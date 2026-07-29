from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from . import __version__
from .errors import AgentWorkflowError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workflow")
    parser.add_argument("--version", action="store_true")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("scan")
    plan = subcommands.add_parser("plan")
    plan.add_subparsers(dest="plan_command").add_parser("init")
    subcommands.add_parser("apply")
    subcommands.add_parser("doctor")
    subcommands.add_parser("rollback")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.version:
            print(f"agent-workflow {__version__}")
        elif args.command is None:
            parser.print_help()
        return 0
    except AgentWorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code
