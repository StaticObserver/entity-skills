from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "entity-router", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from entity_router_common import ensure_home, now_utc, save_site_profile  # noqa: E402
from entity_router_flow_runners import run_step  # noqa: E402


class RouterRemoteSourceFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="router-remote-source-")
        self.home = ensure_home(os.path.join(self.temp, "control"))
        self.source = os.path.join(self.temp, "source")
        self.remote = os.path.join(self.temp, "remote")
        self.bin = os.path.join(self.temp, "bin")
        os.makedirs(self.source)
        os.makedirs(self.remote)
        os.makedirs(self.bin)
        with open(os.path.join(self.source, "source.txt"), "w") as handle:
            handle.write("immutable source\n")
        self.write_fake_transport()
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path
        self.profile("source", "local", self.source, "")
        self.profile("remote", "ssh", self.remote, "fake")

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        shutil.rmtree(self.temp)

    def executable(self, name, source):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write("#!%s\n%s" % (sys.executable, source))
        os.chmod(path, 0o755)

    def write_fake_transport(self):
        self.executable("ssh", """import subprocess,sys
command=sys.argv[-1]
sys.exit(subprocess.call(command,shell=True))
""")
        self.executable("scp", """import os,shutil,sys
source,target=sys.argv[-2:]
def local(value):
    value=value.split(':',1)[1] if ':' in value else value
    return value.strip("'")
source,target=local(source),local(target)
parent=os.path.dirname(target)
os.makedirs(parent) if parent and not os.path.isdir(parent) else None
shutil.copy2(source,target)
""")

    def profile(self, site_id, transport, root, alias):
        save_site_profile(self.home, {
            "schema_version": 1, "site_id": site_id, "display_name": site_id,
            "transport": {"kind": transport, "ssh_alias": alias},
            "scheduler": {"kind": "none"},
            "roots": {"source_root": root, "staging_root": root},
            "shared_mappings": [], "created_at": now_utc(), "updated_at": now_utc(),
        })

    def test_remote_snapshot_receipt_and_replay_are_verified(self):
        target = os.path.join(self.remote, "snapshots")
        receipt = os.path.join(target, "flow-receipt.json")
        step = {
            "case_uid": "case-remote", "action_id": "source-remote",
            "action_type": "source.materialize", "execution_site_id": "remote",
            "runner": "source.materialize.v1",
            "read_roots": [{"site_id": "source", "path": self.source}],
            "write_roots": [{"site_id": "remote", "path": target}],
            "protected_paths": [],
            "runner_args": {
                "mode": "snapshot", "source": {"site_id": "source", "path": self.source},
                "target": {"site_id": "remote", "path": target},
                "receipt": {"site_id": "remote", "path": receipt},
            },
        }
        flow_hash = "sha256:" + "a" * 64
        first = run_step(self.home, step, flow_hash)
        replay = run_step(self.home, step, flow_hash)
        self.assertEqual(first.status, "completed")
        self.assertEqual(replay.status, "completed")
        self.assertTrue(os.path.isfile(receipt))
        snapshots = [name for name in os.listdir(target) if os.path.isdir(os.path.join(target, name))]
        self.assertEqual(len(snapshots), 1)


if __name__ == "__main__":
    unittest.main()
