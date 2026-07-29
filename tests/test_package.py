from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from agent_workflow.package import build_manager_zipapp


def test_built_zipapp_runs_without_source_tree(tmp_path: Path) -> None:
    first = build_manager_zipapp(Path.cwd())
    second = build_manager_zipapp(Path.cwd())
    archive = tmp_path / "agent-workflow.pyz"
    archive.write_bytes(first)

    completed = subprocess.run(
        [sys.executable, str(archive), "--version"],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert first == second
    assert completed.returncode == 0
    assert completed.stdout.strip() == "agent-workflow 0.1.0"
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        assert names == sorted(names)
        assert (
            "agent_workflow/_bundled/skills/"
            "agent-workflow-setup/SKILL.md"
        ) in names
        assert {entry.date_time for entry in package.infolist()} == {
            (1980, 1, 1, 0, 0, 0)
        }
        assert b"\r\n" not in package.read("agent_workflow/setup.py")


def test_zipapp_rejects_missing_or_symlinked_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source root"):
        build_manager_zipapp(tmp_path / "missing")

    source = tmp_path / "source-link"
    try:
        source.symlink_to(Path.cwd(), target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="source root"):
        build_manager_zipapp(source)


def test_bootstrap_defaults_to_read_only_preview(tmp_path: Path) -> None:
    checkout = Path.cwd()
    home = tmp_path / "home"
    home.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(checkout / "scripts" / "bootstrap.py"),
            "--home",
            str(home),
            "--target",
            "codex",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Detected adapters:" in completed.stdout
    assert "Setup preview:" in completed.stdout
    assert "Preview only." in completed.stdout
    assert not (home / ".agents").exists()


def test_bootstrap_apply_installs_and_runs_doctor(tmp_path: Path) -> None:
    checkout = Path.cwd()
    home = tmp_path / "home"
    home.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(checkout / "scripts" / "bootstrap.py"),
            "--home",
            str(home),
            "--target",
            "codex",
            "--apply",
            "--yes",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "doctor: clean" in completed.stdout
    assert (
        home
        / ".agents"
        / "workflow"
        / "agent-workflow.pyz"
    ).is_file()
