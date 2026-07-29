from __future__ import annotations

import json
from pathlib import Path

from agent_workflow.cli import main


def test_migration_cli_dry_run_then_apply(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / ".claude" / "commands" / "pick.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "Resolve one backlog item.\n",
        encoding="utf-8",
    )
    setup_plan = tmp_path / "setup.json"
    inventory = tmp_path / "inventory.json"
    normalized = tmp_path / "normalized.json"
    migration_plan = tmp_path / "migration-plan.json"

    assert main(
        [
            "plan",
            "init",
            "--scope",
            "global",
            "--home",
            str(home),
            "--cwd",
            str(tmp_path),
            "--output",
            str(setup_plan),
        ]
    ) == 0
    assert main(["apply", str(setup_plan)]) == 0
    assert main(
        [
            "migrate",
            "scan",
            "--scope",
            "global",
            "--targets",
            "claude",
            "--home",
            str(home),
            "--cwd",
            str(tmp_path),
            "--output",
            str(inventory),
        ]
    ) == 0
    assert main(
        [
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
        ]
    ) == 0
    assert main(
        [
            "migrate",
            "plan",
            "--scope",
            "global",
            "--targets",
            "claude",
            "--inventory",
            str(inventory),
            "--normalized",
            str(normalized),
            "--home",
            str(home),
            "--cwd",
            str(tmp_path),
            "--imported-at",
            "2026-07-29T00:00:00Z",
            "--output",
            str(migration_plan),
        ]
    ) == 0

    preview = json.loads(migration_plan.read_text(encoding="utf-8"))
    assert preview["import_plan"]["operations"]
    assert legacy.is_file()
    assert not (
        home / ".agents" / "skills" / "pick" / "SKILL.md"
    ).exists()

    assert main(
        [
            "migrate",
            "apply",
            "--plan",
            str(migration_plan),
            "--yes",
        ]
    ) == 0
    assert (
        home / ".agents" / "skills" / "pick" / "SKILL.md"
    ).is_file()
    assert legacy.is_file()


def test_migration_report_is_derived_from_plan(
    tmp_path: Path,
    capsys,
) -> None:
    plan_file = tmp_path / "missing.json"

    assert main(
        [
            "migrate",
            "report",
            "--plan",
            str(plan_file),
        ]
    ) == 2
    assert "error:" in capsys.readouterr().err
