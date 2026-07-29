#!/usr/bin/env python3
"""Synchronize the fixed workitem rendering references."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SKILL_NAMES = ("morning", "tasks", "my-reviews", "feedback")


def synchronize(root: Path, *, write: bool) -> bool:
    root = Path(root).resolve(strict=True)
    canonical = root / "resources" / "workitems-rendering.md"
    if canonical.is_symlink() or not canonical.is_file():
        raise ValueError(f"missing safe canonical reference: {canonical}")
    content = canonical.read_bytes()
    synchronized = True
    for name in SKILL_NAMES:
        destination = (
            root
            / "skills"
            / name
            / "references"
            / "workitems-rendering.md"
        )
        _validate_destination(root, destination)
        current = (
            destination.read_bytes()
            if destination.is_file()
            else None
        )
        if current == content:
            continue
        synchronized = False
        if write:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    return True if write else synchronized


def _validate_destination(root: Path, destination: Path) -> None:
    relative = destination.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(
                f"refusing symlinked destination: {destination}"
            )
        if not current.exists():
            break
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"destination escapes repository: {destination}"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        synchronized = synchronize(root, write=args.write)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.write:
        print("workitem skill references synchronized")
        return 0
    if synchronized:
        print("workitem skill references are synchronized")
        return 0
    print(
        "workitem skill references differ; run with --write",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
