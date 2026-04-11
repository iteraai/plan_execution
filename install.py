#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent
SOURCE_SKILL_DIR = REPO_ROOT / "skills" / "execute-approved-plan"
DEFAULT_DESTINATION_DIR = Path.home() / ".codex" / "skills" / "execute-approved-plan"


def install_skill(
    source_dir: Path = SOURCE_SKILL_DIR, destination_dir: Path = DEFAULT_DESTINATION_DIR
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the public execute-approved-plan skill into ~/.codex/skills."
    )
    parser.add_argument(
        "--destination",
        default=str(DEFAULT_DESTINATION_DIR),
        help="Destination skill directory. Defaults to ~/.codex/skills/execute-approved-plan",
    )
    args = parser.parse_args()

    installed_path = install_skill(destination_dir=Path(args.destination))
    print(installed_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"install failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
