#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = REPO_ROOT / "skills"


@dataclass(frozen=True)
class InstallTarget:
    name: str
    default_destination_root: Path


INSTALL_TARGETS = {
    "codex": InstallTarget(
        name="codex",
        default_destination_root=Path.home() / ".codex" / "skills",
    ),
    "claude": InstallTarget(
        name="claude",
        default_destination_root=Path.home() / ".claude" / "skills",
    ),
}
DEFAULT_TARGET = "codex"
CLAUDE_SKILL_FRONTMATTER = {
    "execute-approved-plan": {
        "disable-model-invocation": True,
        "argument-hint": "[canonical-task-id]",
    },
    "download-task-specification": {
        "disable-model-invocation": True,
        "argument-hint": "[canonical-task-id]",
    },
    "download-pr-specification": {
        "disable-model-invocation": True,
        "argument-hint": "[canonical-task-id] [pull-request-position-or-planned-pull-request-id]",
    },
}


def get_install_target(name: str) -> InstallTarget:
    try:
        return INSTALL_TARGETS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported install target: {name}") from exc


def path_for_display(path: Path) -> str:
    expanded = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative = expanded.relative_to(home)
    except ValueError:
        return str(expanded)
    if str(relative) == ".":
        return "~"
    return f"~/{relative}"


def replace_install_paths(
    content: str,
    *,
    skill_name: str,
    installed_skill_dir: Path,
) -> str:
    default_codex_skill_path = f"~/.codex/skills/{skill_name}"
    return content.replace(
        default_codex_skill_path,
        path_for_display(installed_skill_dir),
    )


def upsert_frontmatter_field(content: str, *, field: str, value: object) -> str:
    if not content.startswith("---\n"):
        return content

    closing_marker = content.find("\n---\n", 4)
    if closing_marker == -1:
        return content

    frontmatter_body = content[4:closing_marker]
    body = content[closing_marker + len("\n---\n") :]
    lines = frontmatter_body.splitlines()
    replacement = f"{field}: {format_yaml_scalar(value)}"

    for index, line in enumerate(lines):
        if line.startswith(f"{field}:"):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)

    updated_frontmatter = "\n".join(lines)
    return f"---\n{updated_frontmatter}\n---\n{body}"


def format_yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def render_skill_markdown_for_target(
    content: str,
    *,
    skill_name: str,
    installed_skill_dir: Path,
    target: InstallTarget,
) -> str:
    rendered = replace_install_paths(
        content,
        skill_name=skill_name,
        installed_skill_dir=installed_skill_dir,
    )
    if target.name != "claude":
        return rendered

    for field, value in CLAUDE_SKILL_FRONTMATTER.get(skill_name, {}).items():
        rendered = upsert_frontmatter_field(rendered, field=field, value=value)
    return rendered


def render_readme_for_target(
    content: str,
    *,
    skill_name: str,
    installed_skill_dir: Path,
    target: InstallTarget,
) -> str:
    rendered = replace_install_paths(
        content,
        skill_name=skill_name,
        installed_skill_dir=installed_skill_dir,
    )
    if target.name == "claude":
        rendered = rendered.replace(
            " public Codex skill ", " public Claude Code skill "
        )
        rendered = rendered.replace(
            " public Codex skills ", " public Claude Code skills "
        )
    return rendered


def render_installed_skill(
    skill_dir: Path,
    *,
    skill_name: str,
    installed_skill_dir: Path,
    target: InstallTarget,
) -> None:
    skill_markdown_path = skill_dir / "SKILL.md"
    if skill_markdown_path.exists():
        skill_markdown_path.write_text(
            render_skill_markdown_for_target(
                skill_markdown_path.read_text(),
                skill_name=skill_name,
                installed_skill_dir=installed_skill_dir,
                target=target,
            )
        )

    readme_path = skill_dir / "README.md"
    if readme_path.exists():
        readme_path.write_text(
            render_readme_for_target(
                readme_path.read_text(),
                skill_name=skill_name,
                installed_skill_dir=installed_skill_dir,
                target=target,
            )
        )


def install_skill(
    source_dir: Path,
    destination_dir: Path,
    *,
    target: InstallTarget | str = DEFAULT_TARGET,
) -> Path:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Missing source skill directory: {source_dir}")

    install_target = (
        target if isinstance(target, InstallTarget) else get_install_target(target)
    )
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
    render_installed_skill(
        staging_dir,
        skill_name=source_dir.name,
        installed_skill_dir=destination_dir,
        target=install_target,
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
    destination_root: Path | None = None,
    target: InstallTarget | str = DEFAULT_TARGET,
) -> list[Path]:
    install_target = (
        target if isinstance(target, InstallTarget) else get_install_target(target)
    )
    if destination_root is None:
        destination_root = install_target.default_destination_root
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
                target=install_target,
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
        description=(
            "Install public plan_execution skills into the selected agent "
            "skills directory."
        )
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        choices=sorted(INSTALL_TARGETS),
        help="Agent target to install for. Defaults to codex.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Skill name to install. Defaults to installing every bundled skill.",
    )
    parser.add_argument(
        "--destination-root",
        help=(
            "Destination root directory. Defaults to the target-specific skills "
            "root, such as ~/.codex/skills or ~/.claude/skills."
        ),
    )
    parser.add_argument(
        "--destination",
        help=(
            "Explicit destination directory for a single installed skill. "
            "Requires exactly one --skill."
        ),
    )
    args = parser.parse_args()
    install_target = get_install_target(args.target)
    destination_root = (
        Path(args.destination_root)
        if args.destination_root
        else install_target.default_destination_root
    )

    if args.destination:
        if not args.skills or len(args.skills) != 1:
            raise ValueError("--destination requires exactly one --skill value")
        source_dir = SKILLS_ROOT / args.skills[0]
        installed_paths = [
            install_skill(
                source_dir=source_dir,
                destination_dir=Path(args.destination),
                target=install_target,
            )
        ]
    else:
        installed_paths = install_skills(
            skill_names=args.skills,
            destination_root=destination_root,
            target=install_target,
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
