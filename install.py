#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = REPO_ROOT / "skills"
DEFAULT_DESTINATION_ROOT = Path.home() / ".codex" / "skills"


def install_skill(
    source_dir: Path,
    destination_dir: Path,
) -> Path:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Missing source skill directory: {source_dir}")

    destination_dir = destination_dir.expanduser()
    destination_dir.parent.mkdir(parents=True, exist_ok=True)

    staging_dir = destination_dir.parent / f".{destination_dir.name}.tmp"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    shutil.copytree(
        source_dir,
        staging_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    if destination_dir.exists():
        shutil.rmtree(destination_dir)

    os.replace(staging_dir, destination_dir)
    return destination_dir


def discover_skill_directories(skills_root: Path = SKILLS_ROOT) -> list[Path]:
    if not skills_root.is_dir():
        raise FileNotFoundError(f"Missing skills directory: {skills_root}")

    skill_directories = sorted(
        path
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    if not skill_directories:
        raise FileNotFoundError(f"No installable skills found in: {skills_root}")
    return skill_directories


def install_skills(
    *,
    skill_names: list[str] | None = None,
    skills_root: Path = SKILLS_ROOT,
    destination_root: Path = DEFAULT_DESTINATION_ROOT,
) -> list[Path]:
    destination_root = destination_root.expanduser()
    selected_names = set(skill_names or [])
    installed_paths: list[Path] = []
    discovered = discover_skill_directories(skills_root)

    for skill_dir in discovered:
        if selected_names and skill_dir.name not in selected_names:
            continue
        installed_paths.append(
            install_skill(
                source_dir=skill_dir,
                destination_dir=destination_root / skill_dir.name,
            )
        )

    if selected_names:
        installed_skill_names = {path.name for path in installed_paths}
        missing_names = sorted(selected_names - installed_skill_names)
        if missing_names:
            raise FileNotFoundError(
                f"Unknown skill name(s): {', '.join(missing_names)}"
            )

    return installed_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install public plan_execution skills into ~/.codex/skills."
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Skill name to install. Defaults to installing every bundled skill.",
    )
    parser.add_argument(
        "--destination-root",
        default=str(DEFAULT_DESTINATION_ROOT),
        help="Destination root directory. Defaults to ~/.codex/skills",
    )
    parser.add_argument(
        "--destination",
        help=(
            "Explicit destination directory for a single installed skill. "
            "Requires exactly one --skill."
        ),
    )
    args = parser.parse_args()

    if args.destination:
        if not args.skills or len(args.skills) != 1:
            raise ValueError("--destination requires exactly one --skill value")
        source_dir = SKILLS_ROOT / args.skills[0]
        installed_paths = [
            install_skill(
                source_dir=source_dir,
                destination_dir=Path(args.destination),
            )
        ]
    else:
        installed_paths = install_skills(
            skill_names=args.skills,
            destination_root=Path(args.destination_root),
        )

    for installed_path in installed_paths:
        print(installed_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"install failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
