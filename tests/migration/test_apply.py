from __future__ import annotations

from pathlib import Path

import pytest

from agent_workflow.doctor import Diagnostic
from agent_workflow.errors import ConflictError, SourceChangedError
from agent_workflow.layout import plan_neutral_init
from agent_workflow.migration.apply import apply_migration
from agent_workflow.migration.planner import (
    MigrationOptions,
    build_migration_plan,
)
from agent_workflow.migration.model import MigrationInventory
from agent_workflow.migration.normalize import (
    normalize_deterministic,
    resolve_normalized_collisions,
)
from agent_workflow.model import Scope, Severity
from agent_workflow.paths import HostPaths
from agent_workflow.transactions import apply_plan, rollback_transaction
from tests.migration.helpers import claude_command_fixture


def test_apply_rejects_changed_source_hash(tmp_path: Path) -> None:
    result, source = _planned_migration(tmp_path)
    source.write_text("changed after preview", encoding="utf-8")

    with pytest.raises(SourceChangedError):
        apply_migration(result)

    assert not (
        result.options.home
        / ".agents"
        / "skills"
        / "pick"
        / "SKILL.md"
    ).exists()


def test_apply_import_and_rollback_are_byte_reversible(
    tmp_path: Path,
) -> None:
    result, source = _planned_migration(tmp_path)
    before = source.read_bytes()

    applied = apply_migration(result)

    destination = (
        result.options.home
        / ".agents"
        / "skills"
        / "pick"
        / "SKILL.md"
    )
    assert destination.is_file()
    assert source.read_bytes() == before
    assert applied.import_journal is not None
    rollback_transaction(Path(applied.import_journal.journal_path))
    assert not destination.exists()
    assert source.read_bytes() == before


def test_native_replacement_requires_separate_confirmation(
    tmp_path: Path,
) -> None:
    result, source = _planned_migration(
        tmp_path,
        replace_native=True,
    )

    with pytest.raises(ConflictError, match="confirmation"):
        apply_migration(result)

    assert source.is_file()


def test_confirmed_native_replacement_has_its_own_rollback(
    tmp_path: Path,
) -> None:
    result, source = _planned_migration(
        tmp_path,
        replace_native=True,
    )
    before = source.read_bytes()

    applied = apply_migration(
        result,
        confirm_replacement=True,
    )

    assert not source.exists()
    assert applied.import_journal is not None
    assert applied.replacement_journal is not None
    rollback_transaction(Path(applied.replacement_journal.journal_path))
    assert source.read_bytes() == before


def test_failed_post_replacement_doctor_restores_legacy_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, source = _planned_migration(
        tmp_path,
        replace_native=True,
    )
    before = source.read_bytes()
    from agent_workflow.migration import apply as apply_module

    real_doctor = apply_module.run_doctor
    calls = 0

    def fail_second_doctor(path: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            return (
                Diagnostic(
                    Severity.BLOCKING,
                    "migration.injected",
                    "legacy",
                    "injected verification failure",
                ),
            )
        return real_doctor(path)

    monkeypatch.setattr(
        apply_module,
        "run_doctor",
        fail_second_doctor,
    )

    with pytest.raises(ConflictError, match="were restored"):
        apply_migration(result, confirm_replacement=True)

    assert source.read_bytes() == before
    assert (
        result.options.home
        / ".agents"
        / "skills"
        / "pick"
        / "SKILL.md"
    ).is_file()


def _planned_migration(
    tmp_path: Path,
    *,
    replace_native: bool = False,
):
    record, source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="Resolve one backlog item.\n",
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    apply_plan(
        plan_neutral_init(
            HostPaths(home=home, cwd=tmp_path, project_root=None),
            scope=Scope.GLOBAL,
            profile=None,
            targets=(),
        )
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude/commands",),
        artifacts=(record,),
        warnings=(),
    )
    normalized = resolve_normalized_collisions(
        (normalize_deterministic(record, source),)
    )
    result = build_migration_plan(
        inventory=inventory,
        normalized=normalized,
        decisions=None,
        mappings=(),
        options=MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=(),
            replace_native=replace_native,
            imported_at="2026-07-29T00:00:00Z",
        ),
    )
    return result, source
