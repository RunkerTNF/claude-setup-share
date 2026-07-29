"""Exercise the installed console entry point without importing the source checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory


def _console_command() -> list[str]:
    executable = "agent-workflow.exe" if os.name == "nt" else "agent-workflow"
    command = Path(sysconfig.get_path("scripts")) / executable
    if not command.is_file():
        raise RuntimeError(f"installed console script is missing: {command}")
    return [str(command)]


def _run(command: list[str], *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [*command, *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def main() -> int:
    command = _console_command()
    with TemporaryDirectory(prefix="agent-workflow-wheel-smoke-") as temporary:
        root = Path(temporary)
        home = root / "home"
        cwd = root / "cwd"
        plan = root / "plan.json"
        home.mkdir()
        cwd.mkdir()

        _run(
            command,
            "plan",
            "init",
            "--scope",
            "global",
            "--home",
            str(home),
            "--cwd",
            str(cwd),
            "--output",
            str(plan),
        )
        scope_root = home / ".agents"
        if scope_root.exists():
            raise RuntimeError("planning modified the target home")

        _run(command, "apply", str(plan))
        doctor = _run(command, "doctor", "--scope-root", str(scope_root), "--json")
        payload = json.loads(doctor.stdout)
        if payload != {"blocking": False, "diagnostics": []}:
            raise RuntimeError(f"doctor did not report a clean installed scope: {payload}")

        journals = tuple((scope_root / "workflow" / "journals").glob("*.json"))
        if len(journals) != 1:
            raise RuntimeError(f"expected exactly one journal, found {len(journals)}")
        _run(command, "rollback", str(journals[0]))
        if (scope_root / "RULES.md").exists():
            raise RuntimeError("rollback left the installed rules file in place")

    print("installed wheel CLI smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
