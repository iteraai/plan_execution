from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import install


class InstallSkillTests(unittest.TestCase):
    def test_install_skill_copies_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source"
            destination_dir = temp_path / "destination"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text("skill")
            (source_dir / "scripts" / "execute.py").write_text("print('ok')\n")

            installed_path = install.install_skill(
                source_dir=source_dir, destination_dir=destination_dir
            )

            self.assertEqual(installed_path, destination_dir)
            self.assertEqual((destination_dir / "SKILL.md").read_text(), "skill")
            self.assertEqual(
                (destination_dir / "scripts" / "execute.py").read_text(),
                "print('ok')\n",
            )

    def test_install_skill_renders_claude_paths_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "execute-approved-plan"
            destination_dir = temp_path / "claude-skills" / "execute-approved-plan"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: execute-approved-plan",
                        "description: Test skill",
                        "---",
                        "",
                        "Install path: `~/.codex/skills/execute-approved-plan`.",
                        "Run `python3 ~/.codex/skills/execute-approved-plan/scripts/execute_approved_plan.py`.",
                    ]
                )
                + "\n"
            )
            (source_dir / "README.md").write_text(
                "\n".join(
                    [
                        "# execute-approved-plan",
                        "",
                        "Engineer-facing public Codex skill for tests.",
                        "Install path: `~/.codex/skills/execute-approved-plan`.",
                    ]
                )
                + "\n"
            )

            install.install_skill(
                source_dir=source_dir,
                destination_dir=destination_dir,
                target="claude",
            )

            rendered_skill = (destination_dir / "SKILL.md").read_text()
            self.assertIn("disable-model-invocation: true", rendered_skill)
            self.assertIn("argument-hint: [canonical-task-id]", rendered_skill)
            self.assertIn(
                f"`{install.path_for_display(destination_dir)}`",
                rendered_skill,
            )
            self.assertNotIn("~/.codex/skills/execute-approved-plan", rendered_skill)

            rendered_readme = (destination_dir / "README.md").read_text()
            self.assertIn("public Claude Code skill", rendered_readme)
            self.assertIn(
                f"`{install.path_for_display(destination_dir)}`",
                rendered_readme,
            )

    def test_install_skills_installs_discovered_catalog_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            skills_root = temp_path / "skills"
            destination_root = temp_path / "installed"

            for skill_name in [
                "download-task-specification",
                "download-pr-specification",
            ]:
                skill_dir = skills_root / skill_name
                (skill_dir / "scripts").mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"{skill_name}\n")
                (skill_dir / "scripts" / "entry.py").write_text("print('ok')\n")

            installed_paths = install.install_skills(
                skills_root=skills_root,
                destination_root=destination_root,
            )

            self.assertEqual(
                [path.name for path in installed_paths],
                ["download-pr-specification", "download-task-specification"],
            )
            self.assertTrue(
                (destination_root / "download-task-specification" / "SKILL.md").exists()
            )
            self.assertTrue(
                (destination_root / "download-pr-specification" / "SKILL.md").exists()
            )


if __name__ == "__main__":
    unittest.main()
