from __future__ import annotations

from pathlib import Path
import shutil

from tests.helpers import (
    materialize_bootstrap_repo,
    run_bootstrap,
    run_installed_manager,
)


def test_installed_manager_survives_source_repo_removal(
    tmp_path: Path,
) -> None:
    clone = materialize_bootstrap_repo(tmp_path / "clone")
    home = tmp_path / "home"
    home.mkdir()

    installed = run_bootstrap(
        clone,
        home=home,
        targets=("claude", "codex"),
        apply=True,
    )
    assert installed.returncode == 0, installed.stderr

    shutil.rmtree(clone)

    result = run_installed_manager(
        home,
        "doctor",
        "--scope",
        "global",
    )
    assert result.returncode == 0, result.stderr
    assert (home / ".agents" / "workflow" / "agent-workflow.pyz").is_file()
    for relative_path in (
        "skills/agent-workflow-setup/SKILL.md",
        "skills/agent-workflow-setup/references/setup-flow.md",
        "skills/agent-workflow-migrate/SKILL.md",
        "skills/agent-workflow-migrate/references/recovery.md",
    ):
        assert (home / ".agents" / relative_path).is_file()


def test_bootstrap_defaults_to_preview(tmp_path: Path) -> None:
    clone = materialize_bootstrap_repo(tmp_path / "clone")
    home = tmp_path / "home"
    home.mkdir()

    result = run_bootstrap(clone, home=home)

    assert result.returncode == 0, result.stderr
    assert "No changes applied" in result.stdout
    assert not (home / ".agents").exists()
