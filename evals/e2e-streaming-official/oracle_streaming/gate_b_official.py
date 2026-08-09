"""Gate B: official-PGen / TOML / physics-spec consistency.

Unlike the neutral-streaming variant there is no PGen authoring to verify:
the official streaming PGen must be used UNMODIFIED, proven by the
submission's official_pgen fingerprint matching the spec-pinned sha256 of
the source-cache pgen.hpp. The produced TOML must encode the frozen spec
(official [setup] layout: drifts_in_x / densities / temperatures arrays),
and the submission's declared TOML fingerprint must match the real file.
Pure functions are unit-testable; only ``run`` touches the filesystem.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any, Dict, List

from oracle_streaming.gate_b_pgen_build import (  # noqa: E402  (reuse neutral helpers)
    _check,
    _close,
    _per_species_values,
    validate_submission_schema,
)


def compare_streaming_toml(toml: Dict[str, Any], spec: Dict[str, Any]) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []

    def expect(name: str, got: Any, want: Any) -> None:
        ok = got == want
        checks.append(_check(name, "pass" if ok else "fail",
                             f"expected {want!r}, got {got!r}"))

    sim = toml.get("simulation", {})
    got_engine = sim.get("engine")
    want_engine = spec.get("engine")
    engine_ok = (
        isinstance(got_engine, str) and isinstance(want_engine, str)
        and got_engine.lower() == want_engine.lower()
    )
    checks.append(_check("engine", "pass" if engine_ok else "fail",
                         f"expected {want_engine!r}, got {got_engine!r} (case-insensitive)"))

    grid = toml.get("grid", {})
    expect("resolution", grid.get("resolution"), spec["domain"]["active_cells"])
    extent = grid.get("extent")
    want_extent = [list(spec["domain"]["x1"])]
    got_extent = [list(e) for e in extent] if extent else None
    expect("extent", got_extent, want_extent)

    boundaries = grid.get("boundaries", {})
    expect("field_boundaries", boundaries.get("fields"),
           [[b.upper() for b in spec["domain"]["field_boundaries"][:1]]])
    expect("particle_boundaries", boundaries.get("particles"),
           [[b.upper() for b in spec["domain"]["particle_boundaries"][:1]]])

    particles = toml.get("particles", {})
    spec_species = spec["species"]
    toml_species = particles.get("species", [])
    nspec = particles.get("nspec")
    nspec_source = "explicit"
    if nspec is None and toml_species:
        nspec = len(toml_species)
        nspec_source = "derived from species array"
    checks.append(_check("nspec", "pass" if nspec == len(spec_species) else "fail",
                         f"expected {len(spec_species)}, got {nspec!r} ({nspec_source})"))
    expect("ppc0", particles.get("ppc0"), float(spec_species[0]["ppc0"]))
    if len(toml_species) == len(spec_species):
        for idx, (got, want) in enumerate(zip(toml_species, spec_species)):
            expect(f"species[{idx}].charge", got.get("charge"),
                   float(want["charge_sign"]))
            expect(f"species[{idx}].mass", got.get("mass"),
                   float(want["mass_ratio"]))
    else:
        checks.append(_check("species_table", "fail",
                             f"TOML has {len(toml_species)} species, spec has {len(spec_species)}"))

    setup = toml.get("setup", {})
    # The official streaming layout uses flat [setup] arrays; per-species
    # fields are accepted as an equivalent encoding.
    want_drifts = [float(s["four_velocity"][0]) for s in spec_species]
    got_drifts = setup.get("drifts_in_x")
    drift_source = "[setup].drifts_in_x"
    if got_drifts is None:
        got_drifts = _per_species_values(
            toml_species, ("drift", "drift_ux", "drift_x", "ux_drift", "drift_in_x"))
        drift_source = "per-species"
    elif got_drifts:
        got_drifts = [float(d) for d in got_drifts]
    expect("drifts_in_x", got_drifts if got_drifts else None, want_drifts)
    checks[-1]["detail"] += f" (source: {drift_source})"
    want_temps = [float(s["temperature"]) for s in spec_species]
    got_temps = setup.get("temperatures")
    temp_source = "[setup].temperatures"
    if got_temps is None:
        got_temps = _per_species_values(toml_species, ("temperature", "temp"))
        temp_source = "per-species"
    elif got_temps:
        got_temps = [float(t) for t in got_temps]
    expect("temperatures", got_temps if got_temps else None, want_temps)
    checks[-1]["detail"] += f" (source: {temp_source})"
    densities = setup.get("densities")
    if densities is not None:
        # the official layout is pairwise densities (nspec/2 entries)
        want_pair = sorted({float(s["density"]) for s in spec_species},
                           reverse=True)
        got = [float(d) for d in densities]
        ok = sorted(set(got), reverse=True) == want_pair
        checks.append(_check("densities", "pass" if ok else "fail",
                             f"pairwise densities: expected {want_pair}, got {got}"))

    # classic unmagnetized two-stream: Bmag must be absent or zero
    bmag = setup.get("Bmag")
    if bmag is not None:
        ok = _close(float(bmag), 0.0)
        checks.append(_check("background_B", "pass" if ok else "fail",
                             f"expected unmagnetized (Bmag=0/absent), got Bmag={bmag}"))

    runtime = spec.get("runtime", {})
    if runtime.get("final_time") is not None:
        expect("final_time", sim.get("runtime"), runtime["final_time"])
    output = toml.get("output", {})
    if runtime.get("field_interval") is not None:
        expect("output_interval", output.get("interval_time"),
               runtime["field_interval"])
    particle_output = output.get("particles", {})
    stride = particle_output.get("stride")
    stride_max = spec.get("output", {}).get("particle_stride_max")
    if stride is not None and stride_max is not None:
        ok = int(stride) <= int(stride_max)
        checks.append(_check("particle_stride", "pass" if ok else "fail",
                             f"stride {stride} vs max {stride_max}"))
    return checks


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_official_pgen(spec: Dict[str, Any], submission: Dict[str, Any]) -> Dict[str, str]:
    """The submission must pin the spec-pinned official pgen fingerprint —
    claiming any other hash means the official PGen was modified (or
    swapped), which this evaluation forbids."""
    want = spec.get("official_pgen", {})
    got = submission.get("official_pgen", {})
    if not want.get("sha256"):
        return _check("official_pgen_fingerprint", "unknown",
                      "spec carries no official_pgen.sha256")
    if got.get("name") != want.get("name"):
        return _check("official_pgen_fingerprint", "fail",
                      f"submission names pgen {got.get('name')!r}, expected {want.get('name')!r}")
    if got.get("sha256") != want["sha256"]:
        return _check(
            "official_pgen_fingerprint", "fail",
            "declared pgen sha256 %s… differs from the pinned official "
            "%s… — the official streaming PGen must be used unmodified"
            % (str(got.get("sha256"))[:16], want["sha256"][:16]))
    return _check("official_pgen_fingerprint", "pass",
                  "official streaming pgen.hpp fingerprint matches the spec pin")


def run(project: Path, spec: Dict[str, Any], submission: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    project = Path(project)

    checks.append(validate_submission_schema(project, submission))
    checks.append(check_official_pgen(spec, submission))

    toml_path = project / "input.toml"
    if not toml_path.is_file():
        candidates = sorted(project.glob("*.toml"))
        # 0.7.0 workspace layout: the TOML may live in the source authority
        candidates += sorted(project.glob("source/*.toml"))
        toml_path = candidates[0] if candidates else toml_path
    if not toml_path.is_file():
        checks.append(_check("input_toml", "fail", "no TOML input found in project"))
        return {"gate": "B-official-pgen-build", "status": "fail", "checks": checks}

    with toml_path.open("rb") as handle:
        toml = tomllib.load(handle)
    checks.extend(compare_streaming_toml(toml, spec))

    declared = submission.get("toml_input", {}).get("sha256")
    if declared:
        actual = _sha256(toml_path)
        checks.append(_check(
            "toml_fingerprint", "pass" if actual == declared else "fail",
            f"submission declares {declared[:16]}…, actual {actual[:16]}…",
        ))

    design = next(
        (p for p in ["docs/design.md", "design.md",
                     "source/docs/design.md", "source/design.md"]
         if (project / p).is_file()),
        None,
    )
    checks.append(_check(
        "design_md", "pass" if design else "fail",
        f"found at {design}" if design else "missing (parameter rationale required)",
    ))

    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "B-official-pgen-build", "status": status, "checks": checks}
