from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from agent_workflow.model import ROOT_IDS, normalize_relative_path, validate_sha256


_JOURNAL_KEYS = frozenset(
    {
        "schema_version",
        "transaction_id",
        "created_at",
        "scope_root",
        "target_roots",
        "allowed_roots",
        "status",
        "entries",
        "backup_root",
        "journal_path",
        "warnings",
    }
)
_ENTRY_KEYS = frozenset({"root_id", "path", "operation_kind", "existed", "before_sha256", "after_sha256"})
_STATUSES = frozenset({"prepared", "committing", "committed", "rolled_back"})


def _absolute_path(value: str, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    return path.resolve(strict=False)


@dataclass(frozen=True)
class JournalEntry:
    root_id: str
    path: str
    operation_kind: str
    existed: bool
    before_sha256: str | None
    after_sha256: str | None

    def __post_init__(self) -> None:
        if self.root_id not in ROOT_IDS:
            raise ValueError(f"unknown root ID: {self.root_id}")
        object.__setattr__(self, "path", normalize_relative_path(self.path))
        if self.operation_kind not in {"write", "delete"}:
            raise ValueError("operation_kind must be write or delete")
        if type(self.existed) is not bool:
            raise ValueError("existed must be a boolean")
        for field, value in (("before_sha256", self.before_sha256), ("after_sha256", self.after_sha256)):
            if value is not None:
                validate_sha256(value, field=field)
        if self.existed != (self.before_sha256 is not None):
            raise ValueError("existed and before_sha256 disagree")
        if self.operation_kind == "write" and self.after_sha256 is None:
            raise ValueError("write journal entry requires after_sha256")
        if self.operation_kind == "delete" and self.after_sha256 is not None:
            raise ValueError("delete journal entry requires absent after_sha256")

    def to_payload(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "path": self.path,
            "operation_kind": self.operation_kind,
            "existed": self.existed,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "JournalEntry":
        if not isinstance(payload, dict):
            raise ValueError("journal entry must be an object")
        unknown = set(payload) - _ENTRY_KEYS
        missing = _ENTRY_KEYS - set(payload)
        if unknown or missing:
            raise ValueError("journal entry has unexpected keys")
        return cls(**payload)


@dataclass(frozen=True)
class TransactionJournal:
    schema_version: int
    transaction_id: str
    scope_root: str
    target_roots: Mapping[str, str]
    allowed_roots: tuple[str, ...]
    status: str
    entries: tuple[JournalEntry, ...]
    backup_root: str
    journal_path: str
    created_at: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported journal schema version")
        try:
            UUID(self.transaction_id)
        except (TypeError, ValueError) as error:
            raise ValueError("transaction_id must be a UUID") from error
        if not isinstance(self.created_at, str) or not self.created_at.endswith("Z"):
            raise ValueError("created_at must be a UTC ISO timestamp")
        try:
            parsed_created_at = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("created_at must be a UTC ISO timestamp") from error
        if parsed_created_at.tzinfo != timezone.utc:
            raise ValueError("created_at must be a UTC ISO timestamp")
        scope_root = _absolute_path(self.scope_root, "scope_root")
        roots = dict(self.target_roots)
        if set(roots) != ROOT_IDS or not all(isinstance(value, str) for value in roots.values()):
            raise ValueError("target_roots must contain neutral and scope")
        normalized_roots = {root_id: str(_absolute_path(value, "target root")) for root_id, value in roots.items()}
        allowed = tuple(str(_absolute_path(value, "allowed root")) for value in self.allowed_roots)
        if not allowed:
            raise ValueError("allowed_roots must not be empty")
        if self.status not in _STATUSES:
            raise ValueError("invalid journal status")
        entries = tuple(self.entries)
        if not all(isinstance(entry, JournalEntry) for entry in entries):
            raise ValueError("entries must be journal entries")
        if entries != tuple(sorted(entries, key=lambda entry: (entry.root_id, entry.path, entry.operation_kind))):
            raise ValueError("journal entries must be deterministic")
        if len({(entry.root_id, entry.path) for entry in entries}) != len(entries):
            raise ValueError("journal entries must not duplicate targets")
        expected_backup = scope_root / "workflow" / "backups" / self.transaction_id
        expected_journal = scope_root / "workflow" / "journals" / f"{self.transaction_id}.json"
        backup_root = _absolute_path(self.backup_root, "backup_root")
        journal_path = _absolute_path(self.journal_path, "journal_path")
        if backup_root != expected_backup.resolve(strict=False):
            raise ValueError("backup_root is not the transaction backup location")
        if journal_path != expected_journal.resolve(strict=False):
            raise ValueError("journal_path is not the transaction journal location")
        if not all(isinstance(item, str) for item in self.warnings):
            raise ValueError("warnings must contain strings")
        object.__setattr__(self, "scope_root", str(scope_root))
        object.__setattr__(self, "target_roots", MappingProxyType(normalized_roots))
        object.__setattr__(self, "allowed_roots", allowed)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "backup_root", str(backup_root))
        object.__setattr__(self, "journal_path", str(journal_path))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "transaction_id": self.transaction_id,
            "created_at": self.created_at,
            "scope_root": self.scope_root,
            "target_roots": dict(self.target_roots),
            "allowed_roots": list(self.allowed_roots),
            "status": self.status,
            "entries": [entry.to_payload() for entry in self.entries],
            "backup_root": self.backup_root,
            "journal_path": self.journal_path,
            "warnings": list(self.warnings),
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "TransactionJournal":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid journal JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("journal must be an object")
        unknown = set(payload) - _JOURNAL_KEYS
        missing = _JOURNAL_KEYS - set(payload)
        if unknown or missing:
            raise ValueError("journal has unexpected keys")
        entries_value = payload.pop("entries")
        if not isinstance(entries_value, list):
            raise ValueError("entries must be a list")
        payload["entries"] = tuple(JournalEntry.from_payload(item) for item in entries_value)
        if not isinstance(payload["target_roots"], dict) or not isinstance(payload["allowed_roots"], list):
            raise ValueError("journal roots are invalid")
        if not isinstance(payload["warnings"], list):
            raise ValueError("warnings must be a list")
        payload["allowed_roots"] = tuple(payload["allowed_roots"])
        payload["warnings"] = tuple(payload["warnings"])
        return cls(**payload)

    def with_status(self, status: str) -> "TransactionJournal":
        return replace(self, status=status)
