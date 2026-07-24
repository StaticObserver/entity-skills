from __future__ import print_function

import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


PGEN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(PGEN_ROOT))
PREFLIGHT = os.path.join(PGEN_ROOT, "scripts", "pgen_preflight.py")
LEDGER_SCRIPTS = os.path.join(ROOT, "skills", "entity-ledger", "scripts")
if LEDGER_SCRIPTS not in sys.path:
    sys.path.insert(0, LEDGER_SCRIPTS)

import tomllib  # noqa: E402


FULL_TOML = """\
[simulation]
  name    = "card_test"
  engine  = "SRPIC"
  runtime = 42.0

[grid]
  resolution = [64, 64]
  extent     = [[-1.0, 1.0], [-1.0, 1.0]]

  [grid.metric]
    metric = "Minkowski"
    coord  = "cartesian"

[boundaries]
  fields    = [["PERIODIC"], ["PERIODIC"]]
  particles = [["PERIODIC"], ["PERIODIC"]]

[algorithms]
  current_filters = 0

  [algorithms.timestep]
    CFL = 0.45

[particles]
  ppc0  = 16.0
  nspec = 2

  [[particles.species]]
    label    = "electrons"
    mass     = 1.0
    charge   = -1.0
    maxnpart = 1000000

  [[particles.species]]
    label    = "positrons"
    mass     = 1.0
    charge   = 1.0
    maxnpart = 1000000

[setup]
  drift_ux    = 0.1
  temperature = 0.01

[output]
  format        = "BPFile"
  interval_time = 10.0

  [output.fields]
    quantities = ["E", "B"]
"""

SPARSE_TOML = """\
[simulation]
  name = "sparse"
"""


def load_preflight_module():
    spec = importlib.util.spec_from_file_location("pgen_preflight", PREFLIGHT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParameterCardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-pgen-card-")
        self.input_path = os.path.join(self.temp, "input.toml")
        self.record_path = self.input_path + ".decisions.json"

    def tearDown(self):
        shutil.rmtree(self.temp)

    def write_input(self, content=FULL_TOML):
        with open(self.input_path, "w") as stream:
            stream.write(content)

    def run_json(self, *args):
        process = subprocess.Popen([sys.executable, PREFLIGHT] + list(args),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        stdout, stderr = process.communicate()
        return process.returncode, json.loads(stdout), stderr

    def run_raw(self, *args):
        process = subprocess.Popen([sys.executable, PREFLIGHT] + list(args),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr

    def card(self):
        code, payload, error = self.run_json("card", self.input_path)
        self.assertEqual(code, 0, error)
        return payload

    def test_card_extracts_tiered_fields(self):
        self.write_input()
        card = self.card()
        self.assertEqual(card["schema_version"], 1)
        self.assertEqual(card["kind"], "entity-parameter-card")
        self.assertEqual(card["domain"], "simulation")
        fields = card["fields"]
        self.assertEqual(fields["grid.resolution"], {"value": [64, 64], "tier": 1})
        self.assertEqual(fields["grid.extent"],
                         {"value": [[-1.0, 1.0], [-1.0, 1.0]], "tier": 1})
        self.assertEqual(fields["particles.ppc0"], {"value": 16.0, "tier": 1})
        self.assertEqual(fields["particles.nspec"], {"value": 2, "tier": 1})
        self.assertEqual(fields["particles.species.0.maxnpart"],
                         {"value": 1000000, "tier": 1})
        self.assertEqual(fields["particles.species.1.charge"],
                         {"value": 1.0, "tier": 1})
        self.assertEqual(fields["boundaries.fields"],
                         {"value": [["PERIODIC"], ["PERIODIC"]], "tier": 1})
        self.assertEqual(fields["simulation.runtime"], {"value": 42.0, "tier": 1})
        self.assertEqual(fields["algorithms.timestep.CFL"], {"value": 0.45, "tier": 1})
        self.assertEqual(fields["setup.drift_ux"], {"value": 0.1, "tier": 1})
        self.assertEqual(fields["setup.temperature"], {"value": 0.01, "tier": 1})
        self.assertEqual(fields["output.format"], {"value": "BPFile", "tier": 2})
        self.assertEqual(fields["output.interval_time"], {"value": 10.0, "tier": 2})
        self.assertEqual(card["warnings"], [])

    def test_card_digest_is_stable_and_wellformed(self):
        self.write_input()
        first = self.card()
        second = self.card()
        self.assertEqual(first["digest"], second["digest"])
        canonical = json.dumps(first["fields"], sort_keys=True, separators=(",", ":"))
        expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(first["digest"], expected)
        with open(self.input_path, "rb") as stream:
            self.assertEqual(first["input_sha256"],
                             hashlib.sha256(stream.read()).hexdigest())

    def test_card_warns_on_missing_tier1_categories(self):
        self.write_input(SPARSE_TOML)
        card = self.card()
        joined = "\n".join(card["warnings"])
        for category in ["grid", "particle count", "species", "boundary", "timestep"]:
            self.assertIn(category, joined)

    def test_confirm_writes_record_matching_contract(self):
        self.write_input()
        code, payload, error = self.run_json(
            "confirm", self.input_path, "--by", "test-agent")
        self.assertEqual(code, 0, error)
        self.assertTrue(os.path.exists(self.record_path))
        with open(self.record_path) as stream:
            record = json.load(stream)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["kind"], "entity-pgen.simulation-confirmation")
        self.assertEqual(record["confirmed_by"], "test-agent")
        self.assertEqual(record["defaults"], False)
        datetime.datetime.fromisoformat(record["confirmed_at"])
        card = self.card()
        self.assertEqual(record["card"], card)
        self.assertEqual(record["input_sha256"], card["input_sha256"])
        self.assertEqual(payload["record_path"], os.path.abspath(self.record_path))
        self.assertEqual(payload["card"], card)

    def test_confirm_requires_by(self):
        self.write_input()
        code, stdout, stderr = self.run_raw("confirm", self.input_path)
        self.assertEqual(code, 2)
        self.assertIn("--by", stderr)
        self.assertFalse(os.path.exists(self.record_path))

    def test_confirm_defaults_flag(self):
        self.write_input()
        code, payload, error = self.run_json(
            "confirm", self.input_path, "--by", "test-agent", "--confirm-defaults")
        self.assertEqual(code, 0, error)
        with open(self.record_path) as stream:
            self.assertEqual(json.load(stream)["defaults"], True)

    def test_confirm_updates_after_toml_change(self):
        self.write_input()
        self.run_json("confirm", self.input_path, "--by", "test-agent")
        with open(self.record_path) as stream:
            original = json.load(stream)
        self.write_input(FULL_TOML.replace("runtime = 42.0", "runtime = 43.0"))
        code, payload, error = self.run_json(
            "confirm", self.input_path, "--by", "test-agent")
        self.assertEqual(code, 0, error)
        with open(self.record_path) as stream:
            updated = json.load(stream)
        self.assertNotEqual(original["input_sha256"], updated["input_sha256"])
        self.assertNotEqual(original["card"]["digest"], updated["card"]["digest"])
        self.assertEqual(updated["card"]["fields"]["simulation.runtime"],
                         {"value": 43.0, "tier": 1})
        with open(self.input_path, "rb") as stream:
            self.assertEqual(updated["input_sha256"],
                             hashlib.sha256(stream.read()).hexdigest())

    def test_fallback_parser_agrees_with_tomllib(self):
        module = load_preflight_module()
        expected = tomllib.loads(FULL_TOML)
        actual = module.fallback_parse_toml(FULL_TOML)
        self.assertEqual(actual, expected)
        fields, warnings = module.extract_fields(actual)
        self.assertEqual(warnings, [])
        self.assertEqual(fields["grid.resolution"], {"value": [64, 64], "tier": 1})
        self.assertEqual(fields["particles.species.1.maxnpart"],
                         {"value": 1000000, "tier": 1})


if __name__ == "__main__":
    unittest.main()
