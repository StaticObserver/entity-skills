from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import EntityError
from .records import load_json, require_id, write_json


WORKSPACE_FILE = "workspace.json"


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def discover(cls, explicit: str | Path | None = None) -> "Workspace":
        if explicit:
            root = Path(explicit).expanduser().resolve()
            return cls.require(root)
        env = os.environ.get("ENTITY_WORKSPACE")
        if env:
            return cls.require(Path(env).expanduser().resolve())
        current = Path.cwd().resolve()
        for candidate in (current, *current.parents):
            if (candidate / WORKSPACE_FILE).is_file():
                return cls(candidate)
        raise EntityError(
            "workspace not found; pass --workspace or set ENTITY_WORKSPACE",
            code="workspace_not_found",
        )

    @classmethod
    def require(cls, root: Path) -> "Workspace":
        if not (root / WORKSPACE_FILE).is_file():
            raise EntityError(f"workspace.json not found under {root}", code="workspace_not_found")
        return cls(root)

    @classmethod
    def init(cls, root: Path, workspace_id: str | None = None) -> "Workspace":
        root = root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        marker = root / WORKSPACE_FILE
        if marker.exists():
            raise EntityError(f"workspace already exists: {root}", code="already_exists")
        workspace_id = require_id(workspace_id or root.name, "workspace id")
        write_json(marker, {"schema_version": 1, "id": workspace_id}, replace=False)
        (root / "projects").mkdir()
        (root / "sites").mkdir()
        return cls(root)

    def metadata(self) -> dict:
        return load_json(self.root / WORKSPACE_FILE)

    def project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / require_id(project_id, "project id")

    def require_project(self, project_id: str) -> Path:
        path = self.project_dir(project_id)
        if not (path / "project.json").is_file():
            raise EntityError(f"project not found: {project_id}", code="not_found")
        return path

    def site_file(self, site_id: str) -> Path:
        return self.root / "sites" / f"{require_id(site_id, 'site id')}.json"

    def source_dir(self, project_id: str, source_id: str) -> Path:
        return self.require_project(project_id) / "sources" / require_id(source_id, "source id")

    def pgen_dir(self, project_id: str, pgen_id: str) -> Path:
        return self.require_project(project_id) / "pgens" / require_id(pgen_id, "pgen id")

    def build_dir(self, project_id: str, build_id: str) -> Path:
        return self.require_project(project_id) / "builds" / require_id(build_id, "build id")

    def run_dir(self, project_id: str, build_id: str, run_id: str) -> Path:
        return self.build_dir(project_id, build_id) / "runs" / require_id(run_id, "run id")

    def find_run(self, project_id: str, run_id: str, build_id: str | None = None) -> tuple[str, Path]:
        require_id(run_id, "run id")
        if build_id:
            path = self.run_dir(project_id, build_id, run_id)
            if not (path / "run.json").is_file():
                raise EntityError(f"run not found: {run_id}", code="not_found")
            return build_id, path
        builds = self.require_project(project_id) / "builds"
        matches = sorted(builds.glob(f"*/runs/{run_id}/run.json")) if builds.exists() else []
        if not matches:
            raise EntityError(f"run not found: {run_id}", code="not_found")
        if len(matches) > 1:
            raise EntityError(f"run id is ambiguous: {run_id}; pass --build", code="ambiguous")
        path = matches[0].parent
        return path.parents[1].name, path


def init_project(workspace: Workspace, project_id: str) -> Path:
    project_id = require_id(project_id, "project id")
    root = workspace.project_dir(project_id)
    if root.exists():
        raise EntityError(f"project already exists: {project_id}", code="already_exists")
    for relative in ("sources", "pgens", "builds", "scripts", "analysis"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    write_json(root / "project.json", {"schema_version": 1, "id": project_id}, replace=False)
    return root
