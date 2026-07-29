from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import uninstall


class UninstallTargetSelectionTests(unittest.TestCase):
    def test_selected_uninstall_targets_returns_all_supported_targets(self) -> None:
        selected_targets = uninstall.selected_uninstall_targets("all")

        self.assertEqual(
            [target.name for target in selected_targets],
            ["codex", "claude", "copilot", "cursor"],
        )

    def test_selected_uninstall_targets_requires_explicit_noninteractive_target(
        self,
    ) -> None:
        with mock.patch("sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(ValueError, "No uninstall target selected"):
                uninstall.selected_uninstall_targets(None)


class UninstallSkillTests(unittest.TestCase):
    def test_uninstall_skill_removes_only_the_requested_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_root = Path(temp_dir) / "installed"
            destination_dir = destination_root / "download-task-specification"
            other_skill_dir = destination_root / "download-pr-specification"
            destination_dir.mkdir(parents=True)
            other_skill_dir.mkdir(parents=True)
            (destination_dir / "SKILL.md").write_text("skill\n")
            (other_skill_dir / "SKILL.md").write_text("other skill\n")

            removed_paths = uninstall.uninstall_skill(destination_dir)

            self.assertEqual(removed_paths, [destination_dir])
            self.assertFalse(destination_dir.exists())
            self.assertTrue(other_skill_dir.exists())
            self.assertTrue(destination_root.exists())

    def test_uninstall_skill_removes_cursor_rule_and_asset_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_root = Path(temp_dir) / "project" / ".cursor" / "rules"
            destination_dir = destination_root / "download-task-specification"
            rule_path = destination_root / "download-task-specification.mdc"
            destination_dir.mkdir(parents=True)
            (destination_dir / "SKILL.md").write_text("skill\n")
            rule_path.write_text("rule\n")

            removed_paths = uninstall.uninstall_skill(destination_dir, target="cursor")

            self.assertEqual(removed_paths, [destination_dir, rule_path])
            self.assertFalse(destination_dir.exists())
            self.assertFalse(rule_path.exists())
            self.assertTrue(destination_root.exists())

    def test_uninstall_skill_dry_run_leaves_the_skill_directory_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_dir = Path(temp_dir) / "download-task-specification"
            destination_dir.mkdir()
            (destination_dir / "SKILL.md").write_text("skill\n")

            affected_paths = uninstall.uninstall_skill(destination_dir, dry_run=True)

            self.assertEqual(affected_paths, [destination_dir])
            self.assertTrue(destination_dir.exists())

    def test_uninstall_skill_refuses_to_remove_an_unexpected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_path = Path(temp_dir) / "download-task-specification"
            destination_path.write_text("not a skill directory\n")

            with self.assertRaisesRegex(
                ValueError, "Expected installed skill directory"
            ):
                uninstall.uninstall_skill(destination_path)

            self.assertTrue(destination_path.exists())

    def test_uninstall_skills_removes_selected_known_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            skills_root = temp_path / "skills"
            destination_root = temp_path / "installed"
            for skill_name in [
                "download-task-specification",
                "download-pr-specification",
            ]:
                (skills_root / skill_name).mkdir(parents=True)
                (skills_root / skill_name / "SKILL.md").write_text("skill\n")
                (destination_root / skill_name).mkdir(parents=True)

            removed_paths = uninstall.uninstall_skills(
                skill_names=["download-pr-specification"],
                skills_root=skills_root,
                destination_root=destination_root,
            )

            self.assertEqual(
                removed_paths, [destination_root / "download-pr-specification"]
            )
            self.assertFalse((destination_root / "download-pr-specification").exists())
            self.assertTrue((destination_root / "download-task-specification").exists())

    def test_uninstall_skills_rejects_unknown_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            skills_root = temp_path / "skills"
            (skills_root / "download-task-specification").mkdir(parents=True)
            (skills_root / "download-task-specification" / "SKILL.md").write_text(
                "skill\n"
            )

            with self.assertRaisesRegex(FileNotFoundError, "Unknown skill name"):
                uninstall.uninstall_skills(
                    skill_names=["not-a-bundled-skill"],
                    skills_root=skills_root,
                    destination_root=temp_path / "installed",
                )

    def test_main_dry_run_reports_paths_without_removing_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_root = Path(temp_dir) / "installed"
            destination_dir = destination_root / "download-task-specification"
            destination_dir.mkdir(parents=True)

            with (
                mock.patch.object(
                    uninstall.sys,
                    "argv",
                    [
                        "uninstall.py",
                        "--codex",
                        "--dry-run",
                        "--skill",
                        "download-task-specification",
                        "--destination-root",
                        str(destination_root),
                    ],
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                self.assertEqual(uninstall.main(), 0)

            self.assertTrue(destination_dir.exists())
            self.assertIn(f"Would remove: {destination_dir}", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
