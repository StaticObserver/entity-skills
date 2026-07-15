from __future__ import print_function

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
ROUTER_SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
ROUTER = os.path.join(ROUTER_SCRIPTS, "entity_router_state.py")
SITE = os.path.join(ROUTER_SCRIPTS, "entity_router_site.py")


class PGenPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="entity-pgen-preflight-")
        self.home = os.path.join(self.temp, "control")
        self.checkout = os.path.join(self.temp, "arbitrary", "entity")
        os.makedirs(os.path.join(self.checkout, "docs"))
        subprocess.check_call(["git", "init", "-q", self.checkout])
        subprocess.check_call(["git", "-C", self.checkout, "config", "user.email", "test@example.invalid"])
        subprocess.check_call(["git", "-C", self.checkout, "config", "user.name", "Test"])
        with open(os.path.join(self.checkout, "README.md"), "w") as handle:
            handle.write("source\n")
        subprocess.check_call(["git", "-C", self.checkout, "add", "."])
        subprocess.check_call(["git", "-C", self.checkout, "commit", "-qm", "base"])
        code, payload, error = self.run_json(
            SITE, "--router-home", self.home, "add", "--site-id", "laptop",
            "--transport", "local", "--source-root", self.checkout,
            "--staging-root", os.path.join(self.temp, "staging"),
        )
        self.assertEqual(code, 0, (payload, error))

    def tearDown(self):
        shutil.rmtree(self.temp)

    def run_json(self, script, *args):
        process = subprocess.Popen([sys.executable, script] + list(args),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        stdout, stderr = process.communicate()
        return process.returncode, json.loads(stdout), stderr

    def create_case(self):
        code, payload, error = self.run_json(
            ROUTER, "--router-home", self.home, "create",
            "--controller-site", "laptop", "--case-id", "smoke",
            "--source-authority", "laptop:%s" % self.checkout,
            "--pgen-locator", "laptop:%s" % os.path.join(self.checkout, "pgen.hpp"),
            "--toml-locator", "laptop:%s" % os.path.join(self.checkout, "smoke.toml"),
            "--design-locator", "laptop:%s" % os.path.join(self.checkout, "docs", "design.md"),
            "--goal", "exercise registry gate",
        )
        self.assertEqual(code, 0, (payload, error))
        return payload

    def start_action(self, case):
        target = "laptop:%s" % os.path.join(self.checkout, "pgen.hpp")
        code, payload, error = self.run_json(
            ROUTER, "--router-home", self.home, "start-action",
            "--case", case["case_uid"], "--expected-revision", "0",
            "--action-id", "pgen-1", "--action-type", "pgen.design",
            "--owner", "entity-pgen", "--execution-domain", "entity-pgen",
            "--execution-site", "laptop", "--goal", "design",
            "--read-root", "laptop:%s" % self.checkout, "--write-root", target,
        )
        self.assertEqual(code, 0, (payload, error))
        return payload["request"]

    def preflight(self, operation, target, request=None):
        args = ["--router-home", self.home, "--operation", operation, "--target", target]
        if request:
            args.extend(["--action-request", request])
        return self.run_json(PREFLIGHT, *args)

    def test_standalone_operations_are_allowed(self):
        target = "laptop:%s" % os.path.join(self.temp, "standalone.hpp")
        for operation in ["read", "write"]:
            code, payload, error = self.preflight(operation, target)
            self.assertEqual(code, 0, error)
            self.assertTrue(payload["mode"].startswith("standalone-"))

    def test_registry_not_ancestor_controls_managed_source(self):
        case = self.create_case()
        target = "laptop:%s" % os.path.join(self.checkout, "pgen.hpp")
        self.assertFalse(case["case_dir"].startswith(self.checkout))
        code, payload, error = self.preflight("read", target)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["mode"], "managed-readonly")
        code, payload, unused = self.preflight("write", target)
        self.assertEqual(code, 2)
        self.assertEqual(payload["mode"], "router-required")

    def test_active_action_checks_site_path_and_revision(self):
        case = self.create_case()
        request = self.start_action(case)
        target = "laptop:%s" % os.path.join(self.checkout, "pgen.hpp")
        code, payload, error = self.preflight("write", target, request)
        self.assertEqual(code, 0, error)
        self.assertEqual(payload["mode"], "managed-write")

        for invalid in [
            "laptop:%s" % os.path.join(self.checkout, "outside.hpp"),
            "other:%s" % os.path.join(self.checkout, "pgen.hpp"),
        ]:
            code, payload, unused = self.preflight("write", invalid, request)
            self.assertEqual(code, 2)
            self.assertFalse(payload["allowed"])

        with open(request) as handle:
            stale = json.load(handle)
        stale["case_revision"] = 99
        with open(request, "w") as handle:
            json.dump(stale, handle)
        code, payload, unused = self.preflight("write", target, request)
        self.assertEqual(code, 2)
        self.assertIn("revision", payload["reason"])


if __name__ == "__main__":
    unittest.main()
