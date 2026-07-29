#!/usr/bin/env python3
"""Bootstrap the persistent agent-workflow manager from this checkout."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile


if sys.version_info < (3, 11):
    print(
        "agent-workflow requires Python 3.11 or newer; "
        f"found {sys.version.split()[0]}",
        file=sys.stderr,
    )
    raise SystemExit(2)


CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT / "src"))

from agent_workflow.cli import main as manager_main  # noqa: E402
from agent_workflow.model import ProjectProfile, Scope  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the portable agent workflow setup."
    )
    parser.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
        default=Scope.GLOBAL.value,
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ProjectProfile),
    )
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--project-root")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--adapter-dir", action="append", default=[])
    parser.add_argument("--trust-adapter-code", action="append", default=[])
    parser.add_argument("--manage-syncprotect", action="store_true")
    parser.add_argument("--exclude-skill", action="append", default=[])
    parser.add_argument(
        "--include-claude-statusline",
        action="store_true",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = Path(args.home).resolve()
    scope = Scope(args.scope)
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root is not None
        else None
    )
    profile = (
        ProjectProfile(args.profile)
        if args.profile is not None
        else None
    )
    if scope is Scope.PROJECT:
        if project_root is None:
            project_root = Path.cwd().resolve()
        if profile is None:
            raise ValueError("project setup requires --profile")
    elif profile is not None or project_root is not None:
        raise ValueError(
            "global setup does not accept --profile or --project-root"
        )

    common = [
        "--scope",
        scope.value,
        "--home",
        str(home),
    ]
    if project_root is not None:
        common.extend(("--project", str(project_root)))
    if profile is not None:
        common.extend(("--profile", profile.value))
    for target in args.target:
        common.extend(("--target", target))
    for adapter_dir in args.adapter_dir:
        common.extend(
            ("--adapter-dir", str(Path(adapter_dir).resolve()))
        )
    for adapter_id in args.trust_adapter_code:
        common.extend(("--trust-adapter-code", adapter_id))

    detected = manager_main(["setup", "detect", *common])
    if detected != 0:
        return detected

    with tempfile.TemporaryDirectory(
        prefix="agent-workflow-bootstrap-"
    ) as temporary:
        plan_path = Path(temporary) / "setup-plan.json"
        preview_arguments = [
            "setup",
            "preview",
            *common,
            "--source-root",
            str(CHECKOUT),
            "--output",
            str(plan_path),
        ]
        if args.manage_syncprotect:
            preview_arguments.append("--manage-syncprotect")
        for skill_name in args.exclude_skill:
            preview_arguments.extend(("--exclude-skill", skill_name))
        if args.include_claude_statusline:
            preview_arguments.append("--include-claude-statusline")
        previewed = manager_main(preview_arguments)
        if previewed != 0:
            print(
                "Setup preview was not applicable; no changes applied.",
                file=sys.stderr,
            )
            return previewed
        if not args.apply:
            print(
                "No changes applied. Re-run with --apply after "
                "reviewing the plan."
            )
            return 0

        apply_arguments = [
            "setup",
            "apply",
            "--plan",
            str(plan_path),
        ]
        if args.yes:
            apply_arguments.append("--yes")
        return manager_main(apply_arguments)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
