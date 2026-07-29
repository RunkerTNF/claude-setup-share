from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from agent_workflow.errors import BackupError, ConflictError, SourceChangedError, UnsafePathError
from agent_workflow.hashing import sha256_bytes, sha256_file
from agent_workflow.paths import resolve_write_target
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation

from . import backup
from .journal import JournalEntry, TransactionJournal
from .lock import ScopeLock


_INTERNAL_NAMES = ("backups", "staging", "journals")


@dataclass(frozen=True)
class _ResolvedOperation:
    operation: WriteOperation | DeleteOperation
    target: Path
    existed: bool
    before_sha256: str | None


def apply_plan(plan: TransactionPlan) -> TransactionJournal:
    """Apply one fully validated plan or restore its complete scope on failure."""
    plan.validate()
    if plan.conflicts:
        raise ConflictError("transaction plan contains conflicts")
    scope_root, resolved_operations = _resolve_plan(plan)
    _reject_internal_collisions(scope_root, resolved_operations)
    _ensure_scope_root(scope_root)
    with ScopeLock(scope_root / ".workflow.lock"):
        _verify_pre_state(resolved_operations)
        transaction_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        workflow_root = _ensure_internal_directory(scope_root / "workflow")
        backup_parent = _ensure_internal_directory(workflow_root / "backups")
        staging_parent = _ensure_internal_directory(workflow_root / "staging")
        journal_parent = _ensure_internal_directory(workflow_root / "journals")
        backup_root = backup_parent / transaction_id
        sources = tuple(
            backup.BackupSource(item.operation.root_id, item.operation.path, item.target, item.existed, item.before_sha256)
            for item in resolved_operations
        )
        _, warnings = backup.create_backup(backup_root, sources)
        backup.verify_backup(backup_root, sources)
        stage_root = _create_stage_root(staging_parent, transaction_id, "apply")
        staged = _stage_writes(stage_root, resolved_operations)
        _revalidate_complete_plan(plan, resolved_operations)
        entries = tuple(
            JournalEntry(
                root_id=item.operation.root_id,
                path=item.operation.path,
                operation_kind="write" if isinstance(item.operation, WriteOperation) else "delete",
                existed=item.existed,
                before_sha256=item.before_sha256,
                after_sha256=sha256_bytes(item.operation.content_bytes()) if isinstance(item.operation, WriteOperation) else None,
            )
            for item in resolved_operations
        )
        journal_path = journal_parent / f"{transaction_id}.json"
        journal = TransactionJournal(
            schema_version=1,
            transaction_id=transaction_id,
            created_at=created_at,
            scope_root=str(scope_root),
            target_roots={root_id: str(Path(path).resolve(strict=False)) for root_id, path in plan.target_roots.items()},
            allowed_roots=tuple(str(Path(path).resolve(strict=False)) for path in plan.allowed_roots),
            status="prepared",
            entries=entries,
            backup_root=str(backup_root),
            journal_path=str(journal_path),
            warnings=warnings,
        )
        _write_journal(journal)
        backup.verify_backup(backup_root, sources)
        _revalidate_complete_plan(plan, resolved_operations)
        committing_started = False
        try:
            committing_started = True
            journal = journal.with_status("committing")
            _write_journal(journal)
            for item in resolved_operations:
                _revalidate_plan_item(plan, item)
                if isinstance(item.operation, WriteOperation):
                    item.target.parent.mkdir(parents=True, exist_ok=True)
                    _verify_current_target(item.target, item.before_sha256, context="source changed during apply")
                    os.replace(staged[(item.operation.root_id, item.operation.path)], item.target)
                else:
                    _verify_current_target(item.target, item.before_sha256, context="source changed during apply")
                    item.target.unlink()
            journal = journal.with_status("committed")
            _write_journal(journal)
            return journal
        except Exception as original_error:
            if committing_started:
                rolling_back = journal.with_status("rolling_back")
                try:
                    _write_journal(rolling_back)
                except Exception as recovery_error:
                    original_error.add_note(f"could not persist rolling_back: {recovery_error}")
                try:
                    _restore_from_backup(scope_root, staging_parent, transaction_id, resolved_operations, backup_root, sources)
                except Exception as cleanup_error:
                    original_error.add_note(f"rollback cleanup failed: {cleanup_error}")
                    try:
                        _write_journal(rolling_back.with_status("rollback_failed"))
                    except Exception as recovery_error:
                        original_error.add_note(f"could not persist rollback_failed: {recovery_error}")
                else:
                    try:
                        _write_journal(rolling_back.with_status("rolled_back"))
                    except Exception as recovery_error:
                        original_error.add_note(f"could not persist rolled_back: {recovery_error}")
            raise


def rollback_transaction(journal_path: Path) -> TransactionJournal:
    supplied_path = _lexical_path(Path(journal_path))
    if len(supplied_path.parents) < 3:
        raise ValueError("journal path is not a transaction journal location")
    _assert_no_symlink_components(supplied_path.parents[2], ("workflow", "journals", supplied_path.name))
    journal = TransactionJournal.from_json(supplied_path.read_text(encoding="utf-8"))
    if supplied_path != _lexical_path(Path(journal.journal_path)):
        raise ValueError("journal path does not match the transaction location")
    if journal.status not in {"committed", "committing", "rolling_back", "rollback_failed"}:
        raise ConflictError(f"transaction is not committed: {journal.status}")
    scope_root = Path(journal.scope_root)
    _ensure_scope_root(scope_root)
    with ScopeLock(scope_root / ".workflow.lock"):
        _assert_no_symlink_components(scope_root, ("workflow", "journals", Path(journal.journal_path).name))
        _assert_no_symlink_components(scope_root, ("workflow", "backups", journal.transaction_id, "inventory.json"))
        workflow_root = _ensure_internal_directory(scope_root / "workflow")
        staging_parent = _ensure_internal_directory(workflow_root / "staging")
        expected_backup_root = workflow_root / "backups" / journal.transaction_id
        if _lexical_path(Path(journal.backup_root)) != _lexical_path(expected_backup_root):
            raise ValueError("backup_root does not match the transaction location")
        resolved = _resolve_journal_entries(journal)
        _reject_internal_collisions(scope_root, resolved)
        sources = tuple(
            backup.BackupSource(entry.root_id, entry.path, target, entry.existed, entry.before_sha256)
            for entry, target in resolved
        )
        backup.verify_backup(expected_backup_root, sources)
        for entry, target in resolved:
            current = _safe_sha256(target)
            allowed_states = {entry.after_sha256}
            if journal.status in {"committing", "rolling_back", "rollback_failed"}:
                allowed_states.add(entry.before_sha256)
            if current not in allowed_states:
                raise SourceChangedError(f"rollback refused due to drift: {target}")
        rolling_back = journal.with_status("rolling_back")
        _write_journal(rolling_back)
        try:
            _restore_from_backup_entries(scope_root, staging_parent, journal.transaction_id, resolved, expected_backup_root, sources)
        except Exception:
            _write_journal(rolling_back.with_status("rollback_failed"))
            raise
        rolled_back = rolling_back.with_status("rolled_back")
        _write_journal(rolled_back)
        return rolled_back


def _resolve_plan(plan: TransactionPlan) -> tuple[Path, tuple[_ResolvedOperation, ...]]:
    roots = {root_id: Path(path) for root_id, path in plan.target_roots.items()}
    allowed = tuple(Path(path) for path in plan.allowed_roots)
    scope_root = Path(plan.scope_root).resolve(strict=False)
    result: list[_ResolvedOperation] = []
    for operation in plan.operations:
        target = resolve_write_target(operation.root_id, operation.path, roots, allowed)
        _reject_target_symlinks(roots[operation.root_id], operation.path)
        before_sha256 = _safe_sha256(target)
        result.append(_ResolvedOperation(operation, target, before_sha256 is not None, before_sha256))
    return scope_root, tuple(result)


def _resolve_journal_entries(journal: TransactionJournal) -> tuple[tuple[JournalEntry, Path], ...]:
    roots = {root_id: Path(path) for root_id, path in journal.target_roots.items()}
    allowed = tuple(Path(path) for path in journal.allowed_roots)
    resolved: list[tuple[JournalEntry, Path]] = []
    for entry in journal.entries:
        target = resolve_write_target(entry.root_id, entry.path, roots, allowed)
        _reject_target_symlinks(roots[entry.root_id], entry.path)
        resolved.append((entry, target))
    return tuple(resolved)


def _reject_target_symlinks(root: Path, relative_path: str) -> None:
    current = root
    if current.is_symlink():
        raise UnsafePathError(f"target root is a symlink: {root}")
    for part in relative_path.split("/"):
        current /= part
        if current.is_symlink():
            raise UnsafePathError(f"target path contains a symlink: {current}")
        if not current.exists():
            break


def _lexical_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("transaction paths must be absolute")
    return Path(os.path.normpath(os.path.abspath(path)))


def _assert_no_symlink_components(anchor: Path, components: tuple[str, ...]) -> None:
    if anchor.is_symlink():
        raise UnsafePathError(f"transaction storage anchor is a symlink: {anchor}")
    current = anchor
    for component in components:
        current /= component
        if current.is_symlink():
            raise UnsafePathError(f"transaction storage contains a symlink: {current}")


def _verify_pre_state(operations: Iterable[_ResolvedOperation]) -> None:
    for item in operations:
        expected = item.operation.expected_sha256
        if item.before_sha256 != expected:
            raise SourceChangedError(f"source hash mismatch before apply: {item.target}")


def _verify_current_target(target: Path, expected_sha256: str | None, *, context: str) -> None:
    current = _safe_sha256(target)
    if current != expected_sha256:
        raise SourceChangedError(f"{context}: {target}")


def _safe_sha256(path: Path) -> str | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise UnsafePathError(f"transaction target is not a regular file: {path}")
    try:
        return sha256_file(path)
    except OSError as error:
        raise SourceChangedError(f"unable to hash transaction target: {path}") from error


def _reject_internal_collisions(scope_root: Path, operations: Iterable[object]) -> None:
    protected = [scope_root / ".workflow.lock", *(scope_root / "workflow" / name for name in _INTERNAL_NAMES)]
    for item in operations:
        target = item.target if isinstance(item, _ResolvedOperation) else item[1]
        for internal in protected:
            if _overlaps(target, internal):
                raise UnsafePathError(f"plan operation collides with transaction storage: {target}")


def _overlaps(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False


def _revalidate_complete_plan(plan: TransactionPlan, operations: Iterable[_ResolvedOperation]) -> None:
    for item in operations:
        _revalidate_plan_item(plan, item)
        _verify_current_target(item.target, item.before_sha256, context="source changed during apply")


def _revalidate_plan_item(plan: TransactionPlan, item: _ResolvedOperation) -> None:
    roots = {root_id: Path(path) for root_id, path in plan.target_roots.items()}
    allowed = tuple(Path(path) for path in plan.allowed_roots)
    target = resolve_write_target(item.operation.root_id, item.operation.path, roots, allowed)
    _reject_target_symlinks(roots[item.operation.root_id], item.operation.path)
    if target != item.target:
        raise UnsafePathError(f"transaction target changed after approval: {item.target}")


def _ensure_scope_root(scope_root: Path) -> None:
    if scope_root.is_symlink():
        raise UnsafePathError(f"scope root is a symlink: {scope_root}")
    scope_root.mkdir(parents=True, exist_ok=True)
    if not scope_root.is_dir() or scope_root.is_symlink():
        raise UnsafePathError(f"scope root is not a directory: {scope_root}")


def _ensure_internal_directory(path: Path) -> Path:
    if path.is_symlink():
        raise UnsafePathError(f"transaction storage is a symlink: {path}")
    path.mkdir(exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise UnsafePathError(f"transaction storage is not a directory: {path}")
    return path


def _create_stage_root(parent: Path, transaction_id: str, label: str) -> Path:
    root = parent / transaction_id / label
    if root.exists() or root.is_symlink():
        raise BackupError(f"staging location already exists or is unsafe: {root}")
    root.mkdir(parents=True)
    return root


def _stage_writes(stage_root: Path, operations: Iterable[_ResolvedOperation]) -> dict[tuple[str, str], Path]:
    staged: dict[tuple[str, str], Path] = {}
    for item in operations:
        if not isinstance(item.operation, WriteOperation):
            continue
        destination = stage_root / item.operation.root_id / Path(*item.operation.path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_fsynced(destination, item.operation.content_bytes())
        staged[(item.operation.root_id, item.operation.path)] = destination
    return staged


def _restore_from_backup(
    scope_root: Path,
    staging_parent: Path,
    transaction_id: str,
    operations: tuple[_ResolvedOperation, ...],
    backup_root: Path,
    sources: tuple[backup.BackupSource, ...],
) -> None:
    resolved = tuple(
        (
            JournalEntry(
                root_id=item.operation.root_id,
                path=item.operation.path,
                operation_kind="write" if isinstance(item.operation, WriteOperation) else "delete",
                existed=item.existed,
                before_sha256=item.before_sha256,
                after_sha256=sha256_bytes(item.operation.content_bytes()) if isinstance(item.operation, WriteOperation) else None,
            ),
            item.target,
        )
        for item in operations
    )
    _restore_from_backup_entries(scope_root, staging_parent, transaction_id, resolved, backup_root, sources)


def _restore_from_backup_entries(
    _scope_root: Path,
    staging_parent: Path,
    transaction_id: str,
    resolved: tuple[tuple[JournalEntry, Path], ...],
    backup_root: Path,
    sources: tuple[backup.BackupSource, ...],
) -> None:
    inventory = backup.verify_backup(backup_root, sources)
    inventory_by_target = {(entry.root_id, entry.path): entry for entry in inventory}
    stage_root = _create_stage_root(staging_parent, transaction_id, f"restore-{uuid4()}")
    staged: dict[tuple[str, str], Path] = {}
    for entry, _target in resolved:
        if not entry.existed:
            continue
        payload = backup.read_verified_payload(backup_root, inventory_by_target[(entry.root_id, entry.path)])
        destination = stage_root / entry.root_id / Path(*entry.path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_fsynced(destination, payload)
        staged[(entry.root_id, entry.path)] = destination
    failures: list[Exception] = []
    for entry, target in resolved:
        try:
            if entry.existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged[(entry.root_id, entry.path)], target)
            else:
                if target.exists() or target.is_symlink():
                    if target.is_dir():
                        raise BackupError(f"cannot remove unexpected directory during rollback: {target}")
                    target.unlink()
                _cleanup_empty_parents(target.parent, _target_root_for_entry(entry, resolved))
        except Exception as error:
            failures.append(error)
    if failures:
        raise BackupError("rollback restoration incomplete: " + "; ".join(str(error) for error in failures))


def _target_root_for_entry(entry: JournalEntry, resolved: tuple[tuple[JournalEntry, Path], ...]) -> Path:
    # The parent cleanup boundary must be no broader than the operation's root.
    target = dict(resolved)[entry]
    return target.parent if "/" not in entry.path else target.parents[len(entry.path.split("/")) - 1]


def _cleanup_empty_parents(start: Path, boundary: Path) -> None:
    current = start
    while current != boundary:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _write_journal(journal: TransactionJournal) -> None:
    path = Path(journal.journal_path)
    if path.is_symlink():
        raise UnsafePathError(f"journal path is a symlink: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    _write_fsynced(temporary, journal.to_json().encode("utf-8"))
    os.replace(temporary, path)


def _write_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
