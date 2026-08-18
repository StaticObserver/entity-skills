"""Gate B: PGen / TOML / physics-spec consistency.

Verifies the produced input TOML actually encodes the frozen physics spec,
that the required PGen artifacts exist, and that the submission's declared
fingerprints match the real files. Pure functions are unit-testable; only
``run`` touches the filesystem.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any, Dict, List


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _close(a: float, b: float, rel: float = 1e-9) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def _per_species_values(toml_species: List[Dict[str, Any]], keys: tuple) -> Any:
    """Collect one float per species from the first matching key; None when
    any species lacks all of them."""
    values = []
    for entry in toml_species:
        for key in keys:
            if key in entry:
                try:
                    values.append(float(entry[key]))
                except (TypeError, ValueError):
                    return None
                break
        else:
            return None
    return values


def compare_toml(toml: Dict[str, Any], spec: Dict[str, Any]) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []

    def expect(name: str, got: Any, want: Any) -> None:
        ok = got == want
        checks.append(_check(name, "pass" if ok else "fail",
                             f"expected {want!r}, got {got!r}"))

    sim = toml.get("simulation", {})
    # Engine spelling is case-insensitive in Entity (Snr1 used "srpic").
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

    boundaries = toml.get("grid", {}).get("boundaries", {})
    expect("field_boundaries", boundaries.get("fields"),
           [[b.upper() for b in spec["domain"]["field_boundaries"][:1]]])
    expect("particle_boundaries", boundaries.get("particles"),
           [[b.upper() for b in spec["domain"]["particle_boundaries"][:1]]])

    particles = toml.get("particles", {})
    spec_species = spec["species"]
    toml_species = particles.get("species", [])
    # Entity derives nspec from the [[particles.species]] array when the
    # explicit key is absent (Snr1 layout).
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
    # drift/temperature are accepted from EITHER a [setup] section OR
    # per-species fields; whichever source is present must match the spec.
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
        unique = {float(s["density"]) for s in spec_species}
        if len(unique) == 1:
            expect("densities", [float(d) for d in densities],
                   [unique.pop()] * len(densities))
    want_b = float(spec["initial_fields"]["B"][0])
    bmag = setup.get("Bmag")
    btheta = setup.get("Btheta", 0.0)
    b_source = "[setup]"
    if bmag is None:
        species_b = _per_species_values(toml_species, ("Bmag",))
        if species_b and len(set(species_b)) == 1:
            bmag = species_b[0]
            btheta = 0.0
            b_source = "per-species"
    if bmag is not None:
        ok = _close(float(bmag), want_b) and float(btheta) == 0.0
        checks.append(_check("background_B", "pass" if ok else "fail",
                             f"Bmag={bmag} Btheta={btheta} (want B1={want_b} along x1; source: {b_source})"))
    else:
        # Not a hard fail: the background B may be hard-coded in the pgen
        # itself; Gate D verifies B1 from the produced data.
        checks.append(_check("background_B", "unknown",
                             "no Bmag in [setup] or per-species; background B unverifiable "
                             "from TOML (Gate D checks the data instead)"))

    runtime = spec.get("runtime", {})
    if runtime.get("final_time") is not None:
        expect("final_time", sim.get("runtime"), runtime["final_time"])
    output = toml.get("output", {})
    if runtime.get("field_interval") is not None:
        expect("output_interval", output.get("interval_time"),
               runtime["field_interval"])
    return checks


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_schema_errors(submission: Dict[str, Any]) -> List[str]:
    """Required-key existence check mirroring fixtures/submission.schema.json;
    used only when the jsonschema package is unavailable."""
    missing = []
    if not submission.get("experiment_id"):
        missing.append("experiment_id")
    analysis = submission.get("analysis") or {}
    for key in ("report", "script"):
        if not analysis.get(key):
            missing.append(f"analysis.{key}")
    if not ((submission.get("run") or {}).get("data_root")
            or (submission.get("output") or {}).get("data_root")):
        missing.append("run.data_root (or output.data_root)")
    return missing


def validate_submission_schema(project: Path, submission: Dict[str, Any]) -> Dict[str, str]:
    """Validate submission.json against the schema fixture shipped with the
    task (fixtures/submission.schema.json, copied into the project by
    run_round.sh)."""
    schema_path = Path(project) / "submission.schema.json"
    if not schema_path.is_file():
        return _check("submission_schema_valid", "unknown",
                      "no submission.schema.json fixture in project")
    import json  # noqa: PLC0415
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        missing = _minimal_schema_errors(submission)
        note = "jsonschema not installed; minimal required-key check only"
        detail = f"{note}; missing: {missing}" if missing else f"{note}; required keys present"
        return _check("submission_schema_valid", "unknown", detail)
    try:
        jsonschema.validate(submission, schema)
    except jsonschema.ValidationError as exc:
        return _check("submission_schema_valid", "fail",
                      f"schema violation: {exc.message[:140]}")
    return _check("submission_schema_valid", "pass",
                  "submission.json conforms to submission.schema.json")


def run(project: Path, spec: Dict[str, Any], submission: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    project = Path(project)

    checks.append(validate_submission_schema(project, submission))

    toml_path = project / "input.toml"
    if not toml_path.is_file():
        candidates = sorted(project.glob("*.toml"))
        toml_path = candidates[0] if candidates else toml_path
    if not toml_path.is_file():
        checks.append(_check("input_toml", "fail", "no TOML input found in project"))
        return {"gate": "B-pgen-build", "status": "fail", "checks": checks}

    with toml_path.open("rb") as handle:
        toml = tomllib.load(handle)
    checks.extend(compare_toml(toml, spec))

    declared = submission.get("toml_input", {}).get("sha256")
    if declared:
        actual = _sha256(toml_path)
        checks.append(_check(
            "toml_fingerprint", "pass" if actual == declared else "fail",
            f"submission declares {declared[:16]}…, actual {actual[:16]}…",
        ))

    for name, candidates in (
        ("design_md", ["docs/design.md", "design.md",
                       "pgens/neutral_streaming/docs/design.md"]),
        ("pgen_hpp", ["pgen.hpp", "pgens/neutral_streaming/pgen.hpp"]),
    ):
        found = next((p for p in candidates if (project / p).is_file()), None)
        checks.append(_check(
            name, "pass" if found else "fail",
            f"found at {found}" if found else f"missing (tried {candidates})",
        ))

    statuses = {c["status"] for c in checks}
    status = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return {"gate": "B-pgen-build", "status": status, "checks": checks}
