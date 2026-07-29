from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from uuid import UUID, uuid4

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


@dataclass(frozen=True)
class _NamespaceClaim:
    staging_root: Path
    claim_path: Path
    journal_path: Path
    token: str
    payload: Mapping[str, object]
    identity: tuple[int, int]


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
        journal_path = journal_parent / f"{transaction_id}.json"
        sources = tuple(
            backup.BackupSource(item.operation.root_id, item.operation.path, item.target, item.existed, item.before_sha256)
            for item in resolved_operations
        )
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
        claim = _claim_transaction_namespace(
            backup_root,
            staging_parent / transaction_id,
            journal_path,
            transaction_id=transaction_id,
            token=str(uuid4()),
            scope_root=str(scope_root),
            target_roots=dict(plan.target_roots),
            allowed_roots=plan.allowed_roots,
            entries=entries,
        )
        try:
            _verify_namespace_claim(claim)
            _, warnings = backup.create_backup(backup_root, sources)
            _fsync_tree_directories(backup_root)
            _fsync_directory(backup_root.parent)
            backup.verify_backup(backup_root, sources)
            stage_root = _create_stage_root(staging_parent, transaction_id, "apply")
            staged = _stage_writes(stage_root, resolved_operations)
            _fsync_tree_directories(stage_root)
            _revalidate_complete_plan(plan, resolved_operations)
        except Exception as preparation_error:
            try:
                _write_claim(claim, "prepare_failed")
            except Exception as claim_error:
                preparation_error.add_note(f"could not persist prepare_failed claim: {claim_error}")
            raise
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
        try:
            _publish_initial_journal(journal, claim)
        except Exception as preparation_error:
            try:
                _write_claim(claim, "prepare_failed")
            except Exception as claim_error:
                preparation_error.add_note(f"could not persist prepare_failed claim: {claim_error}")
            raise
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
                    _cleanup_empty_parents(
                        item.target.parent,
                        Path(plan.target_roots[item.operation.root_id]),
                    )
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
                    _restore_from_backup(scope_root, staging_parent, transaction_id, resolved_operations, backup_root, sources, plan.target_roots, plan.allowed_roots)
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
            _restore_from_backup_entries(scope_root, staging_parent, journal.transaction_id, resolved, expected_backup_root, sources, journal.target_roots, journal.allowed_roots)
        except Exception as restore_error:
            try:
                _write_journal(rolling_back.with_status("rollback_failed"))
            except Exception as journal_error:
                restore_error.add_note(f"could not persist rollback_failed: {journal_error}")
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
    try:
        path.mkdir()
    except FileExistsError:
        pass
    else:
        _fsync_directory(path)
        _fsync_directory(path.parent)
    if not path.is_dir() or path.is_symlink():
        raise UnsafePathError(f"transaction storage is not a directory: {path}")
    return path


def _create_stage_root(parent: Path, transaction_id: str, label: str) -> Path:
    root = parent / transaction_id / label
    if root.exists() or root.is_symlink():
        raise BackupError(f"staging location already exists or is unsafe: {root}")
    root.mkdir(parents=True)
    _fsync_directory(root.parent)
    return root


def _claim_transaction_namespace(
    backup_root: Path,
    staging_root: Path,
    journal_path: Path,
    *,
    transaction_id: str,
    token: str,
    scope_root: str,
    target_roots: Mapping[str, str],
    allowed_roots: Sequence[str],
    entries: tuple[JournalEntry, ...],
) -> _NamespaceClaim:
    existing = [path for path in (backup_root, staging_root, journal_path) if path.exists() or path.is_symlink()]
    if existing:
        raise BackupError(f"transaction namespace already exists: {existing[0]}")
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "preparing",
        "transaction_id": transaction_id,
        "token": token,
        "scope_root": scope_root,
        "target_roots": dict(target_roots),
        "allowed_roots": list(allowed_roots),
        "backup_root": str(backup_root),
        "staging_root": str(staging_root),
        "journal_path": str(journal_path),
        "entries": [entry.to_payload() for entry in entries],
    }
    claim_path = staging_root / "claim.json"
    claim: _NamespaceClaim | None = None
    try:
        staging_root.mkdir()
        identity = _write_fsynced_identity(claim_path, _claim_json(payload))
        claim = _NamespaceClaim(staging_root, claim_path, journal_path, token, payload, identity)
        _read_claim(claim_path)
        _fsync_directory(staging_root)
        _fsync_directory(staging_root.parent)
    except Exception as original_error:
        if claim is not None:
            try:
                _write_claim(claim, "prepare_failed")
            except Exception as claim_error:
                original_error.add_note(f"could not persist prepare_failed claim: {claim_error}")
        raise
    assert claim is not None
    return claim


def _verify_namespace_claim(
    claim: _NamespaceClaim,
    *,
    allow_apply: bool = False,
    allow_journal: bool = False,
    allow_prepare_failed: bool = False,
    expected_status: str = "preparing",
) -> None:
    stat = claim.claim_path.lstat()
    if (stat.st_dev, stat.st_ino) != claim.identity:
        raise BackupError("transaction namespace claim identity changed")
    payload = _read_claim(claim.claim_path)
    expected = dict(claim.payload)
    expected["status"] = expected_status
    if payload != expected:
        raise BackupError("transaction namespace ownership changed")
    if not allow_journal and (claim.journal_path.exists() or claim.journal_path.is_symlink()):
        raise BackupError("transaction namespace journal was claimed by another writer")
    allowed = {claim.claim_path}
    if allow_apply:
        allowed.add(claim.staging_root / "apply")
    if allow_prepare_failed:
        marker_path = claim.staging_root / "prepare_failed.json"
        marker = _read_claim(marker_path)
        expected_marker = dict(claim.payload)
        expected_marker["status"] = "prepare_failed"
        if marker != expected_marker:
            raise BackupError("invalid transaction preparation failure marker")
        allowed.add(marker_path)
    if set(claim.staging_root.iterdir()) != allowed:
        raise BackupError("transaction namespace contains racing artifacts")


def _claim_json(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_claim(path: Path) -> dict[str, object]:
    required = {"schema_version", "status", "transaction_id", "token", "scope_root", "target_roots", "allowed_roots", "backup_root", "staging_root", "journal_path", "entries"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BackupError("invalid transaction preparation claim") from error
    if not isinstance(payload, dict) or set(payload) != required or type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["status"] not in {"preparing", "prepare_failed"}:
        raise BackupError("invalid transaction preparation claim")
    if (
        not all(isinstance(payload[key], str) for key in ("transaction_id", "token", "scope_root", "backup_root", "staging_root", "journal_path"))
        or not isinstance(payload["target_roots"], dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in payload["target_roots"].items())
        or not isinstance(payload["allowed_roots"], list)
        or not all(isinstance(value, str) for value in payload["allowed_roots"])
        or not isinstance(payload["entries"], list)
    ):
        raise BackupError("invalid transaction preparation claim")
    try:
        UUID(payload["transaction_id"])
        UUID(payload["token"])
    except ValueError as error:
        raise BackupError("invalid transaction preparation claim") from error
    scope_root = _lexical_path(Path(payload["scope_root"]))
    transaction_id = payload["transaction_id"]
    if (
        _lexical_path(Path(payload["backup_root"])) != scope_root / "workflow" / "backups" / transaction_id
        or _lexical_path(Path(payload["staging_root"])) != scope_root / "workflow" / "staging" / transaction_id
        or _lexical_path(Path(payload["journal_path"])) != scope_root / "workflow" / "journals" / f"{transaction_id}.json"
    ):
        raise BackupError("invalid transaction preparation claim")
    tuple(JournalEntry.from_payload(item) for item in payload["entries"])
    return payload


def _write_claim(claim: _NamespaceClaim, status: str) -> None:
    if status != "prepare_failed":
        raise BackupError(f"unsupported transaction claim status: {status}")
    allow_apply = (claim.staging_root / "apply").exists()
    allow_journal = claim.journal_path.exists() or claim.journal_path.is_symlink()
    _verify_namespace_claim(claim, allow_apply=allow_apply, allow_journal=allow_journal)
    payload = dict(claim.payload)
    payload["status"] = status
    marker_path = claim.staging_root / "prepare_failed.json"
    identity = _write_fsynced_identity(marker_path, _claim_json(payload))
    stat = marker_path.lstat()
    if identity != (stat.st_dev, stat.st_ino) or _read_claim(marker_path) != payload:
        raise BackupError("invalid transaction preparation failure marker")
    _verify_namespace_claim(
        claim,
        allow_apply=allow_apply,
        allow_journal=allow_journal,
        allow_prepare_failed=True,
    )
    _fsync_directory(claim.staging_root)


def _publish_initial_journal(journal: TransactionJournal, claim: _NamespaceClaim) -> None:
    _verify_namespace_claim(claim, allow_apply=True)
    output = None
    journal_identity: tuple[int, int] | None = None
    try:
        output = claim.journal_path.open("xb")
        stat = os.fstat(output.fileno())
        journal_identity = stat.st_dev, stat.st_ino
        output.write(journal.to_json().encode("utf-8"))
        _sync_initial_journal(output)
        synced = os.fstat(output.fileno())
        if journal_identity != (synced.st_dev, synced.st_ino):
            raise BackupError("published journal handle identity changed")
        _close_initial_journal(output)
        output = None
        _fsync_directory(claim.journal_path.parent)
        _after_initial_journal_sync(claim.journal_path)
        current = claim.journal_path.lstat()
        if journal_identity != (current.st_dev, current.st_ino):
            raise BackupError("published journal identity changed")
        with claim.journal_path.open("rb") as published:
            opened = os.fstat(published.fileno())
            if journal_identity != (opened.st_dev, opened.st_ino):
                raise BackupError("published journal identity changed")
            raw_journal = published.read()
            read = os.fstat(published.fileno())
            if journal_identity != (read.st_dev, read.st_ino):
                raise BackupError("published journal identity changed")
        final = claim.journal_path.lstat()
        if journal_identity != (final.st_dev, final.st_ino):
            raise BackupError("published journal identity changed")
        restored = TransactionJournal.from_json(raw_journal.decode("utf-8"))
        if restored.to_json() != journal.to_json():
            raise BackupError("published journal validation failed")
        _verify_namespace_claim(claim, allow_apply=True, allow_journal=True)
        _fsync_directory(claim.staging_root)
    except FileExistsError as error:
        raise BackupError(f"transaction namespace already exists: {claim.journal_path}") from error
    except Exception as original_error:
        if output is not None:
            try:
                _close_initial_journal(output)
            except Exception as close_error:
                original_error.add_note(f"initial journal close failed: {close_error}")
        raise


def _sync_initial_journal(output: object) -> None:
    output.flush()
    os.fsync(output.fileno())


def _close_initial_journal(output: object) -> None:
    output.close()


def _after_initial_journal_sync(_journal_path: Path) -> None:
    """Test seam for a writer racing after durable journal output closes."""


def _fsync_directory(path: Path) -> None:
    """Flush directory entries on POSIX.

    Python's Windows stdlib cannot open and fsync directory handles, so Windows
    retains fsynced file contents but directory-entry durability is best effort.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(directory)


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
    target_roots: Mapping[str, str],
    allowed_roots: Sequence[str],
) -> None:
    _assert_no_symlink_components(scope_root, ("workflow", "backups", transaction_id, "inventory.json"))
    _assert_no_symlink_components(scope_root, ("workflow", "staging"))
    _assert_no_symlink_components(scope_root, ("workflow", "journals"))
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
    _restore_from_backup_entries(scope_root, staging_parent, transaction_id, resolved, backup_root, sources, target_roots, allowed_roots)


def _restore_from_backup_entries(
    _scope_root: Path,
    staging_parent: Path,
    transaction_id: str,
    resolved: tuple[tuple[JournalEntry, Path], ...],
    backup_root: Path,
    sources: tuple[backup.BackupSource, ...],
    target_roots: Mapping[str, str],
    allowed_roots: Sequence[str],
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
            _revalidate_restore_entry(entry, target, target_roots, allowed_roots)
            if entry.existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                _revalidate_restore_entry(entry, target, target_roots, allowed_roots)
                os.replace(staged[(entry.root_id, entry.path)], target)
            else:
                _revalidate_restore_entry(entry, target, target_roots, allowed_roots)
                if target.exists() or target.is_symlink():
                    if target.is_dir():
                        raise BackupError(f"cannot remove unexpected directory during rollback: {target}")
                    target.unlink()
                _cleanup_empty_parents(target.parent, _target_root_for_entry(entry, resolved))
        except Exception as error:
            failures.append(error)
    if failures:
        raise BackupError("rollback restoration incomplete: " + "; ".join(str(error) for error in failures))


def _revalidate_restore_entry(entry: JournalEntry, approved_target: Path, target_roots: Mapping[str, str], allowed_roots: Sequence[str]) -> None:
    roots = {root_id: Path(path) for root_id, path in target_roots.items()}
    allowed = tuple(Path(path) for path in allowed_roots)
    target = resolve_write_target(entry.root_id, entry.path, roots, allowed)
    _reject_target_symlinks(roots[entry.root_id], entry.path)
    if target != approved_target:
        raise UnsafePathError(f"restore target changed after approval: {approved_target}")
    current = _safe_sha256(target)
    if current not in {entry.before_sha256, entry.after_sha256}:
        raise SourceChangedError(f"restore refused due to drift: {target}")


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
    _fsync_directory(path.parent)


def _write_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _write_fsynced_identity(path: Path, payload: bytes) -> tuple[int, int]:
    with path.open("xb") as output:
        stat = os.fstat(output.fileno())
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return stat.st_dev, stat.st_ino
