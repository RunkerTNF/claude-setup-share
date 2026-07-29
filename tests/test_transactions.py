import json
import os
from pathlib import Path
import shutil

import pytest

from agent_workflow.errors import BackupError, ConflictError, SourceChangedError, TransactionBusyError, UnsafePathError
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation
from agent_workflow.transactions.engine import apply_plan, rollback_transaction
from agent_workflow.transactions.lock import ScopeLock


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


@pytest.mark.parametrize("path", ("workflow", "workflow/backups/data", "workflow/journals/entry.json"))
def test_transaction_storage_and_its_ancestors_are_reserved(tmp_path: Path, path: str) -> None:
    root = tmp_path / ".agents"
    operation = WriteOperation.from_bytes("neutral", path, b"x", None, Ownership.CANONICAL)
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(operation,))

    with pytest.raises(UnsafePathError, match="transaction storage"):
        apply_plan(plan)


@pytest.mark.parametrize("path", ("workflow/manager/state.json", "workflow/adapters/codex.json", "workflow/templates/rules.md"))
def test_manager_workflow_siblings_remain_writable(tmp_path: Path, path: str) -> None:
    root = tmp_path / ".agents"
    operation = WriteOperation.from_bytes("neutral", path, b"x", None, Ownership.CANONICAL)
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(operation,))

    apply_plan(plan)

    assert (root / path).read_bytes() == b"x"


def test_full_preflight_blocks_late_drift_without_modifying_earlier_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    first, second = root / "first.txt", root / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(
        WriteOperation.from_bytes("neutral", "first.txt", b"new first", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second.txt", b"new second", sha256_file(second), Ownership.CANONICAL),
    ))
    from agent_workflow.transactions import engine
    original_stage = engine._stage_writes

    def stage_then_drift(*args: object, **kwargs: object) -> object:
        result = original_stage(*args, **kwargs)
        second.write_bytes(b"drift")
        return result

    monkeypatch.setattr(engine, "_stage_writes", stage_then_drift)
    with pytest.raises(SourceChangedError):
        apply_plan(plan)
    assert first.read_bytes() == b"first"


def test_apply_rejects_parent_symlink_swapped_after_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, outside = tmp_path / ".agents", tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    operation = WriteOperation.from_bytes("neutral", "new/file.txt", b"safe", None, Ownership.CANONICAL)
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(operation,))
    from agent_workflow.transactions import engine
    original_stage = engine._stage_writes
    def stage_then_swap(*args: object, **kwargs: object) -> object:
        result = original_stage(*args, **kwargs)
        try:
            (root / "new").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation unavailable")
        return result
    monkeypatch.setattr(engine, "_stage_writes", stage_then_swap)
    with pytest.raises(UnsafePathError):
        apply_plan(plan)
    assert not (outside / "file.txt").exists()


def test_replaced_lock_is_never_unlinked_on_exit(tmp_path: Path) -> None:
    path = tmp_path / ".workflow.lock"
    lock = ScopeLock(path)
    lock.__enter__()
    path.unlink()
    path.write_text("replacement", encoding="utf-8")
    lock.__exit__(None, None, None)
    assert path.read_text(encoding="utf-8") == "replacement"


@pytest.mark.parametrize("storage_name", ("backups", "journals"))
def test_rollback_rejects_symlinked_retained_storage_before_use(tmp_path: Path, storage_name: str) -> None:
    root, outside = tmp_path / ".agents", tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    rules = root / "RULES.md"; rules.write_bytes(b"old")
    journal = apply_plan(make_plan(root, sha256_file(rules)))
    storage = root / "workflow" / storage_name
    shutil.rmtree(storage)
    try:
        storage.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(UnsafePathError, match="symlink"):
        rollback_transaction(Path(journal.journal_path))
    assert not list(outside.iterdir())


def test_recovery_journal_failure_never_masks_commit_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    first, second = root / "first", root / "second"
    first.write_bytes(b"first"); second.write_bytes(b"second")
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(
        WriteOperation.from_bytes("neutral", "first", b"new first", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second", b"new second", sha256_file(second), Ownership.CANONICAL),
    ))
    from agent_workflow.transactions import engine
    real_replace, real_write = os.replace, engine._write_journal
    def fail_commit(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == second: raise OSError("original commit failure")
        real_replace(source, destination)
    def fail_recovery_status(journal: object) -> None:
        if getattr(journal, "status") == "rolling_back": raise OSError("journal recovery failure")
        real_write(journal)
    monkeypatch.setattr(engine.os, "replace", fail_commit)
    monkeypatch.setattr(engine, "_write_journal", fail_recovery_status)
    with pytest.raises(OSError, match="original commit failure"):
        apply_plan(plan)


def test_manual_rollback_resumes_committing_journal(tmp_path: Path) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    rules = root / "RULES.md"; rules.write_bytes(b"old")
    journal = apply_plan(make_plan(root, sha256_file(rules)))
    path = Path(journal.journal_path)
    payload = json.loads(path.read_text(encoding="utf-8")); payload["status"] = "committing"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rollback_transaction(path)
    assert rules.read_bytes() == b"old"


def test_manual_restore_rejects_parent_symlink_swap_and_later_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, outside = tmp_path / ".agents", tmp_path / "outside"
    nested = root / "nested"; nested.mkdir(parents=True); outside.mkdir()
    target = nested / "file"; target.write_bytes(b"before")
    operation = WriteOperation.from_bytes("neutral", "nested/file", b"after", sha256_file(target), Ownership.CANONICAL)
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(operation,))
    journal = apply_plan(plan)
    from agent_workflow.transactions import engine
    real_stage = engine._create_stage_root
    def stage_then_attack(parent: Path, transaction_id: str, label: str) -> Path:
        result = real_stage(parent, transaction_id, label)
        if label.startswith("restore-"):
            shutil.rmtree(nested)
            try: nested.symlink_to(outside, target_is_directory=True)
            except OSError: pytest.skip("symlink creation unavailable")
        return result
    monkeypatch.setattr(engine, "_create_stage_root", stage_then_attack)
    with pytest.raises(BackupError):
        rollback_transaction(Path(journal.journal_path))
    assert not (outside / "file").exists()
    nested.unlink(); nested.mkdir(); target.write_bytes(b"after")
    monkeypatch.setattr(engine, "_create_stage_root", real_stage)
    rollback_transaction(Path(journal.journal_path))
    assert target.read_bytes() == b"before"


def test_lock_cleanup_failure_keeps_body_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = ScopeLock(tmp_path / ".workflow.lock")
    lock.__enter__()
    monkeypatch.setattr(type(lock.path), "lstat", lambda _self: (_ for _ in ()).throw(OSError("cleanup failed")))
    body_error = RuntimeError("body failure")
    lock.__exit__(RuntimeError, body_error, None)
    assert any("cleanup failed" in note for note in body_error.__notes__)


def test_backup_tamper_after_staging_blocks_before_committing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"; target.write_bytes(b"old")
    from agent_workflow.transactions import engine
    real_stage = engine._stage_writes
    def stage_then_tamper(stage_root: Path, operations: object) -> object:
        result = real_stage(stage_root, operations)
        transaction_id = stage_root.parent.name
        payload = next((root / "workflow" / "backups" / transaction_id / "files").rglob("*"))
        while payload.is_dir(): payload = next(payload.iterdir())
        payload.write_bytes(b"tampered")
        return result
    monkeypatch.setattr(engine, "_stage_writes", stage_then_tamper)
    with pytest.raises(BackupError): apply_plan(make_plan(root, sha256_file(target)))
    assert target.read_bytes() == b"old"


def test_mixed_committing_journal_restores_all_entries(tmp_path: Path) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    first, second = root / "first", root / "second"; first.write_bytes(b"one"); second.write_bytes(b"two")
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(
        WriteOperation.from_bytes("neutral", "first", b"ONE", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second", b"TWO", sha256_file(second), Ownership.CANONICAL),
    ))
    journal = apply_plan(plan); path = Path(journal.journal_path)
    payload = json.loads(path.read_text()); payload["status"] = "committing"; path.write_text(json.dumps(payload))
    first.write_bytes(b"one")
    rollback_transaction(path)
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"


def test_lock_replacement_between_identity_and_token_check_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".workflow.lock"; lock = ScopeLock(path); lock.__enter__()
    original = type(path).read_text
    def replace_then_read(item: Path, *args: object, **kwargs: object) -> str:
        if item == path:
            path.unlink(); path.write_text("replacement", encoding="utf-8")
        return original(item, *args, **kwargs)
    monkeypatch.setattr(type(path), "read_text", replace_then_read)
    lock.__exit__(None, None, None)
    assert path.read_text(encoding="utf-8") == "replacement"
