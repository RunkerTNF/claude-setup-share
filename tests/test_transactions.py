import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import UUID

import pytest

from agent_workflow.errors import BackupError, ConflictError, SourceChangedError, TransactionBusyError, UnsafePathError
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation
from agent_workflow.transactions.engine import apply_plan, rollback_transaction
from agent_workflow.transactions.journal import TransactionJournal
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
    def fail_recovery_status(journal: object, **kwargs: object) -> None:
        if getattr(journal, "status") == "rolling_back": raise OSError("journal recovery failure")
        real_write(journal, **kwargs)
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


def test_automatic_restore_parent_symlink_attack_is_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, outside = tmp_path / ".agents", tmp_path / "outside"
    nested = root / "nested"; nested.mkdir(parents=True); outside.mkdir()
    first, second = nested / "first.txt", root / "second.txt"
    first.write_bytes(b"first before"); second.write_bytes(b"second before")
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(
        WriteOperation.from_bytes("neutral", "nested/first.txt", b"first after", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second.txt", b"second after", sha256_file(second), Ownership.CANONICAL),
    ))
    from agent_workflow.transactions import engine
    real_replace, real_stage = os.replace, engine._create_stage_root
    def fail_second(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == second: raise OSError("original commit failure")
        real_replace(source, destination)
    def stage_then_attack(parent: Path, transaction_id: str, label: str) -> Path:
        result = real_stage(parent, transaction_id, label)
        if label.startswith("restore-"):
            shutil.rmtree(nested)
            try: nested.symlink_to(outside, target_is_directory=True)
            except OSError: pytest.skip("symlink creation unavailable")
        return result
    monkeypatch.setattr(engine.os, "replace", fail_second)
    monkeypatch.setattr(engine, "_create_stage_root", stage_then_attack)
    with pytest.raises(OSError, match="original commit failure") as error:
        apply_plan(plan)
    assert any("rollback cleanup failed" in note for note in error.value.__notes__)
    assert not (outside / "first.txt").exists()
    journals = list((root / "workflow" / "journals").glob("*.json")); assert len(journals) == 1
    payload = json.loads(journals[0].read_text()); assert payload["status"] == "rollback_failed"
    assert (root / "workflow" / "backups" / payload["transaction_id"]).is_dir()
    nested.unlink(); nested.mkdir(); first.write_bytes(b"first after"); second.write_bytes(b"second after")
    monkeypatch.setattr(engine.os, "replace", real_replace); monkeypatch.setattr(engine, "_create_stage_root", real_stage)
    rollback_transaction(journals[0])
    assert first.read_bytes() == b"first before" and second.read_bytes() == b"second before"


@pytest.mark.parametrize("member", ("backup", "staging", "journal"))
def test_apply_rejects_preexisting_transaction_namespace_without_debris(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    transaction_id = "11111111-1111-1111-1111-111111111111"
    workflow = root / "workflow"
    backup_path = workflow / "backups" / transaction_id
    staging_path = workflow / "staging" / transaction_id
    journal_path = workflow / "journals" / f"{transaction_id}.json"
    selected = {"backup": backup_path, "staging": staging_path, "journal": journal_path}[member]
    if member == "journal":
        selected.parent.mkdir(parents=True); selected.write_bytes(b"prior recovery evidence")
    else:
        selected.mkdir(parents=True); (selected / "marker").write_bytes(b"owned")
    from agent_workflow.transactions import engine
    monkeypatch.setattr(engine, "uuid4", lambda: UUID(transaction_id))

    with pytest.raises(BackupError, match="namespace"):
        apply_plan(make_plan(root, None))

    assert selected.is_file() and selected.read_bytes() == b"prior recovery evidence" if member == "journal" else (selected / "marker").read_bytes() == b"owned"
    assert not backup_path.exists() if member != "backup" else True
    assert not staging_path.exists() if member != "staging" else True
    assert not journal_path.exists() if member != "journal" else True


@pytest.mark.parametrize("failure_point", ("write", "flush", "fsync", "fstat"))
def test_partial_lock_acquisition_cleans_owned_lock_and_can_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str) -> None:
    from agent_workflow.transactions import lock as lock_module
    path = tmp_path / ".workflow.lock"
    if failure_point in {"write", "flush"}:
        method = "_write_token" if failure_point == "write" else "_flush_token"
        original = getattr(ScopeLock, method)
        monkeypatch.setattr(ScopeLock, method, lambda *_args: (_ for _ in ()).throw(OSError(f"{failure_point} failed")))
    else:
        original = getattr(lock_module.os, failure_point)
        monkeypatch.setattr(lock_module.os, failure_point, lambda *_args: (_ for _ in ()).throw(OSError(f"{failure_point} failed")))
    with pytest.raises(OSError, match=failure_point):
        ScopeLock(path).__enter__()
    if failure_point == "fstat":
        assert path.exists()
        path.unlink()
    else:
        assert not path.exists()
    if failure_point in {"write", "flush"}:
        monkeypatch.setattr(ScopeLock, method, original)
    else:
        monkeypatch.setattr(lock_module.os, failure_point, original)
    with ScopeLock(path):
        assert path.exists()


def test_lock_replacement_before_identity_capture_survives_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".workflow.lock"
    def replace_then_fail(_self: ScopeLock, handle: object) -> tuple[int, int]:
        handle.close(); path.unlink(); path.write_bytes(b"replacement")
        raise OSError("identity capture failed")
    monkeypatch.setattr(ScopeLock, "_capture_identity", replace_then_fail)
    with pytest.raises(OSError, match="identity capture failed"):
        ScopeLock(path).__enter__()
    assert path.read_bytes() == b"replacement"


@pytest.mark.parametrize("racing_member", ("staging", "journal"))
def test_namespace_race_preserves_evidence_and_leaves_no_owned_debris(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, racing_member: str) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"
    transaction_id = "22222222-2222-2222-2222-222222222222"
    from agent_workflow.transactions import engine
    monkeypatch.setattr(engine, "uuid4", lambda: UUID(transaction_id))
    original_claim = engine._claim_transaction_namespace
    def claim_then_race(*args: object, **kwargs: object) -> object:
        result = original_claim(*args, **kwargs)
        workflow = root / "workflow"
        if racing_member == "staging":
            race = workflow / "staging" / transaction_id / "racer"; race.mkdir(parents=True); (race / "evidence").write_bytes(b"racer")
        else:
            race = workflow / "journals" / f"{transaction_id}.json"; race.write_bytes(b"racer evidence")
        return result
    monkeypatch.setattr(engine, "_claim_transaction_namespace", claim_then_race)
    with pytest.raises(BackupError):
        apply_plan(make_plan(root, None))
    assert not target.exists()
    assert not (root / "workflow" / "backups" / transaction_id).exists()
    evidence = (root / "workflow" / "staging" / transaction_id / "racer" / "evidence") if racing_member == "staging" else (root / "workflow" / "journals" / f"{transaction_id}.json")
    assert b"racer" in evidence.read_bytes()


def test_initial_journal_publication_failure_preserves_backup_claim_marker_and_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"
    from agent_workflow.transactions import engine
    monkeypatch.setattr(engine, "_sync_initial_journal", lambda _output: (_ for _ in ()).throw(OSError("exclusive publication unavailable")))
    with pytest.raises(OSError, match="publication unavailable"):
        apply_plan(make_plan(root, None))
    assert not target.exists()
    assert (next((root / "workflow" / "backups").iterdir()) / "inventory.json").exists()
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert claim["schema_version"] == 1 and claim["status"] == "preparing"
    assert marker == expected_marker
    assert list((root / "workflow" / "journals").iterdir())


def test_failed_publication_preserves_foreign_backup_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    from agent_workflow.transactions import engine
    def add_foreign_then_fail(_output: object) -> None:
        backup_root = next((root / "workflow" / "backups").iterdir())
        (backup_root / "foreign").write_bytes(b"foreign")
        raise OSError("publication failed")
    monkeypatch.setattr(engine, "_sync_initial_journal", add_foreign_then_fail)
    with pytest.raises(OSError, match="publication failed"):
        apply_plan(make_plan(root, None))
    backup_root = next((root / "workflow" / "backups").iterdir())
    assert (backup_root / "foreign").read_bytes() == b"foreign"
    assert (backup_root / "inventory.json").exists()


@pytest.mark.parametrize("failure_point", ("backup_write", "backup_verify", "stage_write", "revalidate", "journal_publish"))
def test_prepublication_failure_preserves_original_error_backup_and_strict_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"; target.write_bytes(b"before")
    from agent_workflow.transactions import engine, backup as backup_module
    if failure_point == "backup_write":
        real = backup_module.create_backup
        def create_then_fail(*args: object, **kwargs: object) -> object:
            real(*args, **kwargs); raise OSError("backup_write failure")
        monkeypatch.setattr(backup_module, "create_backup", create_then_fail)
    elif failure_point == "backup_verify":
        monkeypatch.setattr(backup_module, "verify_backup", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("backup_verify failure")))
    elif failure_point == "stage_write":
        real = engine._stage_writes
        def stage_then_fail(*args: object, **kwargs: object) -> object:
            real(*args, **kwargs); raise OSError("stage_write failure")
        monkeypatch.setattr(engine, "_stage_writes", stage_then_fail)
    elif failure_point == "revalidate":
        monkeypatch.setattr(engine, "_revalidate_complete_plan", lambda *_args: (_ for _ in ()).throw(OSError("revalidate failure")))
    else:
        monkeypatch.setattr(engine, "_sync_initial_journal", lambda _output: (_ for _ in ()).throw(OSError("journal_publish failure")))
    with pytest.raises(OSError, match=f"{failure_point} failure"):
        apply_plan(make_plan(root, sha256_file(target)))
    assert target.read_bytes() == b"before"
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert set(claim) == {"schema_version", "status", "transaction_id", "token", "scope_root", "target_roots", "allowed_roots", "backup_root", "staging_root", "journal_path", "entries"}
    assert claim["status"] == "preparing" and len(claim["entries"]) == 1
    assert marker == expected_marker
    backup_dirs = list((root / "workflow" / "backups").iterdir())
    assert backup_dirs and (backup_dirs[0] / "inventory.json").exists()


def test_foreign_replacement_claim_with_same_ids_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"; target.write_bytes(b"before")
    from agent_workflow.transactions import backup as backup_module
    real_create = backup_module.create_backup
    foreign_raw: bytes | None = None
    def replace_claim_then_fail(*args: object, **kwargs: object) -> object:
        nonlocal foreign_raw
        result = real_create(*args, **kwargs)
        claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
        payload = json.loads(claim_path.read_text())
        payload["target_roots"]["neutral"] = str(tmp_path / "foreign")
        payload["entries"][0]["path"] = "foreign"
        foreign_raw = json.dumps(payload, sort_keys=True).encode()
        claim_path.unlink(); claim_path.write_bytes(foreign_raw)
        raise OSError("backup phase failed")
    monkeypatch.setattr(backup_module, "create_backup", replace_claim_then_fail)
    with pytest.raises(OSError, match="backup phase failed") as error:
        apply_plan(make_plan(root, sha256_file(target)))
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    assert claim_path.read_bytes() == foreign_raw
    assert any("prepare_failed" in note for note in error.value.__notes__)


def test_substituted_prepared_journal_and_claim_survive_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".agents"; root.mkdir(); target = root / "RULES.md"; target.write_bytes(b"before")
    from agent_workflow.transactions import engine
    foreign_journal: bytes | None = None
    def substitute(journal_path: Path) -> None:
        nonlocal foreign_journal
        payload = json.loads(journal_path.read_text()); payload["target_roots"]["neutral"] = str(tmp_path / "foreign")
        foreign_journal = json.dumps(payload, sort_keys=True).encode()
        journal_path.unlink(); journal_path.write_bytes(foreign_journal)
    monkeypatch.setattr(engine, "_after_initial_journal_sync", substitute, raising=False)
    with pytest.raises(BackupError):
        apply_plan(make_plan(root, sha256_file(target)))
    journal_path = next((root / "workflow" / "journals").glob("*.json"))
    assert journal_path.read_bytes() == foreign_journal
    assert next((root / "workflow" / "staging").rglob("claim.json")).exists()
    assert target.read_bytes() == b"before"


@pytest.mark.parametrize("phase", ("backup", "stage"))
def test_genuine_partial_preparation_retains_bytes_and_failed_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    root = tmp_path / ".agents"; root.mkdir()
    first, second = root / "first", root / "second"; first.write_bytes(b"first"); second.write_bytes(b"second")
    plan = TransactionPlan.new(scope_root=str(root), target_roots={"neutral": str(root), "scope": str(tmp_path)}, allowed_roots=(str(tmp_path),), operations=(
        WriteOperation.from_bytes("neutral", "first", b"FIRST", sha256_file(first), Ownership.CANONICAL),
        WriteOperation.from_bytes("neutral", "second", b"SECOND", sha256_file(second), Ownership.CANONICAL),
    ))
    from agent_workflow.transactions import engine, backup as backup_module
    if phase == "backup":
        real_write = backup_module._write_fsynced; count = 0
        def fail_second(path: Path, payload: bytes) -> None:
            nonlocal count
            if "files" in path.parts:
                count += 1
                if count == 2: raise OSError("partial backup failure")
            real_write(path, payload)
        monkeypatch.setattr(backup_module, "_write_fsynced", fail_second)
    else:
        real_write = engine._write_fsynced; count = 0
        def fail_second(path: Path, payload: bytes) -> None:
            nonlocal count
            if "apply" in path.parts:
                count += 1
                if count == 2: raise OSError("partial stage failure")
            real_write(path, payload)
        monkeypatch.setattr(engine, "_write_fsynced", fail_second)
    error_type = BackupError if phase == "backup" else OSError
    with pytest.raises(error_type, match=f"partial {phase} failure"):
        apply_plan(plan)
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert claim["status"] == "preparing"
    assert marker == expected_marker
    assert first.read_bytes() == b"first" and second.read_bytes() == b"second"
    backup_root = next((root / "workflow" / "backups").iterdir())
    assert (backup_root / "files" / "neutral" / "first").read_bytes() == b"first"
    if phase == "stage":
        assert (claim_path.parent / "apply" / "neutral" / "first").read_bytes() == b"FIRST"


@pytest.mark.parametrize("phase", ("backup_parent", "journal_parent"))
def test_directory_fsync_failure_preserves_claim_backup_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    target = root / "RULES.md"
    target.write_bytes(b"before")
    from agent_workflow.transactions import engine

    failing_path = root / "workflow" / ("backups" if phase == "backup_parent" else "journals")
    matching_calls = 0

    def fail_once(path: Path) -> None:
        nonlocal matching_calls
        if path == failing_path:
            matching_calls += 1
            if matching_calls == 2:
                raise OSError("directory fsync failure")

    monkeypatch.setattr(engine, "_fsync_directory", fail_once, raising=False)
    with pytest.raises(OSError, match="directory fsync failure"):
        apply_plan(make_plan(root, sha256_file(target)))

    assert target.read_bytes() == b"before"
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert claim["status"] == "preparing"
    assert marker == expected_marker
    backup_root = next((root / "workflow" / "backups").iterdir())
    assert (backup_root / "files" / "neutral" / "RULES.md").read_bytes() == b"before"


def test_initial_journal_close_cleanup_failure_keeps_publish_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    target = root / "RULES.md"
    target.write_bytes(b"before")
    from agent_workflow.transactions import engine

    def fail_sync(_output: object) -> None:
        raise OSError("journal sync failed")

    def close_then_fail(output: object) -> None:
        output.close()
        raise OSError("journal close cleanup failed")

    monkeypatch.setattr(engine, "_sync_initial_journal", fail_sync)
    monkeypatch.setattr(engine, "_close_initial_journal", close_then_fail, raising=False)

    with pytest.raises(OSError, match="journal sync failed") as error:
        apply_plan(make_plan(root, sha256_file(target)))

    assert any("journal close cleanup failed" in note for note in error.value.__notes__)
    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert claim["status"] == "preparing"
    assert marker == expected_marker
    backup_root = next((root / "workflow" / "backups").iterdir())
    assert (backup_root / "files" / "neutral" / "RULES.md").read_bytes() == b"before"
    assert target.read_bytes() == b"before"


def test_success_keeps_original_claim_bytes_and_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    target = root / "RULES.md"
    target.write_bytes(b"before")
    from agent_workflow.transactions import engine

    captured: dict[str, Any] = {}

    def capture_claim(_journal_path: Path) -> None:
        claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
        stat = claim_path.lstat()
        captured.update(path=claim_path, raw=claim_path.read_bytes(), identity=(stat.st_dev, stat.st_ino))

    monkeypatch.setattr(engine, "_after_initial_journal_sync", capture_claim)
    apply_plan(make_plan(root, sha256_file(target)))

    claim_path = captured["path"]
    stat = claim_path.lstat()
    assert claim_path.read_bytes() == captured["raw"]
    assert (stat.st_dev, stat.st_ino) == captured["identity"]
    assert engine._read_claim(claim_path)["status"] == "preparing"
    assert not claim_path.with_name("prepare_failed.json").exists()


def test_failure_keeps_original_claim_and_writes_exclusive_full_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    target = root / "RULES.md"
    target.write_bytes(b"before")
    from agent_workflow.transactions import backup as backup_module
    from agent_workflow.transactions import engine

    real_create = backup_module.create_backup
    captured: dict[str, Any] = {}
    real_claim = engine._claim_transaction_namespace

    def capture_namespace(*args: object, **kwargs: object) -> object:
        claim = real_claim(*args, **kwargs)
        captured["claim"] = claim
        return claim

    def capture_then_fail(*args: object, **kwargs: object) -> object:
        real_create(*args, **kwargs)
        claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
        stat = claim_path.lstat()
        captured.update(path=claim_path, raw=claim_path.read_bytes(), identity=(stat.st_dev, stat.st_ino))
        raise OSError("preparation failed")

    monkeypatch.setattr(engine, "_claim_transaction_namespace", capture_namespace)
    monkeypatch.setattr(backup_module, "create_backup", capture_then_fail)
    with pytest.raises(OSError, match="preparation failed"):
        apply_plan(make_plan(root, sha256_file(target)))

    claim_path = captured["path"]
    stat = claim_path.lstat()
    assert claim_path.read_bytes() == captured["raw"]
    assert (stat.st_dev, stat.st_ino) == captured["identity"]
    claim = engine._read_claim(claim_path)
    marker_path = claim_path.with_name("prepare_failed.json")
    marker_raw = marker_path.read_bytes()
    marker = engine._read_claim(marker_path)
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    assert claim["status"] == "preparing"
    assert marker == expected_marker

    with pytest.raises(BackupError):
        engine._verify_namespace_claim(captured["claim"])
    engine._verify_namespace_claim(captured["claim"], allow_prepare_failed=True)

    with pytest.raises(BackupError):
        engine._write_claim(captured["claim"], "prepare_failed")
    assert marker_path.read_bytes() == marker_raw


def test_internal_directory_fsyncs_new_path_and_parent_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_workflow.transactions import engine

    path = tmp_path / "workflow"
    calls: list[Path] = []
    monkeypatch.setattr(engine, "_fsync_directory", calls.append)

    assert engine._ensure_internal_directory(path) == path
    assert calls == [path, path.parent]

    calls.clear()
    assert engine._ensure_internal_directory(path) == path
    assert calls == []


def test_apply_fsyncs_each_new_internal_directory_hierarchy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    from agent_workflow.transactions import engine

    calls: list[Path] = []
    monkeypatch.setattr(engine, "_fsync_directory", calls.append)
    apply_plan(make_plan(root, None))

    workflow = root / "workflow"
    assert calls[:8] == [
        workflow,
        root,
        workflow / "backups",
        workflow,
        workflow / "staging",
        workflow,
        workflow / "journals",
        workflow,
    ]


def test_fsync_failure_after_authoritative_journal_preserves_all_recovery_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    target = root / "RULES.md"
    target.write_bytes(b"before")
    from agent_workflow.transactions import engine

    publication_synced = False
    failed = False

    def mark_publication_synced(_journal_path: Path) -> None:
        nonlocal publication_synced
        publication_synced = True

    def fail_once_after_authority(path: Path) -> None:
        nonlocal failed
        if publication_synced and path.parent.name == "staging" and not failed:
            failed = True
            raise OSError("post-authoritative directory fsync failed")

    monkeypatch.setattr(engine, "_after_initial_journal_sync", mark_publication_synced)
    monkeypatch.setattr(engine, "_fsync_directory", fail_once_after_authority)

    with pytest.raises(OSError, match="post-authoritative directory fsync failed"):
        apply_plan(make_plan(root, sha256_file(target)))

    claim_path = next((root / "workflow" / "staging").rglob("claim.json"))
    claim = engine._read_claim(claim_path)
    marker = engine._read_claim(claim_path.with_name("prepare_failed.json"))
    expected_marker = dict(claim)
    expected_marker["status"] = "prepare_failed"
    journal_path = next((root / "workflow" / "journals").glob("*.json"))
    journal = TransactionJournal.from_json(journal_path.read_text(encoding="utf-8"))
    backup_root = next((root / "workflow" / "backups").iterdir())

    assert claim["status"] == "preparing"
    assert marker == expected_marker
    assert journal.status == "prepared"
    assert (backup_root / "files" / "neutral" / "RULES.md").read_bytes() == b"before"
    assert target.read_bytes() == b"before"
