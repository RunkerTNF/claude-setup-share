from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import venv
import zipfile


_WHEEL_RESOURCES = {
    "agent_workflow/_bundled/templates/core/global-memory-index.md",
    "agent_workflow/_bundled/templates/core/global-rules.md",
    "agent_workflow/_bundled/templates/core/project-memory-index.md",
    "agent_workflow/_bundled/templates/core/project-rules.md",
    "agent_workflow/adapters/codex/adapter.json",
    "agent_workflow/adapters/codex/templates/global-agents.md",
    "agent_workflow/adapters/codex/templates/project-agents-override.md",
    "agent_workflow/adapters/codex/templates/project-agents.md",
    "agent_workflow/adapters/claude/adapter.json",
    "agent_workflow/adapters/claude/assets/statusline.js",
    "agent_workflow/adapters/claude/templates/global-claude.md",
    "agent_workflow/adapters/claude/templates/project-claude-local.md",
    "agent_workflow/adapters/claude/templates/project-claude.md",
    "agent_workflow/adapters/claude/templates/settings.example.json",
}


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _venv_python(environment_root: Path) -> Path:
    return environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_installed_smoke_canonicalizes_temporary_root(tmp_path: Path) -> None:
    actual_root = tmp_path / "actual"
    (actual_root / "nested").mkdir(parents=True)
    lexical_alias = actual_root / "nested" / ".."
    smoke = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "installed_cli_smoke.py")
    )

    canonicalize = smoke["_canonical_temporary_root"]

    assert canonicalize(str(lexical_alias)) == actual_root.resolve()


def test_non_editable_wheel_contains_resources_and_runs_full_cli_smoke(tmp_path: Path) -> None:
    """Omitting package data must break a wheel after the checkout is unavailable."""
    checkout = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy2(checkout / "pyproject.toml", source / "pyproject.toml")
    shutil.copytree(checkout / "src", source / "src")

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(source),
        ],
        cwd=tmp_path,
        environment=environment,
    )
    wheels = tuple(wheelhouse.glob("agent_workflow-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        assert _WHEEL_RESOURCES <= set(archive.namelist())

    environment_root = tmp_path / "environment"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
    python = _venv_python(environment_root)
    _run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        cwd=tmp_path,
        environment=environment,
    )
    installed = _run(
        [str(python), "-c", "import agent_workflow; print(agent_workflow.__file__)"],
        cwd=tmp_path,
        environment=environment,
    ).stdout.strip()
    assert str(environment_root.resolve()) in str(Path(installed).resolve())
    assert str(checkout.resolve()) not in str(Path(installed).resolve())
    adapter = _run(
        [
            str(python),
            "-c",
            "from agent_workflow.adapters.codex import CodexAdapter; "
            "print(CodexAdapter().id)",
        ],
        cwd=tmp_path,
        environment=environment,
    )
    assert adapter.stdout.strip() == "codex"
    claude_adapter = _run(
        [
            str(python),
            "-c",
            "from agent_workflow.adapters.claude import ClaudeAdapter; "
            "print(ClaudeAdapter().id)",
        ],
        cwd=tmp_path,
        environment=environment,
    )
    assert claude_adapter.stdout.strip() == "claude"

    smoke = _run(
        [str(python), str(checkout / "tests" / "installed_cli_smoke.py")],
        cwd=tmp_path,
        environment=environment,
    )
    assert smoke.stdout.strip() == "installed wheel CLI smoke: ok"
