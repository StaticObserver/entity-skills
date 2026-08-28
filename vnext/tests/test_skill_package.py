from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class SkillPackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vnext = Path(__file__).resolve().parents[1]
        cls.skills = cls.vnext / "skills"

    def test_vnext_exposes_four_concise_skills_without_legacy_ledger(self) -> None:
        expected = {
            "entity-workspace",
            "entity-env-build",
            "entity-pgen",
            "entity-nt2py",
        }
        actual = {path.parent.name for path in self.skills.glob("*/SKILL.md")}
        self.assertEqual(actual, expected)
        self.assertFalse((self.skills / "entity-ledger").exists())

        for name in expected:
            text = (self.skills / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn(f"name: {name}\n", text)
            self.assertIn("\ndescription:", text)

    def test_workspace_skill_wrapper_runs_the_packaged_runtime(self) -> None:
        wrapper = self.skills / "entity-workspace" / "scripts" / "entity"
        completed = subprocess.run(
            [str(wrapper), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), "0.1.0")

    def test_specialist_resources_are_packaged(self) -> None:
        self.assertTrue(
            (self.skills / "entity-pgen" / "references" / "09-toml-config.md").is_file()
        )
        self.assertTrue(
            (self.skills / "entity-nt2py" / "scripts" / "inspect_nt2_data.py").is_file()
        )

if __name__ == "__main__":
    unittest.main()
