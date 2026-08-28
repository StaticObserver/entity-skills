from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class CliJourneyTest(unittest.TestCase):
    def test_cli_direct_four_object_journey(self) -> None:
        with tempfile.TemporaryDirectory(prefix="entity-cli-journey-") as temp:
            root = Path(temp)
            cli = Path(__file__).resolve().parents[1] / "bin" / "entity"
            workspace = root / "workspace"
            site_root = root / "site"

            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
            executable = repository / "fake_entity"
            executable.write_text(
                "#!/usr/bin/env bash\nprintf 'ok\\n' > result.txt\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
            commit = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
            ).strip()

            pgen = root / "pgen"
            pgen.mkdir()
            (pgen / "pgen.hpp").write_text("// pgen\n", encoding="utf-8")
            toml = root / "input.toml"
            toml.write_text("steps = 1\n", encoding="utf-8")
            env = root / "env.sh"
            env.write_text("#!/usr/bin/env bash\nexport ENTITY_CLI_JOURNEY=1\n", encoding="utf-8")
            site_config = root / "site.json"
            site_config.write_text(
                json.dumps(
                    {
                        "id": "local",
                        "root": str(site_root),
                        "transport": {"kind": "local"},
                        "scheduler": {"kind": "none"},
                    }
                ),
                encoding="utf-8",
            )

            def invoke(*args: str, use_workspace: bool = True) -> dict:
                command = [str(cli)]
                if use_workspace:
                    command.extend(["--workspace", str(workspace)])
                command.extend(args)
                result = subprocess.run(command, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, f"{command}\n{result.stdout}\n{result.stderr}")
                return json.loads(result.stdout)

            invoke("workspace", "init", str(workspace), "--id", "journey", use_workspace=False)
            invoke("project", "init", "--project", "demo")
            invoke("site", "add", "--config", str(site_config))
            invoke("site", "init", "--site", "local")
            invoke(
                "source",
                "add",
                "--project",
                "demo",
                "--id",
                "source-a",
                "--repository",
                str(repository),
                "--commit",
                commit,
                "--checkout",
                str(repository),
            )
            invoke(
                "pgen",
                "add",
                "--project",
                "demo",
                "--id",
                "pgen-a",
                "--from",
                str(pgen),
                "--entry",
                "pgen.hpp",
            )
            invoke("deps", "add", "--site", "local", "--id", "deps-a", "--env", str(env))
            options = json.dumps(
                {
                    "build_command": ["cp", "{source}/fake_entity", "{bin}/entity"],
                    "executable_from": "{bin}/entity",
                }
            )
            invoke(
                "build",
                "create",
                "--project",
                "demo",
                "--id",
                "build-a",
                "--source",
                "source-a",
                "--pgen",
                "pgen-a",
                "--site",
                "local",
                "--deps",
                "deps-a",
                "--options",
                options,
            )
            invoke("build", "prepare", "--project", "demo", "--id", "build-a")
            invoke("build", "run", "--project", "demo", "--id", "build-a")
            invoke(
                "run",
                "create",
                "--project",
                "demo",
                "--id",
                "run-a",
                "--build",
                "build-a",
                "--toml",
                str(toml),
            )
            invoke(
                "run",
                "prepare",
                "--project",
                "demo",
                "--id",
                "run-a",
                "--attempt",
                "attempt-001",
            )
            invoke(
                "run",
                "submit",
                "--project",
                "demo",
                "--id",
                "run-a",
                "--attempt",
                "attempt-001",
            )
            status = {}
            for _ in range(50):
                status = invoke(
                    "run",
                    "status",
                    "--project",
                    "demo",
                    "--id",
                    "run-a",
                    "--attempt",
                    "attempt-001",
                )["record"]
                if status["state"] != "RUNNING":
                    break
                time.sleep(0.02)
            self.assertEqual(status["state"], "COMPLETED")
            self.assertTrue(invoke("check")["ok"])
            self.assertTrue((site_root / "projects/demo/builds/build-a/runs/run-a/data/result.txt").is_file())
            self.assertFalse((workspace / ".ledger").exists())


if __name__ == "__main__":
    unittest.main()
