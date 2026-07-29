from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.helpers import materialize_bootstrap_repo, run_bootstrap


@pytest.mark.parametrize("target", ["claude", "codex"])
@pytest.mark.parametrize("profile", ["local", "shared", "split"])
def test_release_artifact_sets_up_and_migrates_without_source_tree(
    target: str,
    profile: str,
    tmp_path: Path,
) -> None:
    clone = materialize_bootstrap_repo(tmp_path / "bootstrap-clone")
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    (project / ".git").mkdir()

    installed = run_bootstrap(
        clone,
        home=home,
        targets=(target,),
        apply=True,
    )
    assert installed.returncode == 0, installed.stderr
    manager = home / ".agents" / "workflow" / "agent-workflow.pyz"
    assert manager.is_file()
    shutil.rmtree(clone)

    project_plan = tmp_path / f"{target}-{profile}-project.json"
    _run(
        manager,
        "setup",
        "preview",
        "--scope",
        "project",
        "--project",
        str(project),
        "--profile",
        profile,
        "--target",
        target,
        "--home",
        str(home),
        "--output",
        str(project_plan),
        cwd=tmp_path,
    )
    _run(
        manager,
        "setup",
        "apply",
        "--plan",
        str(project_plan),
        "--yes",
        cwd=tmp_path,
    )
    _run(
        manager,
        "doctor",
        "--scope",
        "project",
        "--home",
        str(home),
        "--cwd",
        str(project),
        cwd=tmp_path,
    )

    legacy_root = home / f".{target}" / "memory"
    legacy_root.mkdir(parents=True, exist_ok=True)
    marker = f"installed release migration: {target}/{profile}"
    (legacy_root / f"release-{profile}.md").write_text(
        marker + "\n",
        encoding="utf-8",
    )
    inventory = tmp_path / f"{target}-{profile}-inventory.json"
    normalized = tmp_path / f"{target}-{profile}-normalized.json"
    migration_plan = tmp_path / f"{target}-{profile}-migration.json"
    _run(
        manager,
        "migrate",
        "scan",
        "--scope",
        "global",
        "--targets",
        target,
        "--home",
        str(home),
        "--cwd",
        str(tmp_path),
        "--output",
        str(inventory),
        cwd=tmp_path,
    )
    _run(
        manager,
        "migrate",
        "normalize",
        "--inventory",
        str(inventory),
        "--home",
        str(home),
        "--cwd",
        str(tmp_path),
        "--output",
        str(normalized),
        cwd=tmp_path,
    )
    _run(
        manager,
        "migrate",
        "plan",
        "--scope",
        "global",
        "--targets",
        target,
        "--inventory",
        str(inventory),
        "--normalized",
        str(normalized),
        "--home",
        str(home),
        "--cwd",
        str(tmp_path),
        "--imported-at",
        "2026-07-30T00:00:00Z",
        "--output",
        str(migration_plan),
        cwd=tmp_path,
    )
    _run(
        manager,
        "migrate",
        "apply",
        "--plan",
        str(migration_plan),
        "--yes",
        cwd=tmp_path,
    )
    _run(
        manager,
        "doctor",
        "--scope",
        "global",
        "--home",
        str(home),
        cwd=tmp_path,
    )

    imported = [
        path.read_text(encoding="utf-8")
        for path in (home / ".agents" / "memory").glob("*.md")
    ]
    assert any(marker in text for text in imported)
    assert not clone.exists()


def _run(
    manager: Path,
    *arguments: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [sys.executable, str(manager), *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"command failed: {' '.join(arguments)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result
