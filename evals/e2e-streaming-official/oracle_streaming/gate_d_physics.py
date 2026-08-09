"""Gate D: independent physics verification (two-stream growth variant).

Reads the raw simulation output (stats CSV + particle snapshots via nt2py)
and recomputes every frozen metric from thresholds.json. The agent's own
analysis is never consulted: declared numbers do not count.

Two-stream is GROWTH physics, so the frozen metrics are: the E1^2 series
must rise exponentially out of the noise with a growth rate inside the
gold-run band, saturate before the final time, while total energy drift
stays bounded and particle counts are exactly conserved. (The neutral
counterpart's conservation criteria — drift retention, B1 background,
E^2 noise ceiling — do not apply and were removed at the 2026-08-09
threshold freeze.)

``evaluate`` and ``fit_growth`` are pure and unit-testable;
``extract_metrics`` is the only part that touches nt2py and real data.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def fit_growth(time: List[float], e1sq: List[float]) -> Optional[Dict[str, Any]]:
    """Least-squares fit of ln(<E1^2>) over the linear-growth window.

    Window: first point above 10x the initial noise floor through the peak.
    The field amplitude grows at gamma, so the E^2 slope is 2*gamma.  Returns
    None when no usable growth window exists.
    """
    points = [(t, e) for t, e in zip(time, e1sq) if e > 0 and math.isfinite(e)]
    if len(points) < 4:
        return None
    floor = points[0][1]
    peak_index = max(range(len(points)), key=lambda i: points[i][1])
    start = next((i for i, (_, e) in enumerate(points) if e > 10.0 * floor), None)
    if start is None or peak_index - start < 2:
        return None
    window = points[start : peak_index + 1]
    n = len(window)
    sum_t = sum(t for t, _ in window)
    sum_l = sum(math.log(e) for _, e in window)
    sum_tl = sum(t * math.log(e) for t, e in window)
    sum_tt = sum(t * t for t, _ in window)
    denom = n * sum_tt - sum_t * sum_t
    if not denom:
        return None
    slope2 = (n * sum_tl - sum_t * sum_l) / denom
    return {
        "gamma_field": slope2 / 2.0,
        "window": [window[0][0], window[-1][0]],
        "window_points": n,
        "noise_floor": floor,
        "peak": points[peak_index][1],
        "peak_time": points[peak_index][0],
        "growth_factor": points[peak_index][1] / floor,
    }


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

    mono = metrics.get("stats_time_monotonic")
    if mono is not None:
        checks.append(_check(
            "stats_time_monotonic",
            "pass" if mono else "fail",
            "stats time strictly increasing and finite" if mono else "stats time not monotonic or non-finite",
        ))
    else:
        checks.append(_check("stats_time_monotonic", "unknown", "no stats rows"))

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

    gamma = metrics.get("e1_growth_rate")
    if gamma is not None:
        lo, hi = spec["e1_growth_rate"]["band"]
        ok = lo <= gamma <= hi
        window = metrics.get("e1_growth_window") or []
        checks.append(_check(
            "e1_growth_rate",
            "pass" if ok else "fail",
            f"fitted growth rate gamma = {gamma:.4f} (band [{lo}, {hi}]; "
            f"window {window}, {metrics.get('e1_growth_window_points')} points)",
        ))
    else:
        checks.append(_check("e1_growth_rate", "unknown", "no linear-growth window in <E1^2>(t)"))

    factor = metrics.get("e1_squared_growth_factor")
    if factor is not None:
        minimum = spec["e1_squared_growth_factor"]["minimum"]
        ok = factor >= minimum
        checks.append(_check(
            "e1_squared_growth_factor",
            "pass" if ok else "fail",
            f"<E1^2> grew {factor:.3e}x over the noise floor (minimum {minimum:.0e})",
        ))
    else:
        checks.append(_check("e1_squared_growth_factor", "unknown", "no <E1^2> series"))

    saturated = metrics.get("saturated_before_final")
    if saturated is not None:
        peak_time = metrics.get("saturation_time")
        checks.append(_check(
            "saturation_before_final",
            "pass" if saturated else "fail",
            f"<E1^2> peaks at t={peak_time}, before the final time"
            if saturated else
            f"<E1^2> still peaks at the final time (t={peak_time}); runtime too short",
        ))
    else:
        checks.append(_check("saturation_before_final", "unknown", "no <E1^2> series"))

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
    e1sq = column("E1^2", "Ex^2", "Ex2")
    if time:
        out["stats_time_monotonic"] = all(
            math.isfinite(v) for v in time
        ) and all(b > a for a, b in zip(time, time[1:]))
    if time and e1sq:
        growth = fit_growth(time, e1sq)
        if growth is not None:
            out["e1_growth_rate"] = growth["gamma_field"]
            out["e1_growth_window"] = growth["window"]
            out["e1_growth_window_points"] = growth["window_points"]
            out["e1_squared_growth_factor"] = growth["growth_factor"]
            out["saturation_time"] = growth["peak_time"]
            out["saturated_before_final"] = growth["peak_time"] < time[-1]
    etot = column("T00", "Etot", "E_tot", "TotalEnergy", "total_energy")
    if etot and etot[0] != 0:
        out["energy_relative_drift_max"] = max(
            abs(v - etot[0]) / abs(etot[0]) for v in etot
        )
    return out


def extract_metrics(data_root: Path) -> Dict[str, Any]:
    """Recompute metrics from raw data. Requires nt2py for particle counts."""
    root = Path(data_root)
    metrics: Dict[str, Any] = {}

    csv_path = _find_stats_csv(root)
    if csv_path:
        metrics.update(_read_stats(csv_path))

    import nt2  # noqa: PLC0415 - deferred: only needed with real data
    data = nt2.Data(str(root))
    particles = data.particles
    times = list(particles.times)
    if times:
        counts: Dict[str, Any] = {}
        for sp in particles.species:
            for t_index, t in ((0, times[0]), (1, times[-1])):
                snapshot = particles.sel(t=t, method="nearest").sel(sp=sp).load(cols=["ux"])
                slot = counts.setdefault(str(sp), [0, 0])
                slot[t_index] = int(snapshot["ux"].size)
        metrics["particle_counts"] = {k: tuple(v) for k, v in counts.items()}
        metrics["min_particles_per_species"] = min(v[1] for v in counts.values())
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
