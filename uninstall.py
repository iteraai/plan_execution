#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from install import (
    ALL_TARGETS,
    DEFAULT_TARGET,
    INSTALL_TARGETS,
    InstallTarget,
    cursor_rule_path_for_destination,
    discover_skill_directories,
    get_install_target,
)

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = REPO_ROOT / "skills"


def prompt_for_uninstall_targets() -> list[InstallTarget]:
    if not sys.stdin.isatty():
        raise ValueError(
            "No uninstall target selected. Pass one of --codex, --claude, "
            "--copilot, --cursor, --all, or --target."
        )

    options = [
        (ALL_TARGETS, "All targets"),
        *[(target_name, target_name) for target_name in INSTALL_TARGETS],
    ]
    print("Select uninstall target:")
    for index, (_, label) in enumerate(options, start=1):
        print(f"  {index}. {label}")

    while True:
        selection = input("Target: ").strip().lower()
        for index, (target_name, _) in enumerate(options, start=1):
            if selection in {str(index), target_name}:
                return selected_uninstall_targets(target_name)
        print(
            "Enter a number or one of: "
            + ", ".join(target_name for target_name, _ in options)
        )


def selected_uninstall_targets(selection: str | None) -> list[InstallTarget]:
    if selection is None:
        return prompt_for_uninstall_targets()
    if selection == ALL_TARGETS:
        return [INSTALL_TARGETS[target_name] for target_name in INSTALL_TARGETS]
    return [get_install_target(selection)]


def path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def validate_removable_directory(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink():
        raise ValueError(f"Refusing to remove symbolic-link skill directory: {path}")
    if not path.is_dir():
        raise ValueError(f"Expected installed skill directory, found a file: {path}")


def validate_removable_rule(path: Path) -> None:
    if not path_exists(path):
        return
    if path.is_symlink():
        raise ValueError(f"Refusing to remove symbolic-link Cursor rule: {path}")
    if not path.is_file():
        raise ValueError(f"Expected Cursor rule file, found a directory: {path}")


def uninstall_skill(
    destination_dir: Path,
    *,
    target: InstallTarget | str = DEFAULT_TARGET,
    dry_run: bool = False,
) -> list[Path]:
    uninstall_target = (
        target if isinstance(target, InstallTarget) else get_install_target(target)
    )
    destination_dir = destination_dir.expanduser()
    rule_path = (
        cursor_rule_path_for_destination(destination_dir)
        if uninstall_target.name == "cursor"
        else None
    )

    validate_removable_directory(destination_dir)
    if rule_path is not None:
        validate_removable_rule(rule_path)

    removed_paths: list[Path] = []
    if path_exists(destination_dir):
        if not dry_run:
            shutil.rmtree(destination_dir)
        removed_paths.append(destination_dir)
    if rule_path is not None and path_exists(rule_path):
        if not dry_run:
            rule_path.unlink()
        removed_paths.append(rule_path)
    return removed_paths


def uninstall_skills(
    *,
    skill_names: list[str] | None = None,
    skills_root: Path = SKILLS_ROOT,
    destination_root: Path | None = None,
    target: InstallTarget | str = DEFAULT_TARGET,
    dry_run: bool = False,
) -> list[Path]:
    uninstall_target = (
        target if isinstance(target, InstallTarget) else get_install_target(target)
    )
    if destination_root is None:
        destination_root = uninstall_target.default_destination_root
    destination_root = destination_root.expanduser()

    discovered_skill_names = [
        skill_dir.name for skill_dir in discover_skill_directories(skills_root)
    ]
    selected_names = set(skill_names or [])
    if selected_names:
        missing_names = sorted(selected_names - set(discovered_skill_names))
        if missing_names:
            raise FileNotFoundError(
                f"Unknown skill name(s): {', '.join(missing_names)}"
            )
        skill_names_to_remove = [
            name for name in discovered_skill_names if name in selected_names
        ]
    else:
        skill_names_to_remove = discovered_skill_names

    removed_paths: list[Path] = []
    for skill_name in skill_names_to_remove:
        removed_paths.extend(
            uninstall_skill(
                destination_root / skill_name,
                target=uninstall_target,
                dry_run=dry_run,
            )
        )
    return removed_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Uninstall public plan_execution skills from the selected agent "
            "skills directory."
        )
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--target",
        choices=[*INSTALL_TARGETS, ALL_TARGETS],
        help=(
            "Agent target to uninstall from. Use 'all' to uninstall from every "
            "target. If omitted, prompts for a target."
        ),
    )
    for target_name in INSTALL_TARGETS:
        target_group.add_argument(
            f"--{target_name}",
            action="store_const",
            const=target_name,
            dest="target_flag",
            help=f"Uninstall from {target_name}.",
        )
    target_group.add_argument(
        "--all",
        action="store_const",
        const=ALL_TARGETS,
        dest="target_flag",
        help="Uninstall from every supported target.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Skill name to uninstall. Defaults to every bundled skill.",
    )
    parser.add_argument(
        "--destination-root",
        help=(
            "Installed skills root. Defaults to the target-specific skills root, "
            "such as ~/.codex/skills, ~/.claude/skills, .github/skills, or "
            ".cursor/rules."
        ),
    )
    parser.add_argument(
        "--destination",
        help=(
            "Explicit installed skill directory to remove. Requires exactly one "
            "--skill."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching installed skill files without removing them.",
    )
    args = parser.parse_args()
    target_selection = args.target_flag or args.target
    uninstall_targets = selected_uninstall_targets(target_selection)

    if len(uninstall_targets) > 1 and (args.destination or args.destination_root):
        raise ValueError(
            "--all cannot be combined with --destination or --destination-root"
        )

    removed_paths: list[Path] = []
    for uninstall_target in uninstall_targets:
        destination_root = (
            Path(args.destination_root)
            if args.destination_root
            else uninstall_target.default_destination_root
        )
        if args.destination:
            if not args.skills or len(args.skills) != 1:
                raise ValueError("--destination requires exactly one --skill value")
            if args.skills[0] not in {
                skill_dir.name for skill_dir in discover_skill_directories(SKILLS_ROOT)
            }:
                raise FileNotFoundError(f"Unknown skill name: {args.skills[0]}")
            removed_paths.extend(
                uninstall_skill(
                    Path(args.destination),
                    target=uninstall_target,
                    dry_run=args.dry_run,
                )
            )
            continue

        removed_paths.extend(
            uninstall_skills(
                skill_names=args.skills,
                destination_root=destination_root,
                target=uninstall_target,
                dry_run=args.dry_run,
            )
        )

    if not removed_paths:
        print("No matching installed skills found.")
        return 0

    action = "Would remove" if args.dry_run else "Removed"
    for removed_path in removed_paths:
        print(f"{action}: {removed_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
