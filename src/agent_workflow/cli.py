from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import __version__
from .errors import AgentWorkflowError
from .doctor import run_doctor
from .layout import plan_neutral_init
from .model import ProjectProfile, Scope, Severity
from .paths import HostPaths
from .plan import TransactionPlan
from .scan import scan_host
from .transactions import apply_plan, rollback_transaction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workflow")
    parser.add_argument("--version", action="store_true")
    subcommands = parser.add_subparsers(dest="command")
    scan = subcommands.add_parser("scan")
    _add_host_arguments(scan)
    scan.add_argument("--json", action="store_true")

    plan = subcommands.add_parser("plan")
    plan_subcommands = plan.add_subparsers(dest="plan_command")
    init = plan_subcommands.add_parser("init")
    init.add_argument("--scope", choices=tuple(scope.value for scope in Scope), required=True)
    init.add_argument("--profile", choices=tuple(profile.value for profile in ProjectProfile))
    init.add_argument("--target", action="append", default=[])
    init.add_argument("--output", required=True)
    _add_host_arguments(init)

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


def _host_paths(args: argparse.Namespace) -> HostPaths:
    home = Path(args.home) if args.home is not None else Path.home()
    cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
    return HostPaths.discover(home=home, cwd=cwd)


def _handle_scan(args: argparse.Namespace) -> None:
    snapshot = scan_host(_host_paths(args))
    if args.json:
        _print_json(asdict(snapshot))
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
