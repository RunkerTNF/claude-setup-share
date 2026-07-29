from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from agent_workflow.doctor import Diagnostic, run_doctor
from agent_workflow.errors import ConflictError, SourceChangedError
from agent_workflow.model import Severity
from agent_workflow.transactions import (
    TransactionJournal,
    apply_plan,
    rollback_transaction,
)

from .planner import MigrationPlanResult, MigrationSourceFile


@dataclass(frozen=True)
class MigrationApplyResult:
    import_journal: TransactionJournal | None
    replacement_journal: TransactionJournal | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def backup_locations(self) -> tuple[str, ...]:
        return tuple(
            journal.backup_root
            for journal in (
                self.import_journal,
                self.replacement_journal,
            )
            if journal is not None
        )

    @property
    def rollback_locations(self) -> tuple[str, ...]:
        return tuple(
            journal.journal_path
            for journal in (
                self.import_journal,
                self.replacement_journal,
            )
            if journal is not None
        )


def apply_migration(
    result: MigrationPlanResult,
    *,
    confirm_replacement: bool = False,
) -> MigrationApplyResult:
    if result.import_plan.conflicts:
        raise ConflictError(
            "migration import plan contains blocking conflicts"
        )
    replacement = result.source_replacement_plan
    if result.options.replace_native and replacement is None:
        raise ConflictError(
            "native replacement is blocked by unresolved migration state"
        )
    if (
        replacement is not None
        and replacement.operations
        and not confirm_replacement
    ):
        raise ConflictError(
            "native replacement requires explicit confirmation"
        )
    _verify_sources(result.source_files)
    import_journal = (
        apply_plan(result.import_plan)
        if result.import_plan.operations
        else None
    )
    diagnostics = run_doctor(result.options.neutral_root)
    blocking = tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.severity is Severity.BLOCKING
    )
    if blocking:
        if import_journal is not None:
            rollback_transaction(Path(import_journal.journal_path))
        raise ConflictError(
            "doctor failed after migration import: "
            + "; ".join(
                f"{item.code}:{item.path}" for item in blocking
            )
        )

    replacement_journal = None
    if replacement is not None and replacement.operations:
        _verify_sources(result.source_files)
        replacement_journal = apply_plan(replacement)
        diagnostics = run_doctor(result.options.neutral_root)
        blocking = tuple(
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.severity is Severity.BLOCKING
        )
        if blocking:
            rollback_transaction(
                Path(replacement_journal.journal_path)
            )
            raise ConflictError(
                "doctor failed after native replacement; legacy "
                "sources were restored: "
                + "; ".join(
                    f"{item.code}:{item.path}"
                    for item in blocking
                )
            )
    return MigrationApplyResult(
        import_journal=import_journal,
        replacement_journal=replacement_journal,
        diagnostics=diagnostics,
    )


def _verify_sources(
    sources: tuple[MigrationSourceFile, ...],
) -> None:
    for source in sources:
        actual = _source_hash(source)
        if actual != source.source_sha256:
            raise SourceChangedError(
                "migration source changed after preview: "
                f"{source.relative_path}"
            )


def _source_hash(source: MigrationSourceFile) -> str:
    path = source.path
    if source.is_directory:
        if not path.is_dir() or path.is_symlink():
            raise SourceChangedError(
                f"migration source directory is missing: {source.relative_path}"
            )
        digest = hashlib.sha256()
        try:
            entries = sorted(
                path.rglob("*"),
                key=lambda item: item.relative_to(path).as_posix(),
            )
            for entry in entries:
                if entry.is_symlink():
                    raise SourceChangedError(
                        "migration source contains a symlink: "
                        f"{source.relative_path}"
                    )
                if entry.is_dir():
                    continue
                if not entry.is_file():
                    raise SourceChangedError(
                        "migration source contains an unsafe entry: "
                        f"{source.relative_path}"
                    )
                content = entry.read_bytes()
                digest.update(
                    entry.relative_to(path).as_posix().encode("utf-8")
                )
                digest.update(b"\0")
                digest.update(content)
                digest.update(b"\0")
        except OSError as error:
            raise SourceChangedError(
                f"migration source cannot be hashed: {source.relative_path}"
            ) from error
        return digest.hexdigest()
    if not path.is_file() or path.is_symlink():
        raise SourceChangedError(
            f"migration source file is missing: {source.relative_path}"
        )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise SourceChangedError(
            f"migration source cannot be hashed: {source.relative_path}"
        ) from error
