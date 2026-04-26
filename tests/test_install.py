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

    def test_install_skill_bundles_shared_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "download-task-specification"
            destination_dir = temp_path / "destination"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text("skill")
            (source_dir / "scripts" / "download_task_specification.py").write_text(
                "print('ok')\n"
            )

            install.install_skill(
                source_dir=source_dir,
                destination_dir=destination_dir,
            )

            self.assertTrue(
                (destination_dir / "scripts" / "plan_execution" / "auth.py").is_file()
            )
            self.assertTrue(
                (
                    destination_dir
                    / "scripts"
                    / "plan_execution"
                    / "graphql_client.py"
                ).is_file()
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
            self.assertIn('argument-hint: "[canonical-task-id]"', rendered_skill)
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

    def test_install_skill_renders_copilot_project_skill_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "download-task-specification"
            destination_dir = (
                temp_path
                / "project"
                / ".github"
                / "skills"
                / "download-task-specification"
            )
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: download-task-specification",
                        "description: Test skill",
                        "---",
                        "",
                        "Install path: `~/.codex/skills/download-task-specification`.",
                        "Run `python3 ~/.codex/skills/download-task-specification/scripts/download_task_specification.py`.",
                    ]
                )
                + "\n"
            )
            (source_dir / "README.md").write_text(
                "\n".join(
                    [
                        "# download-task-specification",
                        "",
                        "Engineer-facing public Codex skill for tests.",
                        "Install path: `~/.codex/skills/download-task-specification`.",
                    ]
                )
                + "\n"
            )

            installed_path = install.install_skill(
                source_dir=source_dir,
                destination_dir=destination_dir,
                target="copilot",
            )

            self.assertEqual(installed_path, destination_dir)

            rendered_skill = (destination_dir / "SKILL.md").read_text()
            self.assertIn(
                f"`{install.path_for_display(destination_dir)}`",
                rendered_skill,
            )
            self.assertNotIn(
                "~/.codex/skills/download-task-specification",
                rendered_skill,
            )
            self.assertIn("description: Test skill", rendered_skill)

            rendered_readme = (destination_dir / "README.md").read_text()
            self.assertIn("GitHub Copilot agent skill", rendered_readme)
            self.assertIn(
                f"`{install.path_for_display(destination_dir)}`",
                rendered_readme,
            )

    def test_install_skill_uses_source_skill_name_for_custom_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "download-pr-specification"
            destination_dir = temp_path / "claude-skills" / "custom-name"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: download-pr-specification",
                        "description: Test skill",
                        "---",
                        "",
                        "Install path: `~/.codex/skills/download-pr-specification`.",
                        "Run `python3 ~/.codex/skills/download-pr-specification/scripts/download_pr_specification.py`.",
                    ]
                )
                + "\n"
            )
            (source_dir / "README.md").write_text(
                "\n".join(
                    [
                        "# download-pr-specification",
                        "",
                        "Engineer-facing public Codex skill for tests.",
                        "Install path: `~/.codex/skills/download-pr-specification`.",
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
            self.assertIn(
                f"`{install.path_for_display(destination_dir)}`",
                rendered_skill,
            )
            self.assertNotIn(
                "~/.codex/skills/download-pr-specification",
                rendered_skill,
            )
            self.assertIn("disable-model-invocation: true", rendered_skill)
            self.assertIn(
                'argument-hint: "[canonical-task-id] '
                '[pull-request-position-or-planned-pull-request-id]"',
                rendered_skill,
            )

    def test_install_skill_creates_cursor_rule_and_asset_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_root = temp_path / "project"
            destination_root = project_root / ".cursor" / "rules"
            source_dir = temp_path / "download-task-specification"
            destination_dir = destination_root / "download-task-specification"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        "name: download-task-specification",
                        "description: Download a task specification.",
                        "---",
                        "",
                        "Install path: `~/.codex/skills/download-task-specification`.",
                        "Run `python3 ~/.codex/skills/download-task-specification/scripts/download_task_specification.py`.",
                    ]
                )
                + "\n"
            )
            (source_dir / "README.md").write_text(
                "\n".join(
                    [
                        "# download-task-specification",
                        "",
                        "Engineer-facing public Codex skill for tests.",
                    ]
                )
                + "\n"
            )
            (source_dir / "input-contract.json").write_text("{}\n")

            installed_path = install.install_skill(
                source_dir=source_dir,
                destination_dir=destination_dir,
                target="cursor",
            )

            self.assertEqual(
                installed_path,
                destination_root / "download-task-specification.mdc",
            )
            self.assertTrue(installed_path.exists())
            self.assertTrue(destination_dir.exists())
            self.assertTrue((destination_dir / "scripts").exists())

            rendered_skill = (destination_dir / "SKILL.md").read_text()
            self.assertIn(
                "`python3 .cursor/rules/download-task-specification/scripts/"
                "download_task_specification.py`",
                rendered_skill,
            )
            self.assertNotIn(
                "~/.codex/skills/download-task-specification",
                rendered_skill,
            )

            rendered_rule = installed_path.read_text()
            self.assertIn(
                'description: "Download a task specification."',
                rendered_rule,
            )
            self.assertIn("alwaysApply: false", rendered_rule)
            self.assertIn("@download-task-specification/SKILL.md", rendered_rule)
            self.assertIn(
                "@download-task-specification/input-contract.json",
                rendered_rule,
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

    def test_install_skills_accepts_selected_cursor_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            skills_root = temp_path / "skills"
            destination_root = temp_path / "project" / ".cursor" / "rules"

            for skill_name in [
                "download-task-specification",
                "download-pr-specification",
            ]:
                skill_dir = skills_root / skill_name
                (skill_dir / "scripts").mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(
                    "\n".join(
                        [
                            "---",
                            f"name: {skill_name}",
                            f"description: {skill_name} description",
                            "---",
                            "",
                            f"Run `python3 ~/.codex/skills/{skill_name}/scripts/entry.py`.",
                        ]
                    )
                    + "\n"
                )
                (skill_dir / "input-contract.json").write_text("{}\n")
                (skill_dir / "scripts" / "entry.py").write_text("print('ok')\n")

            installed_paths = install.install_skills(
                skill_names=["download-pr-specification"],
                skills_root=skills_root,
                destination_root=destination_root,
                target="cursor",
            )

            self.assertEqual(
                installed_paths,
                [destination_root / "download-pr-specification.mdc"],
            )
            self.assertTrue(installed_paths[0].exists())
            self.assertFalse(
                (destination_root / "download-task-specification.mdc").exists()
            )


if __name__ == "__main__":
    unittest.main()
