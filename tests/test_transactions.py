import json
import os
from pathlib import Path

import pytest

from agent_workflow.errors import BackupError, ConflictError, SourceChangedError, TransactionBusyError
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation
from agent_workflow.transactions.engine import apply_plan, rollback_transaction


def make_plan(root: Path, expected: str | None, *, content: bytes = b"# Rules\n", conflicts: tuple[str, ...] = ()) -> TransactionPlan:
    operation = WriteOperation.from_bytes(
        root_id="neutral",
        path="RULES.md",
        content=content,
        expected_sha256=expected,
        ownership=Ownership.CANONICAL,
    )
    return TransactionPlan.new(
        scope_root=str(root),
        target_roots={"neutral": str(root), "scope": str(root.parent)},
        allowed_roots=(str(root.parent),),
        operations=(operation,),
        conflicts=conflicts,
    )


def make_delete_plan(root: Path, expected: str) -> TransactionPlan:
    operation = DeleteOperation(
        root_id="neutral",
        path="legacy/CLAUDE.md",
        expected_sha256=expected,
        ownership=Ownership.GENERATED,
    )
    return TransactionPlan.new(
        scope_root=str(root),
        target_roots={"neutral": str(root), "scope": str(root.parent)},
        allowed_roots=(str(root.parent),),
        operations=(operation,),
    )


def test_apply_then_rollback_restores_bytes(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"old\n")

    journal = apply_plan(make_plan(root, sha256_file(rules)))

    assert rules.read_bytes() == b"# Rules\n"
    rollback_transaction(Path(journal.journal_path))
    assert rules.read_bytes() == b"old\n"


def test_hash_mismatch_blocks_before_write(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"changed\n")

    with pytest.raises(SourceChangedError, match="hash mismatch"):
        apply_plan(make_plan(root, "0" * 64))

    assert rules.read_bytes() == b"changed\n"


def test_delete_then_rollback_restores_bytes(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    legacy = root / "legacy" / "CLAUDE.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy\n")

    journal = apply_plan(make_delete_plan(root, sha256_file(legacy)))
    assert not legacy.exists()

    rollback_transaction(Path(journal.journal_path))

    assert legacy.read_bytes() == b"legacy\n"


def test_conflicted_plan_creates_no_transaction_files(tmp_path: Path) -> None:
    root = tmp_path / ".agents"

    with pytest.raises(ConflictError):
        apply_plan(make_plan(root, None, conflicts=("generated file drift",)))

    assert not root.exists()


def test_existing_lock_blocks_apply_and_is_released_after_success(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    lock_path = root / ".workflow.lock"
    lock_path.write_text("other transaction", encoding="utf-8")

    with pytest.raises(TransactionBusyError):
        apply_plan(make_plan(root, None))

    lock_path.unlink()
    apply_plan(make_plan(root, None))

    assert not lock_path.exists()


def test_backup_verification_failure_prevents_target_modification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"old\n")

    from agent_workflow.transactions import backup

    def fail_verification(*_args: object, **_kwargs: object) -> None:
        raise BackupError("backup verification failed")

    monkeypatch.setattr(backup, "verify_backup", fail_verification)

    with pytest.raises(BackupError, match="verification"):
        apply_plan(make_plan(root, sha256_file(rules)))

    assert rules.read_bytes() == b"old\n"


def test_mid_commit_failure_restores_the_complete_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    first = root / "first.txt"
    second = root / "second.txt"
    first.write_bytes(b"first before")
    second.write_bytes(b"second before")
    operations = (
        WriteOperation.from_bytes("neutral", "first.txt", b"first after", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second.txt", b"second after", sha256_file(second), Ownership.CANONICAL),
    )
    plan = TransactionPlan.new(
        scope_root=str(root),
        target_roots={"neutral": str(root), "scope": str(root.parent)},
        allowed_roots=(str(root.parent),),
        operations=operations,
    )
    from agent_workflow.transactions import engine

    replace = os.replace

    def fail_second_target(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == second:
            raise OSError("injected replace failure")
        replace(source, destination)

    monkeypatch.setattr(engine.os, "replace", fail_second_target)

    with pytest.raises(OSError, match="injected replace failure"):
        apply_plan(plan)

    assert first.read_bytes() == b"first before"
    assert second.read_bytes() == b"second before"


def test_rollback_refuses_drift_before_restoring_any_target(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"old\n")
    journal = apply_plan(make_plan(root, sha256_file(rules)))
    rules.write_bytes(b"manual edit\n")

    with pytest.raises(SourceChangedError, match="drift"):
        rollback_transaction(Path(journal.journal_path))

    assert rules.read_bytes() == b"manual edit\n"


def test_rollback_rejects_tampered_journal_backup_path(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"old\n")
    journal = apply_plan(make_plan(root, sha256_file(rules)))
    journal_path = Path(journal.journal_path)
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    payload["backup_root"] = str(tmp_path / "outside")
    journal_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="backup_root"):
        rollback_transaction(journal_path)

    assert rules.read_bytes() == b"# Rules\n"


def test_rollback_removes_target_that_did_not_exist_before_apply(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    journal = apply_plan(make_plan(root, None))

    assert rules.read_bytes() == b"# Rules\n"
    rollback_transaction(Path(journal.journal_path))

    assert not rules.exists()
