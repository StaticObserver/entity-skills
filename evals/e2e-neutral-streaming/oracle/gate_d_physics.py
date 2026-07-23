"""Gate D: independent physics verification.

Reads the raw simulation output (stats CSV + field/particle snapshots via
nt2py) and recomputes every frozen metric from thresholds.json. The agent's
own analysis is never consulted: declared numbers do not count.

``evaluate`` is pure and unit-testable; ``extract_metrics`` is the only part
that touches nt2py and real data.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def weighted_mean(values, weights=None):
    """Mean of values; weighted by the particle weight column when given.

    Returns (mean, weighted). Falls back to a simple mean when weights are
    absent or non-positive (and says so via the flag).
    """
    values = list(values)
    if weights is not None:
        weights = list(weights)
        total = sum(weights)
        if total > 0:
            return sum(v * w for v, w in zip(values, weights)) / total, True
    return sum(values) / len(values), False


def ux_drift_max(snapshot_species_means):
    """Max over ALL snapshots of |mean_ux - 0.2| / 0.2.

    snapshot_species_means: per snapshot, the per-species mean ux values;
    the per-snapshot value averages across species (as before), the reported
    metric is the max over time — drift anywhere in the run counts, not just
    at the last snapshot.
    """
    deviations = []
    for means in snapshot_species_means:
        avg = sum(means) / len(means)
        deviations.append(abs(avg - 0.2) / 0.2)
    return max(deviations) if deviations else None


def evaluate(metrics: Dict[str, Any], thresholds: Dict[str, Any]) -> List[Dict[str, str]]:
    """Compare extracted metrics against frozen thresholds.

    metrics keys mirror thresholds["metrics"]; a metric absent from the
    extraction yields status "unknown" (fail-closed at the report level).
    """
    spec = thresholds["metrics"]
    checks: List[Dict[str, str]] = []

    counts = metrics.get("particle_counts")
    if counts:
        worst = max(abs(last - first) for first, last in counts.values())
        tol = spec["particle_count_conservation"]["tolerance"]
        ok = worst <= tol
        checks.append(_check(
            "particle_count_conservation",
            "pass" if ok else "fail",
            f"max per-species count change {worst} (tolerance {tol}); counts={counts}",
        ))
    else:
        checks.append(_check("particle_count_conservation", "unknown", "no particle counts extracted"))

    ux = metrics.get("ux_drift_relative_max")
    if ux is not None:
        tol = spec["ux_drift_relative_max"]["tolerance"]
        ok = ux <= tol
        n_snap = metrics.get("ux_snapshots")
        span = f" over {n_snap} snapshots" if n_snap else ""
        how = ("weight-averaged" if metrics.get("ux_weighted")
               else "simple mean (no usable weight column)")
        checks.append(_check(
            "ux_drift_relative_max",
            "pass" if ok else "fail",
            f"max{span} |mean_ux - 0.2| / 0.2 = {ux:.4f} (tolerance {tol}; {how})",
        ))
    else:
        checks.append(_check("ux_drift_relative_max", "unknown", "no particle ux extracted"))

    n_min = metrics.get("min_particles_per_species")
    if n_min is not None:
        floor = spec["min_particles_per_species"]["tolerance"]
        ok = n_min >= floor
        checks.append(_check(
            "min_particles_per_species",
            "pass" if ok else "fail",
            f"last-snapshot sampled particles per species: min {n_min} (minimum {floor})",
        ))
    else:
        checks.append(_check("min_particles_per_species", "unknown",
                             "no per-species particle counts extracted"))

    b1 = metrics.get("b1_mean_deviation_max")
    if b1 is not None:
        tol = spec["b1_mean_absolute_deviation"]["tolerance"]
        ok = b1 <= tol
        checks.append(_check(
            "b1_mean_absolute_deviation",
            "pass" if ok else "fail",
            f"max |mean(B1) - 1.0| = {b1:.6f} (tolerance {tol})",
        ))
    else:
        checks.append(_check("b1_mean_absolute_deviation", "unknown", "no field snapshots extracted"))

    b1sq = metrics.get("b1_squared_relative_drift_max")
    if b1sq is not None:
        tol = spec["b1_squared_relative_drift"]["tolerance"]
        ok = b1sq <= tol
        checks.append(_check(
            "b1_squared_relative_drift",
            "pass" if ok else "fail",
            f"max relative <B1^2> drift = {b1sq:.6f} (tolerance {tol})",
        ))
    else:
        checks.append(_check("b1_squared_relative_drift", "unknown", "no stats B1^2 column"))

    esq = metrics.get("e_squared_max")
    if esq is not None:
        tol = spec["e_squared_noise_ceiling"]["tolerance"]
        ok = esq <= tol
        checks.append(_check(
            "e_squared_noise_ceiling",
            "pass" if ok else "fail",
            f"max <E^2> = {esq:.3e} (ceiling {tol:.1e})",
        ))
    else:
        checks.append(_check("e_squared_noise_ceiling", "unknown", "no stats E^2 columns"))

    edrift = metrics.get("energy_relative_drift_max")
    if edrift is not None:
        tol = spec["energy_relative_drift"]["tolerance"]
        ok = edrift <= tol
        checks.append(_check(
            "energy_relative_drift",
            "pass" if ok else "fail",
            f"max relative total-energy drift = {edrift:.6f} (tolerance {tol})",
        ))
    else:
        checks.append(_check("energy_relative_drift", "unknown", "no total-energy column in stats"))

    mono = metrics.get("stats_time_monotonic")
    if mono is not None:
        checks.append(_check(
            "stats_time_monotonic",
            "pass" if mono else "fail",
            "stats time strictly increasing and finite" if mono else "stats time not monotonic or non-finite",
        ))
    else:
        checks.append(_check("stats_time_monotonic", "unknown", "no stats rows"))

    return checks


def _find_stats_csv(data_root: Path) -> Optional[Path]:
    candidates = sorted(data_root.rglob("*_stats.csv"))
    return candidates[0] if candidates else None


def _read_stats(csv_path: Path) -> Dict[str, Any]:
    with csv_path.open() as handle:
        rows = [
            {k.strip(): v.strip() for k, v in row.items()}
            for row in csv.DictReader(handle, skipinitialspace=True)
        ]
    out: Dict[str, Any] = {"rows": len(rows)}
    if not rows:
        return out

    def column(*names: str) -> Optional[List[float]]:
        for name in names:
            if name in rows[0]:
                try:
                    return [float(r[name]) for r in rows]
                except (ValueError, KeyError):
                    return None
        return None

    time = column("time", "t")
    if time:
        out["stats_time_monotonic"] = all(
            math.isfinite(v) for v in time
        ) and all(b > a for a, b in zip(time, time[1:]))

    e_cols = [column(f"E{i}^2") for i in (1, 2, 3)]
    if all(c is not None for c in e_cols):
        out["e_squared_max"] = max(
            sum(values) for values in zip(*e_cols)  # type: ignore[arg-type]
        )
    b1sq = column("B1^2")
    if b1sq and b1sq[0] != 0:
        out["b1_squared_relative_drift_max"] = max(
            abs(v - b1sq[0]) / abs(b1sq[0]) for v in b1sq
        )
    etot = column("T00", "Etot", "E_tot", "TotalEnergy", "total_energy")
    if etot and etot[0] != 0:
        out["energy_relative_drift_max"] = max(
            abs(v - etot[0]) / abs(etot[0]) for v in etot
        )
    return out


def extract_metrics(data_root: Path) -> Dict[str, Any]:
    """Recompute metrics from raw data. Requires nt2py for snapshots."""
    import numpy as np  # noqa: PLC0415 - deferred: only needed with real data
    import nt2  # noqa: PLC0415

    root = Path(data_root)
    metrics: Dict[str, Any] = {}

    csv_path = _find_stats_csv(root)
    if csv_path:
        metrics.update(_read_stats(csv_path))

    data = nt2.Data(str(root))

    fields = data.fields
    if "Bx" in fields.keys() and len(fields.t.values) > 0:
        deviations = []
        for t in fields.t.values:
            snapshot = fields.sel(t=t)
            deviations.append(abs(float(np.mean(snapshot["Bx"].values)) - 1.0))
        metrics["b1_mean_deviation_max"] = max(deviations)

    particles = data.particles
    times = list(particles.times)
    if times:
        counts: Dict[str, Any] = {}
        per_snapshot_means: List[List[float]] = []
        all_weighted = True
        for t_index, t in enumerate(times):
            species_means: List[float] = []
            for sp in particles.species:
                snapshot = particles.sel(t=t, method="nearest").sel(sp=sp).load(cols=["ux", "w"])
                ux_vals = [float(v) for v in snapshot["ux"].values]
                try:
                    w_vals = [float(v) for v in snapshot["w"].values]
                except Exception:
                    w_vals = None
                mean, weighted = weighted_mean(ux_vals, w_vals)
                all_weighted = all_weighted and weighted
                species_means.append(mean)
                if t_index == 0 or t_index == len(times) - 1:
                    slot = counts.setdefault(str(sp), [0, 0])
                    slot[0 if t_index == 0 else 1] = len(ux_vals)
            per_snapshot_means.append(species_means)
        metrics["particle_counts"] = {k: tuple(v) for k, v in counts.items()}
        metrics["min_particles_per_species"] = min(v[1] for v in counts.values())
        metrics["ux_drift_relative_max"] = ux_drift_max(per_snapshot_means)
        metrics["ux_snapshots"] = len(times)
        metrics["ux_weighted"] = all_weighted
    return metrics


def run(data_root: Path, thresholds: Dict[str, Any]) -> Dict[str, Any]:
    try:
        metrics = extract_metrics(Path(data_root))
    except Exception as exc:  # fail-closed: extraction failure = unknown
        return {
            "gate": "D-physics",
            "status": "unknown",
            "reason": f"metric extraction failed: {exc}",
            "checks": evaluate({}, thresholds),
        }
    checks = evaluate(metrics, thresholds)
    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "D-physics", "status": status, "metrics": metrics, "checks": checks}
