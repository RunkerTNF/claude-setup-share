from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Iterable

from agent_workflow.errors import BackupError
from agent_workflow.hashing import sha256_bytes
from agent_workflow.model import ROOT_IDS, normalize_relative_path, validate_sha256


_INVENTORY_KEYS = frozenset({"schema_version", "entries"})
_INVENTORY_ENTRY_KEYS = frozenset({"root_id", "path", "existed", "sha256", "backup_path"})


@dataclass(frozen=True)
class BackupSource:
    root_id: str
    path: str
    target: Path
    existed: bool
    sha256: str | None


@dataclass(frozen=True)
class BackupInventoryEntry:
    root_id: str
    path: str
    existed: bool
    sha256: str | None
    backup_path: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "path": self.path,
            "existed": self.existed,
            "sha256": self.sha256,
            "backup_path": self.backup_path,
        }


def create_backup(backup_root: Path, sources: Iterable[BackupSource]) -> tuple[tuple[BackupInventoryEntry, ...], tuple[str, ...]]:
    if backup_root.exists() or backup_root.is_symlink():
        raise BackupError(f"backup location already exists or is unsafe: {backup_root}")
    warnings: list[str] = []
    try:
        backup_root.mkdir(parents=False)
        _request_private_mode(backup_root, warnings)
        files_root = backup_root / "files"
        files_root.mkdir()
        _request_private_mode(files_root, warnings)
        inventory: list[BackupInventoryEntry] = []
        for source in sources:
            if source.existed != (source.sha256 is not None):
                raise BackupError("backup source existence and hash disagree")
            backup_path: str | None = None
            if source.existed:
                payload = source.target.read_bytes()
                if sha256_bytes(payload) != source.sha256:
                    raise BackupError(f"source changed while backing up: {source.target}")
                destination = files_root / source.root_id / Path(*source.path.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                _write_fsynced(destination, payload)
                _request_private_mode(destination, warnings)
                backup_path = str(destination.relative_to(backup_root)).replace("\\", "/")
            inventory.append(
                BackupInventoryEntry(source.root_id, source.path, source.existed, source.sha256, backup_path)
            )
        inventory = sorted(inventory, key=lambda entry: (entry.root_id, entry.path))
        _write_inventory(backup_root / "inventory.json", inventory)
        _request_private_mode(backup_root / "inventory.json", warnings)
    except (OSError, ValueError) as error:
        raise BackupError(f"unable to create backup: {error}") from error
    return tuple(inventory), tuple(warnings)


def verify_backup(backup_root: Path, sources: Iterable[BackupSource]) -> tuple[BackupInventoryEntry, ...]:
    expected = tuple(sorted(sources, key=lambda source: (source.root_id, source.path)))
    inventory = _read_inventory(backup_root / "inventory.json")
    if len(expected) != len(inventory):
        raise BackupError("backup inventory does not match transaction")
    for source, entry in zip(expected, inventory, strict=True):
        if (source.root_id, source.path, source.existed, source.sha256) != (
            entry.root_id,
            entry.path,
            entry.existed,
            entry.sha256,
        ):
            raise BackupError("backup inventory does not match transaction")
        if entry.existed:
            if entry.backup_path is None:
                raise BackupError("backup inventory omits payload path")
            backup_file = _backup_payload_path(backup_root, entry)
            try:
                payload = backup_file.read_bytes()
            except OSError as error:
                raise BackupError(f"cannot read backup payload: {backup_file}") from error
            if sha256_bytes(payload) != entry.sha256:
                raise BackupError(f"backup payload hash mismatch: {backup_file}")
        elif entry.backup_path is not None:
            raise BackupError("absent backup entry has a payload")
    return inventory


def read_verified_payload(backup_root: Path, entry: BackupInventoryEntry) -> bytes:
    if not entry.existed or entry.backup_path is None:
        raise BackupError("absent backup entry has no payload")
    payload_path = _backup_payload_path(backup_root, entry)
    try:
        payload = payload_path.read_bytes()
    except OSError as error:
        raise BackupError(f"cannot read backup payload: {payload_path}") from error
    if sha256_bytes(payload) != entry.sha256:
        raise BackupError(f"backup payload hash mismatch: {payload_path}")
    return payload


def _read_inventory(path: Path) -> tuple[BackupInventoryEntry, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackupError("invalid backup inventory") from error
    if not isinstance(payload, dict) or set(payload) != _INVENTORY_KEYS or payload.get("schema_version") != 1:
        raise BackupError("invalid backup inventory")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise BackupError("invalid backup inventory")
    parsed: list[BackupInventoryEntry] = []
    for item in entries:
        if not isinstance(item, dict) or set(item) != _INVENTORY_ENTRY_KEYS:
            raise BackupError("invalid backup inventory entry")
        root_id = item["root_id"]
        path_value = item["path"]
        existed = item["existed"]
        sha256 = item["sha256"]
        backup_path = item["backup_path"]
        if root_id not in ROOT_IDS or type(existed) is not bool:
            raise BackupError("invalid backup inventory entry")
        try:
            path_value = normalize_relative_path(path_value)
            if sha256 is not None:
                validate_sha256(sha256)
        except ValueError as error:
            raise BackupError("invalid backup inventory entry") from error
        if existed != (sha256 is not None) or (backup_path is None) != (not existed):
            raise BackupError("invalid backup inventory entry")
        if backup_path is not None and not isinstance(backup_path, str):
            raise BackupError("invalid backup inventory entry")
        parsed.append(BackupInventoryEntry(root_id, path_value, existed, sha256, backup_path))
    result = tuple(parsed)
    if result != tuple(sorted(result, key=lambda entry: (entry.root_id, entry.path))):
        raise BackupError("backup inventory ordering is invalid")
    if len({(entry.root_id, entry.path) for entry in result}) != len(result):
        raise BackupError("backup inventory duplicates a target")
    return result


def _backup_payload_path(backup_root: Path, entry: BackupInventoryEntry) -> Path:
    expected = Path("files") / entry.root_id / Path(*entry.path.split("/"))
    if entry.backup_path != str(expected).replace("\\", "/"):
        raise BackupError("backup payload path is invalid")
    logical_candidate = backup_root / expected
    current = backup_root
    for part in expected.parts:
        current /= part
        if current.is_symlink():
            raise BackupError("backup payload path contains a symlink")
    candidate = logical_candidate.resolve(strict=False)
    files_root = (backup_root / "files").resolve(strict=False)
    try:
        candidate.relative_to(files_root)
    except ValueError as error:
        raise BackupError("backup payload escapes backup root") from error
    if candidate.is_symlink():
        raise BackupError("backup payload is a symlink")
    return candidate


def _write_inventory(path: Path, entries: list[BackupInventoryEntry]) -> None:
    raw = json.dumps(
        {"schema_version": 1, "entries": [entry.to_payload() for entry in entries]},
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    _write_fsynced(path, raw)


def _write_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _request_private_mode(path: Path, warnings: list[str]) -> None:
    if os.name == "nt":
        warnings.append(f"could not verify user-only backup permissions on Windows: {path}")
        return
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
        if stat.S_IMODE(path.stat().st_mode) != (0o700 if path.is_dir() else 0o600):
            warnings.append(f"could not verify user-only backup permissions: {path}")
    except OSError:
        warnings.append(f"could not set user-only backup permissions: {path}")
