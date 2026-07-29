from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Iterable

from agent_workflow.adapters.base import AgentAdapter
from agent_workflow.model import normalize_relative_path, validate_sha256
from agent_workflow.plan import WriteOperation

from .model import ArtifactKind, ArtifactRecord
from .redaction import redact_text


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_KEY = re.compile(r"^[^\x00\r\n]+$")
_REDACTED = "<redacted>"
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "bearer_token",
        "cookie",
        "credential",
        "credentials",
        "http_headers",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_credential",
    "_key",
    "_password",
    "_secret",
    "_token",
)
_NATIVE_KINDS = frozenset(
    {
        ArtifactKind.SETTINGS,
        ArtifactKind.PERMISSIONS,
        ArtifactKind.HOOKS,
        ArtifactKind.MCP,
    }
)


class MappingStatus(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"
    SENSITIVE_SKIP = "sensitive_skip"


@dataclass(frozen=True)
class NativeMappingContext:
    target_adapter_id: str
    adapter_version: str

    def __post_init__(self) -> None:
        if _ADAPTER_ID.fullmatch(self.target_adapter_id) is None:
            raise ValueError("target adapter ID must be kebab-case")
        if (
            not isinstance(self.adapter_version, str)
            or not self.adapter_version
            or "\x00" in self.adapter_version
        ):
            raise ValueError("adapter version must be non-empty")


@dataclass(frozen=True)
class NativeMapping:
    source_key: str
    target_key: str | None
    status: MappingStatus
    normalized_value: object | None
    unmapped_fields: tuple[str, ...]
    credential_fields: tuple[str, ...]
    rationale: str
    adapter_version: str

    def __post_init__(self) -> None:
        if not _valid_key(self.source_key):
            raise ValueError("mapping source key is invalid")
        if self.target_key is not None and not _valid_key(self.target_key):
            raise ValueError("mapping target key is invalid")
        if not isinstance(self.status, MappingStatus):
            raise ValueError("mapping status is invalid")
        unmapped = _canonical_labels(
            self.unmapped_fields,
            preserve_order=True,
        )
        credentials = _canonical_labels(self.credential_fields)
        if (
            not isinstance(self.rationale, str)
            or not self.rationale
            or len(self.rationale) > 500
            or "\x00" in self.rationale
        ):
            raise ValueError("mapping rationale is invalid")
        if (
            not isinstance(self.adapter_version, str)
            or not self.adapter_version
            or "\x00" in self.adapter_version
        ):
            raise ValueError("mapping adapter version is invalid")
        try:
            json.dumps(self.normalized_value, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "mapping normalized value must be JSON-compatible"
            ) from error
        object.__setattr__(self, "unmapped_fields", unmapped)
        object.__setattr__(self, "credential_fields", credentials)

    def payload(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "target_key": self.target_key,
            "status": self.status.value,
            "normalized_value": self.normalized_value,
            "unmapped_fields": list(self.unmapped_fields),
            "credential_fields": list(self.credential_fields),
            "rationale": self.rationale,
            "adapter_version": self.adapter_version,
        }


@dataclass(frozen=True)
class MappedNativeArtifact:
    artifact_id: str
    source_agent_id: str
    target_agent_id: str
    source_relative_path: str
    mappings: tuple[NativeMapping, ...]
    write_operations: tuple[WriteOperation, ...] = ()

    def __post_init__(self) -> None:
        validate_sha256(self.artifact_id, field="mapped artifact ID")
        if _ADAPTER_ID.fullmatch(self.source_agent_id) is None:
            raise ValueError("source adapter ID must be kebab-case")
        if _ADAPTER_ID.fullmatch(self.target_agent_id) is None:
            raise ValueError("target adapter ID must be kebab-case")
        relative = normalize_relative_path(self.source_relative_path)
        if not self.mappings:
            raise ValueError("mapped artifact must contain a mapping")
        object.__setattr__(self, "source_relative_path", relative)

    @property
    def status(self) -> MappingStatus:
        statuses = {mapping.status for mapping in self.mappings}
        for status in (
            MappingStatus.UNSUPPORTED,
            MappingStatus.MANUAL,
            MappingStatus.SENSITIVE_SKIP,
            MappingStatus.PARTIAL,
            MappingStatus.EXACT,
        ):
            if status in statuses:
                return status
        raise AssertionError("mapped artifact has no status")

    @property
    def unmapped(self) -> tuple[str, ...]:
        output: list[str] = []
        for mapping in self.mappings:
            output.extend(mapping.unmapped_fields)
        return tuple(dict.fromkeys(output))

    @property
    def credential_fields(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    field
                    for mapping in self.mappings
                    for field in mapping.credential_fields
                }
            )
        )

    @property
    def source_file_required(self) -> bool:
        return any(
            mapping.status
            in {
                MappingStatus.MANUAL,
                MappingStatus.UNSUPPORTED,
                MappingStatus.SENSITIVE_SKIP,
            }
            for mapping in self.mappings
        )

    def payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "source_relative_path": self.source_relative_path,
            "status": self.status.value,
            "source_file_required": self.source_file_required,
            "mappings": [mapping.payload() for mapping in self.mappings],
            "write_operations": [
                {
                    "root_id": operation.root_id,
                    "path": operation.path,
                }
                for operation in self.write_operations
            ],
        }

    def serialized_preview(self) -> str:
        return json.dumps(
            self.payload(),
            indent=2,
            sort_keys=True,
        ) + "\n"


def map_native_artifacts(
    records: Iterable[ArtifactRecord],
    source_adapter: AgentAdapter,
    target_adapters: Iterable[AgentAdapter],
) -> tuple[MappedNativeArtifact, ...]:
    source_id = source_adapter.id
    mapper = getattr(source_adapter, "map_native_artifact", None)
    if not callable(mapper):
        raise ValueError(
            f"source adapter has no native mapping support: {source_id}"
        )
    targets = tuple(
        sorted(target_adapters, key=lambda adapter: adapter.id)
    )
    output: list[MappedNativeArtifact] = []
    for record in sorted(
        records,
        key=lambda item: (
            item.scope.value,
            item.relative_path,
            item.artifact_id,
        ),
    ):
        if record.agent_id != source_id:
            raise ValueError(
                "native artifact does not belong to source adapter"
            )
        if record.kind not in _NATIVE_KINDS:
            continue
        safe_content, blocked_reason = _load_safe_content(record)
        safe_content = _wrap_native_content(
            record,
            safe_content,
        )
        for target in targets:
            if target.id == source_id:
                continue
            context = NativeMappingContext(
                target_adapter_id=target.id,
                adapter_version=_adapter_version(target),
            )
            if blocked_reason is not None:
                output.append(
                    _sensitive_skip(record, context, blocked_reason)
                )
                continue
            output.append(
                mapper(record, safe_content, context)
            )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.source_relative_path,
                item.source_agent_id,
                item.target_agent_id,
                item.artifact_id,
            ),
        )
    )


def mapping_groups(
    results: Iterable[MappedNativeArtifact],
) -> dict[MappingStatus, tuple[NativeMapping, ...]]:
    grouped: dict[MappingStatus, list[NativeMapping]] = {
        status: [] for status in MappingStatus
    }
    for result in results:
        for mapping in result.mappings:
            grouped[mapping.status].append(mapping)
    return {
        status: tuple(
            sorted(
                items,
                key=lambda item: (
                    item.source_key,
                    item.target_key or "",
                    item.adapter_version,
                ),
            )
        )
        for status, items in grouped.items()
    }


def _load_safe_content(
    record: ArtifactRecord,
) -> tuple[object | None, str | None]:
    if not record.path.is_file() or record.path.is_symlink():
        raise ValueError("native artifact must be a safe regular file")
    try:
        content = record.path.read_bytes()
    except OSError as error:
        raise ValueError("native artifact is unreadable") from error
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError(
            f"native artifact changed after inventory: {record.relative_path}"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, "native artifact is not UTF-8"
    blocked = redact_text(text)
    if blocked.blocked:
        return None, ", ".join(blocked.reasons)
    try:
        if record.media_type == "application/json":
            parsed = json.loads(text)
        elif record.media_type == "application/toml":
            parsed = tomllib.loads(text)
        else:
            return None, "native artifact format is unsupported"
    except (json.JSONDecodeError, tomllib.TOMLDecodeError):
        return None, "native artifact syntax is invalid"
    return _sanitize(parsed), None


def _wrap_native_content(
    record: ArtifactRecord,
    safe_content: object | None,
) -> object | None:
    if safe_content is None or record.kind is ArtifactKind.SETTINGS:
        return safe_content
    key = {
        ArtifactKind.PERMISSIONS: "permissions",
        ArtifactKind.HOOKS: "hooks",
        ArtifactKind.MCP: (
            "mcpServers"
            if record.agent_id == "claude"
            else "mcp_servers"
        ),
    }.get(record.kind)
    return {key: safe_content} if key is not None else safe_content


def _sanitize(
    value: object,
    *,
    parent_key: str | None = None,
) -> object:
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.casefold()
            if (
                parent_key in {"env", "headers", "http_headers"}
                or _sensitive_key(normalized)
            ):
                output[key] = _REDACTED
            else:
                output[key] = _sanitize(
                    child,
                    parent_key=normalized,
                )
        return output
    if isinstance(value, list):
        return [
            _sanitize(item, parent_key=parent_key)
            for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sensitive_key(key: str) -> bool:
    return key in _SENSITIVE_KEYS or key.endswith(_SENSITIVE_SUFFIXES)


def _sensitive_skip(
    record: ArtifactRecord,
    context: NativeMappingContext,
    reason: str,
) -> MappedNativeArtifact:
    return MappedNativeArtifact(
        artifact_id=record.artifact_id,
        source_agent_id=record.agent_id,
        target_agent_id=context.target_adapter_id,
        source_relative_path=record.relative_path,
        mappings=(
            NativeMapping(
                source_key=record.relative_path,
                target_key=None,
                status=MappingStatus.SENSITIVE_SKIP,
                normalized_value=None,
                unmapped_fields=(),
                credential_fields=(),
                rationale=reason,
                adapter_version=context.adapter_version,
            ),
        ),
    )


def _adapter_version(adapter: AgentAdapter) -> str:
    manifest = getattr(adapter, "manifest", None)
    schema_version = getattr(manifest, "schema_version", None)
    return (
        f"manifest-{schema_version}"
        if isinstance(schema_version, int)
        else "adapter-unknown"
    )


def _valid_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and _SAFE_KEY.fullmatch(value) is not None
    )


def _canonical_labels(
    values: tuple[str, ...],
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not _valid_key(value) for value in values
    ):
        raise ValueError("mapping labels are invalid")
    unique = tuple(dict.fromkeys(values))
    return unique if preserve_order else tuple(sorted(unique))
