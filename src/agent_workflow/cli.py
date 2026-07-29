from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import __version__
from .adapters.base import AdapterContext
from .adapters.registry import AdapterRegistry, builtin_registry
from .errors import AgentWorkflowError
from .doctor import run_doctor
from .layout import plan_neutral_init
from .model import ProjectProfile, Scope, Severity
from .paths import HostPaths
from .plan import TransactionPlan
from .scan import scan_host
from .setup import SetupRequest, build_setup_plan, detect_setup_targets
from .transactions import apply_plan, rollback_transaction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workflow")
    parser.add_argument("--version", action="store_true")
    subcommands = parser.add_subparsers(dest="command")
    scan = subcommands.add_parser("scan")
    _add_host_arguments(scan)
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--agents", action="store_true")
    _add_adapter_arguments(scan)

    plan = subcommands.add_parser("plan")
    plan_subcommands = plan.add_subparsers(dest="plan_command", required=True)
    init = plan_subcommands.add_parser("init")
    init.add_argument("--scope", choices=tuple(scope.value for scope in Scope), required=True)
    init.add_argument("--profile", choices=tuple(profile.value for profile in ProjectProfile))
    init.add_argument("--target", action="append", default=[])
    init.add_argument("--output", required=True)
    _add_host_arguments(init)

    setup = plan_subcommands.add_parser("setup")
    setup.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in Scope),
        required=True,
    )
    setup.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in ProjectProfile),
    )
    setup.add_argument("--target", action="append", default=[])
    setup.add_argument("--source-root")
    setup.add_argument("--manage-syncprotect", action="store_true")
    setup.add_argument("--output", required=True)
    _add_host_arguments(setup)
    _add_adapter_arguments(setup)

    apply = subcommands.add_parser("apply")
    apply.add_argument("plan")

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--scope-root", required=True)
    doctor.add_argument("--json", action="store_true")

    rollback = subcommands.add_parser("rollback")
    rollback.add_argument("journal")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    try:
        if args.version:
            print(f"agent-workflow {__version__}")
        elif args.command is None:
            parser.print_help()
        elif args.command == "scan":
            _handle_scan(args)
        elif args.command == "plan" and args.plan_command == "init":
            return _handle_plan_init(args)
        elif args.command == "plan" and args.plan_command == "setup":
            return _handle_plan_setup(args)
        elif args.command == "apply":
            _handle_apply(args)
        elif args.command == "doctor":
            return _handle_doctor(args)
        elif args.command == "rollback":
            _handle_rollback(args)
        else:
            parser.print_help()
        return 0
    except AgentWorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _add_host_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home")
    parser.add_argument("--cwd")


def _add_adapter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--adapter-dir", action="append", default=[])
    parser.add_argument(
        "--trust-adapter-code",
        action="append",
        default=[],
    )


def _host_paths(args: argparse.Namespace) -> HostPaths:
    home = Path(args.home) if args.home is not None else Path.home()
    cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
    return HostPaths.discover(home=home, cwd=cwd)


def _handle_scan(args: argparse.Namespace) -> None:
    paths = _host_paths(args)
    snapshot = scan_host(paths)
    detections = ()
    if args.agents:
        registry = _registry_for_cli(
            paths.home,
            tuple(Path(path) for path in args.adapter_dir),
            tuple(args.trust_adapter_code),
        )
        context = AdapterContext(
            home=paths.home,
            project_root=None,
            neutral_root=paths.home / ".agents",
            scope=Scope.GLOBAL,
            profile=None,
            generator_version=__version__,
        )
        detections = detect_setup_targets(context, registry)
    if args.json:
        payload = asdict(snapshot)
        if args.agents:
            payload["agents"] = [
                asdict(detection) for detection in detections
            ]
        _print_json(payload)
        return
    print(
        " ".join(
            (
                f"os={snapshot.os_name}",
                f"python={snapshot.python_version}",
                f"home={snapshot.home}",
                f"project_root={snapshot.project_root or '-'}",
            )
        )
    )
    for detection in detections:
        print(
            " ".join(
                (
                    f"agent={detection.adapter_id}",
                    f"installed={str(detection.installed).lower()}",
                    f"executable={detection.executable or '-'}",
                    f"version={detection.version or '-'}",
                    f"warning={detection.warning or '-'}",
                )
            )
        )


def _handle_plan_init(args: argparse.Namespace) -> int:
    scope = Scope(args.scope)
    profile = ProjectProfile(args.profile) if args.profile is not None else None
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError("global scope does not accept a project profile")
    if scope is Scope.PROJECT and profile is None:
        raise ValueError("project scope requires --profile")
    plan = plan_neutral_init(
        _host_paths(args),
        scope=scope,
        profile=profile,
        targets=tuple(args.target),
    )
    output = Path(args.output)
    output.write_text(plan.to_json(), encoding="utf-8")
    print(
        f"wrote plan: {output} "
        f"({len(plan.operations)} operations, {len(plan.conflicts)} conflicts)"
    )
    return 3 if plan.conflicts else 0


def _handle_plan_setup(args: argparse.Namespace) -> int:
    scope = Scope(args.scope)
    profile = (
        ProjectProfile(args.profile)
        if args.profile is not None
        else None
    )
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError("global scope does not accept a project profile")
    if scope is Scope.PROJECT and profile is None:
        raise ValueError("project scope requires --profile")
    paths = _host_paths(args)
    request = SetupRequest(
        home=paths.home,
        project_root=(
            paths.project_root if scope is Scope.PROJECT else None
        ),
        source_root=(
            Path(args.source_root)
            if args.source_root is not None
            else Path.cwd()
        ),
        scope=scope,
        profile=profile,
        targets=tuple(args.target),
        manage_syncprotect=args.manage_syncprotect,
        adapter_sources=tuple(
            Path(path) for path in args.adapter_dir
        ),
        trusted_adapter_ids=tuple(args.trust_adapter_code),
    )
    plan = build_setup_plan(request)
    output = Path(args.output)
    output.write_text(plan.to_json(), encoding="utf-8")
    print(
        f"wrote setup plan: {output} "
        f"({len(plan.operations)} operations, "
        f"{len(plan.conflicts)} conflicts, "
        f"{len(plan.warnings)} warnings)"
    )
    return 3 if plan.conflicts else 0


def _handle_apply(args: argparse.Namespace) -> None:
    plan = TransactionPlan.from_json(Path(args.plan).read_text(encoding="utf-8"))
    journal = apply_plan(plan)
    print(f"applied transaction {journal.transaction_id}: {journal.status}; journal: {journal.journal_path}")


def _handle_doctor(args: argparse.Namespace) -> int:
    diagnostics = run_doctor(Path(args.scope_root))
    if args.json:
        _print_json(
            {
                "blocking": any(item.severity is Severity.BLOCKING for item in diagnostics),
                "diagnostics": [
                    {
                        "severity": item.severity.value,
                        "code": item.code,
                        "path": item.path,
                        "message": item.message,
                    }
                    for item in diagnostics
                ],
            }
        )
    elif diagnostics:
        for item in diagnostics:
            print(f"{item.severity.value}: {item.code}: {item.path}: {item.message}")
    else:
        print("doctor: clean")
    return 2 if any(item.severity is Severity.BLOCKING for item in diagnostics) else 0


def _handle_rollback(args: argparse.Namespace) -> None:
    journal = rollback_transaction(Path(args.journal))
    print(f"rolled back transaction {journal.transaction_id}: {journal.status}; journal: {journal.journal_path}")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, sort_keys=True))


def _registry_for_cli(
    home: Path,
    adapter_sources: tuple[Path, ...],
    trusted_adapter_ids: tuple[str, ...],
) -> AdapterRegistry:
    if trusted_adapter_ids and not adapter_sources:
        raise ValueError(
            "adapter code trust requires an explicit --adapter-dir"
        )
    roots = adapter_sources
    if not roots:
        managed = home / ".agents" / "workflow" / "adapters"
        if managed.is_dir() and not managed.is_symlink():
            roots = (managed,)
    external = (
        AdapterRegistry.from_directories(
            roots,
            trusted_adapter_ids if adapter_sources else (),
        )
        if roots
        else AdapterRegistry.from_pairs(())
    )
    return AdapterRegistry.combine((builtin_registry(), external))
