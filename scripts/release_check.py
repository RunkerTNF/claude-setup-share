#!/usr/bin/env python3
"""Run the complete local/CI release gate and build a reproducible zipapp."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow.package import build_manager_zipapp  # noqa: E402


@dataclass(frozen=True)
class ReleaseStep:
    name: str
    command: tuple[str, ...]


def release_steps(python: str = sys.executable) -> tuple[ReleaseStep, ...]:
    """Return release commands in their required fail-fast order."""
    pytest = (python, "-m", "pytest")
    return (
        ReleaseStep(
            "portable skill lint",
            (*pytest, "tests/test_portability.py", "tests/skills", "-q"),
        ),
        ReleaseStep(
            "documentation and forbidden content",
            (*pytest, "tests/content", "-q"),
        ),
        ReleaseStep(
            "unit and migration tests",
            (
                *pytest,
                "tests",
                "--ignore=tests/integration",
                "--ignore=tests/content",
                "--ignore=tests/skills",
                "--ignore=tests/test_portability.py",
                "--ignore=tests/test_transactions.py",
                "-q",
            ),
        ),
        ReleaseStep(
            "setup and migration goldens",
            (
                *pytest,
                "tests/integration/test_setup_golden.py",
                "tests/integration/test_migration_golden.py",
                "-q",
            ),
        ),
        ReleaseStep(
            "transaction fault injection",
            (*pytest, "tests/test_transactions.py", "-q"),
        ),
        ReleaseStep(
            "installed artifact tests",
            (
                *pytest,
                "tests/integration/test_bootstrap.py",
                "tests/integration/test_cli_workflow.py",
                "tests/integration/test_migration_cli.py",
                "tests/integration/test_installed_release.py",
                "tests/integration/test_wheel_install.py",
                "-q",
            ),
        ),
    )


def build_release_artifact(
    output_dir: Path,
    source_root: Path = ROOT,
) -> tuple[Path, Path, str]:
    """Build twice, verify byte identity, and write the release pair."""
    first = build_manager_zipapp(source_root)
    second = build_manager_zipapp(source_root)
    if first != second:
        raise RuntimeError("zipapp builds are not byte-for-byte reproducible")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "agent-workflow.pyz"
    checksum = output_dir / "agent-workflow.pyz.sha256"
    digest = hashlib.sha256(first).hexdigest()
    archive.write_bytes(first)
    checksum.write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return archive, checksum, digest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run all Agent Workflow release gates."
    )
    parser.add_argument(
        "--artifact-dir",
        help=(
            "Persistent artifact directory. By default a temporary "
            "directory outside the checkout is retained."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    for index, step in enumerate(release_steps(), start=1):
        print(f"[{index}/8] {step.name}", flush=True)
        result = _run(step.command, environment)
        if result != 0:
            return result

    print("[7/8] reproducible release artifact", flush=True)
    output_dir = (
        Path(args.artifact_dir).resolve()
        if args.artifact_dir
        else Path(
            tempfile.mkdtemp(prefix="agent-workflow-release-")
        ).resolve()
    )
    try:
        archive, checksum, digest = build_release_artifact(output_dir)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"release artifact failed: {error}", file=sys.stderr)
        return 1
    print(f"release artifact: {archive}", flush=True)
    print(f"release checksum: {checksum}", flush=True)
    print(f"release artifact sha256: {digest}", flush=True)

    print("[8/8] git diff --check", flush=True)
    result = _run(("git", "diff", "--check"), environment)
    if result != 0:
        return result
    print("release check: PASS", flush=True)
    return 0


def _run(
    command: tuple[str, ...],
    environment: dict[str, str],
) -> int:
    print(f"$ {subprocess.list2cmdline(command)}", flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
        )
    except OSError as error:
        print(f"command failed to start: {error}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        print(
            f"release step failed with exit code "
            f"{completed.returncode}",
            file=sys.stderr,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
