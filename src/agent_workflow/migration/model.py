from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re

from agent_workflow.model import normalize_relative_path, validate_sha256


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ArtifactKind(StrEnum):
    RULES = "rules"
    MANUAL_MEMORY = "manual_memory"
    AUTO_MEMORY = "auto_memory"
    SESSION = "session"
    SKILL = "skill"
    COMMAND = "command"
    SUBAGENT_PROMPT = "subagent_prompt"
    SETTINGS = "settings"
    PERMISSIONS = "permissions"
    HOOKS = "hooks"
    MCP = "mcp"
    UNKNOWN = "unknown"


class ArtifactScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"


class Sensitivity(StrEnum):
    SAFE = "safe"
    REDACTED = "redacted"
    BLOCKED = "blocked"


def derive_artifact_id(
    *,
    agent_id: str,
    scope: ArtifactScope,
    relative_path: str,
    source_sha256: str,
) -> str:
    normalized = normalize_relative_path(relative_path)
    validate_sha256(source_sha256, field="source SHA-256")
    digest = hashlib.sha256()
    for value in (agent_id, scope.value, normalized, source_sha256):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    agent_id: str
    kind: ArtifactKind
    scope: ArtifactScope
    path: Path
    relative_path: str
    sha256: str
    media_type: str
    size_bytes: int
    sensitivity: Sensitivity
    already_neutral: bool

    def __post_init__(self) -> None:
        if _ADAPTER_ID.fullmatch(self.agent_id) is None:
            raise ValueError("artifact agent_id must be kebab-case")
        if not isinstance(self.kind, ArtifactKind):
            raise ValueError("artifact kind must be valid")
        if not isinstance(self.scope, ArtifactScope):
            raise ValueError("artifact scope must be valid")
        source_path = Path(self.path)
        if not source_path.is_absolute():
            raise ValueError("artifact path must be absolute")
        relative_path = normalize_relative_path(self.relative_path)
        validate_sha256(self.sha256, field="artifact SHA-256")
        validate_sha256(self.artifact_id, field="artifact ID")
        expected_id = derive_artifact_id(
            agent_id=self.agent_id,
            scope=self.scope,
            relative_path=relative_path,
            source_sha256=self.sha256,
        )
        if self.artifact_id != expected_id:
            raise ValueError("artifact ID does not match source identity")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("artifact media_type must be non-empty")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("artifact size_bytes must be non-negative")
        if not isinstance(self.sensitivity, Sensitivity):
            raise ValueError("artifact sensitivity must be valid")
        if type(self.already_neutral) is not bool:
            raise ValueError("artifact already_neutral must be boolean")
        object.__setattr__(self, "path", source_path)
        object.__setattr__(self, "relative_path", relative_path)

    def portable_payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "agent_id": self.agent_id,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sensitivity": self.sensitivity.value,
            "already_neutral": self.already_neutral,
        }


@dataclass(frozen=True)
class MigrationInventory:
    schema_version: int
    roots: tuple[str, ...]
    artifacts: tuple[ArtifactRecord, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported migration inventory schema version")
        roots = tuple(sorted(set(self.roots)))
        artifacts = tuple(
            sorted(
                self.artifacts,
                key=lambda item: (
                    item.scope.value,
                    item.agent_id,
                    item.relative_path,
                    item.artifact_id,
                ),
            )
        )
        identifiers = [item.artifact_id for item in artifacts]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("migration inventory contains duplicate artifact IDs")
        warnings = tuple(sorted(set(self.warnings)))
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "warnings", warnings)

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "roots": list(self.roots),
            "artifacts": [
                item.portable_payload() for item in self.artifacts
            ],
            "warnings": list(self.warnings),
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
