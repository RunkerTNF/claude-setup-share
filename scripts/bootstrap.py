#!/usr/bin/env python3
"""Bootstrap the persistent agent-workflow manager from this checkout."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


if sys.version_info < (3, 11):
    print(
        "agent-workflow requires Python 3.11 or newer; "
        f"found {sys.version.split()[0]}",
        file=sys.stderr,
    )
    raise SystemExit(2)


CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT / "src"))

from agent_workflow import __version__  # noqa: E402
from agent_workflow.adapters.base import AdapterContext  # noqa: E402
from agent_workflow.adapters.registry import (  # noqa: E402
    AdapterRegistry,
    builtin_registry,
)
from agent_workflow.doctor import run_doctor  # noqa: E402
from agent_workflow.model import ProjectProfile, Scope  # noqa: E402
from agent_workflow.setup import (  # noqa: E402
    SetupRequest,
    build_setup_plan,
    detect_setup_targets,
)
from agent_workflow.transactions import apply_plan  # noqa: E402


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

    adapter_sources = tuple(
        Path(path).resolve() for path in args.adapter_dir
    )
    external = (
        AdapterRegistry.from_directories(
            adapter_sources,
            args.trust_adapter_code,
        )
        if adapter_sources
        else AdapterRegistry.from_pairs(())
    )
    if args.trust_adapter_code and not adapter_sources:
        raise ValueError(
            "adapter code trust requires an explicit --adapter-dir"
        )
    registry = AdapterRegistry.combine((builtin_registry(), external))
    context = AdapterContext(
        home=home,
        project_root=project_root,
        neutral_root=(
            home / ".agents"
            if scope is Scope.GLOBAL
            else project_root / ".agents"
        ),
        scope=scope,
        profile=profile,
        generator_version=__version__,
    )
    detections = detect_setup_targets(context, registry)
    print("Detected adapters:")
    for detection in detections:
        state = "installed" if detection.installed else "not-installed"
        warning = f"; {detection.warning}" if detection.warning else ""
        print(f"- {detection.adapter_id}: {state}{warning}")

    targets = tuple(args.target) or tuple(
        item.adapter_id for item in detections if item.installed
    )
    request = SetupRequest(
        home=home,
        project_root=project_root,
        source_root=CHECKOUT,
        scope=scope,
        profile=profile,
        targets=targets,
        manage_syncprotect=args.manage_syncprotect,
        adapter_sources=adapter_sources,
        trusted_adapter_ids=tuple(args.trust_adapter_code),
    )
    plan = build_setup_plan(request)
    print("\nSetup preview:")
    print(plan.to_json(), end="")
    if plan.conflicts:
        print("Setup has conflicts; nothing was applied.", file=sys.stderr)
        return 3
    if not args.apply:
        print("Preview only. Re-run with --apply after reviewing the plan.")
        return 0
    if not args.yes:
        confirmation = input("Apply this exact plan? [y/N] ").strip().casefold()
        if confirmation not in {"y", "yes"}:
            print("Cancelled; nothing was applied.")
            return 0

    journal = apply_plan(plan)
    print(f"Applied transaction {journal.transaction_id}.")
    diagnostics = run_doctor(Path(plan.scope_root))
    if diagnostics:
        for item in diagnostics:
            print(
                f"{item.severity.value}: {item.code}: "
                f"{item.path}: {item.message}"
            )
        return 2
    print("doctor: clean")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
