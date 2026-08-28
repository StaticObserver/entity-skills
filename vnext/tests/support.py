from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from entity.build import prepare_build, run_build
from entity.objects import add_build, add_pgen, add_source
from entity.paths import Workspace, init_project
from entity.site import add_deps, add_site


class Fixture:
    def __init__(self, *, scheduler: str = "none", mpi: bool = False) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="entity-vnext-test-")
        self.root = Path(self.temp.name)
        self.workspace = Workspace.init(self.root / "workspace", "test-workspace")
        init_project(self.workspace, "project-a")
        self.repo = self.root / "source-repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        fake_entity = self.repo / "fake_entity"
        fake_entity.write_text(
            "#!/usr/bin/env bash\nset -e\nprintf '%s\\n' \"$1\" > invoked-toml.txt\nprintf 'field\\n' > fields.bp\n",
            encoding="utf-8",
        )
        fake_entity.chmod(0o755)
        (self.repo / "README").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        add_source(
            self.workspace,
            "project-a",
            "source-a",
            str(self.repo),
            self.commit,
            self.repo,
        )
        pgen_source = self.root / "pgen-source"
        pgen_source.mkdir()
        (pgen_source / "pgen.hpp").write_text("// pgen\n", encoding="utf-8")
        add_pgen(self.workspace, "project-a", "pgen-a", pgen_source, "pgen.hpp")
        self.site_root = self.root / "site"
        scheduler_config: dict[str, object]
        if scheduler == "slurm":
            tools = self.root / "fake-slurm"
            tools.mkdir()
            self.sbatch = tools / "sbatch"
            self.squeue = tools / "squeue"
            self.sacct = tools / "sacct"
            self.sbatch.write_text("#!/usr/bin/env bash\necho 'Submitted batch job 12345'\n", encoding="utf-8")
            self.squeue.write_text("#!/usr/bin/env bash\necho RUNNING\n", encoding="utf-8")
            self.sacct.write_text("#!/usr/bin/env bash\necho COMPLETED\n", encoding="utf-8")
            for script in (self.sbatch, self.squeue, self.sacct):
                script.chmod(0o755)
            scheduler_config = {
                "kind": "slurm",
                "submit": str(self.sbatch),
                "query": str(self.squeue),
                "accounting": str(self.sacct),
                "defaults": {"partition": "test", "walltime": "00:10:00"},
            }
        else:
            scheduler_config = {"kind": "none"}
        add_site(
            self.workspace,
            {
                "id": "site-a",
                "root": str(self.site_root),
                "transport": {"kind": "local"},
                "scheduler": scheduler_config,
                "environment": {"script": "site-env.sh"},
                "mpi": {"launcher": "env", "template": ["env", "ENTITY_MPI_TASKS={tasks}"]},
            },
        )
        add_deps(
            self.workspace,
            "site-a",
            "deps-a",
            {"backend": "cpu", "mpi": mpi},
            "#!/usr/bin/env bash\nexport ENTITY_TEST_DEPS=1\n",
        )
        add_build(
            self.workspace,
            "project-a",
            "build-a",
            "source-a",
            "pgen-a",
            "site-a",
            "deps-a",
            {
                "build_command": ["cp", "{source}/fake_entity", "{bin}/entity"],
                "executable_from": "{bin}/entity",
            },
            {"mpi": mpi, "gpu": False},
        )

    def build(self) -> None:
        prepare_build(self.workspace, "project-a", "build-a")
        run_build(self.workspace, "project-a", "build-a")

    def close(self) -> None:
        self.temp.cleanup()
