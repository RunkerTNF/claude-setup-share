from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import ntpath
import posixpath
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Mapping, TypeAlias
from uuid import NAMESPACE_URL, UUID, uuid5

from .model import Ownership, ROOT_IDS, normalize_relative_path, validate_sha256


_PLAN_KEYS = frozenset(
    {
        "schema_version",
        "plan_id",
        "scope_root",
        "target_roots",
        "allowed_roots",
        "operations",
        "conflicts",
        "warnings",
    }
)
_WRITE_KEYS = frozenset({"kind", "root_id", "path", "content_b64", "expected_sha256", "ownership"})
_DELETE_KEYS = frozenset({"kind", "root_id", "path", "expected_sha256", "ownership"})
_PLAN_ID_SENTINEL = "00000000-0000-0000-0000-000000000000"


def _validate_operation_fields(root_id: str, path: str, expected_sha256: str | None, ownership: Ownership) -> tuple[str, str]:
    if root_id not in ROOT_IDS:
        raise ValueError(f"unknown root ID: {root_id}")
    if expected_sha256 is not None:
        validate_sha256(expected_sha256)
    if not isinstance(ownership, Ownership):
        raise ValueError("ownership must be valid")
    return root_id, normalize_relative_path(path)


@dataclass(frozen=True)
class WriteOperation:
    root_id: str
    path: str
    content_b64: str
    expected_sha256: str | None
    ownership: Ownership

    def __post_init__(self) -> None:
        root_id, path = _validate_operation_fields(self.root_id, self.path, self.expected_sha256, self.ownership)
        if not isinstance(self.content_b64, str):
            raise ValueError("content_b64 must be a string")
        try:
            base64.b64decode(self.content_b64, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("content_b64 must be valid base64") from error
        object.__setattr__(self, "root_id", root_id)
        object.__setattr__(self, "path", path)

    @classmethod
    def from_bytes(
        cls,
        root_id: str,
        path: str,
        content: bytes,
        expected_sha256: str | None,
        ownership: Ownership,
    ) -> "WriteOperation":
        if not isinstance(content, bytes):
            raise ValueError("content must be bytes")
        return cls(
            root_id=root_id,
            path=path,
            content_b64=base64.b64encode(content).decode("ascii"),
            expected_sha256=expected_sha256,
            ownership=ownership,
        )

    def content_bytes(self) -> bytes:
        return base64.b64decode(self.content_b64, validate=True)


@dataclass(frozen=True)
class DeleteOperation:
    root_id: str
    path: str
    expected_sha256: str
    ownership: Ownership

    def __post_init__(self) -> None:
        if self.expected_sha256 is None:
            raise ValueError("delete operation requires an expected SHA-256")
        root_id, path = _validate_operation_fields(self.root_id, self.path, self.expected_sha256, self.ownership)
        object.__setattr__(self, "root_id", root_id)
        object.__setattr__(self, "path", path)


FileOperation: TypeAlias = WriteOperation | DeleteOperation


def _uses_windows_path(path: str) -> bool:
    return "\\" in path or bool(PureWindowsPath(path).drive)


def _normalize_absolute_path(path: str) -> tuple[bool, str]:
    if not isinstance(path, str) or not path:
        raise ValueError("root paths must be non-empty absolute paths")
    if _uses_windows_path(path):
        candidate = PureWindowsPath(path)
        if not candidate.is_absolute():
            raise ValueError("root paths must be non-empty absolute paths")
        return True, ntpath.normpath(str(candidate)).casefold()
    candidate = PurePosixPath(path)
    if not candidate.is_absolute():
        raise ValueError("root paths must be non-empty absolute paths")
    return False, posixpath.normpath(str(candidate))


def _is_contained(path: str, allowed_root: str) -> bool:
    path_is_windows, normalized_path = _normalize_absolute_path(path)
    root_is_windows, normalized_root = _normalize_absolute_path(allowed_root)
    if path_is_windows != root_is_windows:
        return False
    if path_is_windows:
        try:
            PureWindowsPath(normalized_path).relative_to(PureWindowsPath(normalized_root))
        except ValueError:
            return False
    else:
        try:
            PurePosixPath(normalized_path).relative_to(PurePosixPath(normalized_root))
        except ValueError:
            return False
    return True


def _resolved_target(root: str, relative_path: str) -> str:
    is_windows, normalized_root = _normalize_absolute_path(root)
    if is_windows:
        return ntpath.normpath(ntpath.join(normalized_root, relative_path.replace("/", "\\"))).casefold()
    return posixpath.normpath(posixpath.join(normalized_root, relative_path))


@dataclass(frozen=True)
class TransactionPlan:
    schema_version: int
    plan_id: str
    scope_root: str
    target_roots: Mapping[str, str]
    allowed_roots: tuple[str, ...]
    operations: tuple[FileOperation, ...]
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_roots", MappingProxyType(dict(self.target_roots)))
        object.__setattr__(self, "allowed_roots", tuple(self.allowed_roots))
        object.__setattr__(self, "operations", tuple(sorted(self.operations, key=_operation_sort_key)))
        object.__setattr__(self, "conflicts", tuple(self.conflicts))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        self._validate_contents()
        derived_plan_id = self._derived_plan_id()
        if self.plan_id == _PLAN_ID_SENTINEL:
            object.__setattr__(self, "plan_id", derived_plan_id)
        else:
            self._validate_plan_id(derived_plan_id)

    @classmethod
    def new(
        cls,
        *,
        scope_root: str,
        target_roots: Mapping[str, str],
        allowed_roots: tuple[str, ...],
        operations: tuple[FileOperation, ...],
        conflicts: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> "TransactionPlan":
        return cls(
            schema_version=1,
            plan_id=_PLAN_ID_SENTINEL,
            scope_root=scope_root,
            target_roots=target_roots,
            allowed_roots=allowed_roots,
            operations=operations,
            conflicts=conflicts,
            warnings=warnings,
        )

    def validate(self) -> None:
        self._validate_contents()
        self._validate_plan_id(self._derived_plan_id())

    def _validate_plan_id(self, derived_plan_id: str) -> None:
        try:
            UUID(self.plan_id)
        except (TypeError, ValueError) as error:
            raise ValueError("plan_id must be a UUID") from error
        if self.plan_id != derived_plan_id:
            raise ValueError("plan_id does not match plan content")

    def _validate_contents(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        if set(self.target_roots) != ROOT_IDS:
            raise ValueError("target_roots must contain exactly neutral and scope")
        if not self.allowed_roots:
            raise ValueError("allowed_roots must not be empty")
        _normalize_absolute_path(self.scope_root)
        for target_root in self.target_roots.values():
            if not isinstance(target_root, str) or not any(_is_contained(target_root, root) for root in self.allowed_roots):
                raise ValueError("target root is outside allowed roots")
        if not any(_is_contained(self.scope_root, root) for root in self.allowed_roots):
            raise ValueError("scope root is outside allowed roots")
        if any(not isinstance(item, str) for item in (*self.conflicts, *self.warnings)):
            raise ValueError("conflicts and warnings must contain strings")

        resolved_targets: set[str] = set()
        for operation in self.operations:
            if not isinstance(operation, (WriteOperation, DeleteOperation)):
                raise ValueError("operations must be file operations")
            resolved = _resolved_target(self.target_roots[operation.root_id], operation.path)
            if resolved in resolved_targets:
                raise ValueError("duplicate resolved target path")
            resolved_targets.add(resolved)

    def _canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope_root": self.scope_root,
            "target_roots": dict(self.target_roots),
            "allowed_roots": list(self.allowed_roots),
            "operations": [_operation_to_payload(operation) for operation in self.operations],
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
        }

    def _derived_plan_id(self) -> str:
        canonical = json.dumps(self._canonical_payload(), sort_keys=True, separators=(",", ":"))
        return str(uuid5(NAMESPACE_URL, canonical))

    def to_json(self) -> str:
        self.validate()
        payload = {"plan_id": self.plan_id, **self._canonical_payload()}
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "TransactionPlan":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid plan JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("plan JSON must be an object")
        unknown = set(payload) - _PLAN_KEYS
        missing = _PLAN_KEYS - set(payload)
        if unknown:
            raise ValueError(f"unknown plan keys: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing plan keys: {sorted(missing)}")
        if not isinstance(payload["target_roots"], dict) or not isinstance(payload["allowed_roots"], list):
            raise ValueError("plan roots must have the expected JSON types")
        if not isinstance(payload["operations"], list) or not isinstance(payload["conflicts"], list) or not isinstance(payload["warnings"], list):
            raise ValueError("plan collections must have the expected JSON types")
        if payload["plan_id"] == _PLAN_ID_SENTINEL:
            raise ValueError("plan_id uses an internal derivation sentinel")
        try:
            plan = cls(
                schema_version=payload["schema_version"],
                plan_id=payload["plan_id"],
                scope_root=payload["scope_root"],
                target_roots=payload["target_roots"],
                allowed_roots=tuple(payload["allowed_roots"]),
                operations=tuple(_operation_from_payload(item) for item in payload["operations"]),
                conflicts=tuple(payload["conflicts"]),
                warnings=tuple(payload["warnings"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid plan: {error}") from error
        if plan.plan_id != plan._derived_plan_id():
            raise ValueError("plan_id does not match plan content")
        return plan


def _operation_sort_key(operation: FileOperation) -> tuple[str, str, str]:
    return (operation.root_id, operation.path, "write" if isinstance(operation, WriteOperation) else "delete")


def _operation_to_payload(operation: FileOperation) -> dict[str, str | None]:
    if isinstance(operation, WriteOperation):
        return {
            "kind": "write",
            "root_id": operation.root_id,
            "path": operation.path,
            "content_b64": operation.content_b64,
            "expected_sha256": operation.expected_sha256,
            "ownership": operation.ownership.value,
        }
    return {
        "kind": "delete",
        "root_id": operation.root_id,
        "path": operation.path,
        "expected_sha256": operation.expected_sha256,
        "ownership": operation.ownership.value,
    }


def _operation_from_payload(payload: object) -> FileOperation:
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        raise ValueError("operation must have a kind")
    kind = payload["kind"]
    expected_keys = _WRITE_KEYS if kind == "write" else _DELETE_KEYS if kind == "delete" else None
    if expected_keys is None:
        raise ValueError(f"unknown operation kind: {kind}")
    unknown = set(payload) - expected_keys
    missing = expected_keys - set(payload)
    if unknown:
        raise ValueError(f"unknown operation keys: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing operation keys: {sorted(missing)}")
    ownership = Ownership(payload["ownership"])
    if kind == "write":
        return WriteOperation(
            root_id=payload["root_id"],
            path=payload["path"],
            content_b64=payload["content_b64"],
            expected_sha256=payload["expected_sha256"],
            ownership=ownership,
        )
    return DeleteOperation(
        root_id=payload["root_id"],
        path=payload["path"],
        expected_sha256=payload["expected_sha256"],
        ownership=ownership,
    )
