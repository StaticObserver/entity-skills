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


def compare_toml(toml: Dict[str, Any], spec: Dict[str, Any]) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []

    def expect(name: str, got: Any, want: Any) -> None:
        ok = got == want
        checks.append(_check(name, "pass" if ok else "fail",
                             f"expected {want!r}, got {got!r}"))

    sim = toml.get("simulation", {})
    expect("engine", sim.get("engine"), spec.get("engine"))

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
    expect("nspec", particles.get("nspec"), len(spec_species))
    expect("ppc0", particles.get("ppc0"), float(spec_species[0]["ppc0"]))
    toml_species = particles.get("species", [])
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
    want_drifts = [float(s["four_velocity"][0]) for s in spec_species]
    got_drifts = setup.get("drifts_in_x")
    expect("drifts_in_x", [float(d) for d in got_drifts] if got_drifts else None,
           want_drifts)
    want_temps = [float(s["temperature"]) for s in spec_species]
    got_temps = setup.get("temperatures")
    expect("temperatures", [float(t) for t in got_temps] if got_temps else None,
           want_temps)
    densities = setup.get("densities")
    if densities is not None:
        unique = {float(s["density"]) for s in spec_species}
        if len(unique) == 1:
            expect("densities", [float(d) for d in densities],
                   [unique.pop()] * len(densities))
    bmag = setup.get("Bmag")
    if bmag is not None:
        want_b = float(spec["initial_fields"]["B"][0])
        ok = _close(float(bmag), want_b) and float(setup.get("Btheta", 0.0)) == 0.0
        checks.append(_check("background_B", "pass" if ok else "fail",
                             f"Bmag={bmag} Btheta={setup.get('Btheta')} (want B1={want_b} along x1)"))
    else:
        checks.append(_check("background_B", "fail", "no Bmag in [setup]"))

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


def run(project: Path, spec: Dict[str, Any], submission: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    project = Path(project)

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
