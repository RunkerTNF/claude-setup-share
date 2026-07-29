from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agent_workflow.doctor import Diagnostic
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.plan import WriteOperation

if TYPE_CHECKING:
    from agent_workflow.migration.mappings import (
        MappedNativeArtifact,
        NativeMappingContext,
    )
    from agent_workflow.migration.model import ArtifactRecord


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AdapterCapability:
    name: str
    status: CapabilityStatus
    note: str = ""


@dataclass(frozen=True)
class AdapterDetection:
    adapter_id: str
    installed: bool
    executable: str | None
    version: str | None
    warning: str | None = None


@dataclass(frozen=True)
class InventoryRoot:
    kind: str
    scope: Scope
    path: Path
    recursive: bool
    include_globs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("inventory root kind must be non-empty")
        if not isinstance(self.scope, Scope):
            raise ValueError("inventory root scope must be valid")
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError("inventory root path must be absolute")
        if type(self.recursive) is not bool:
            raise ValueError("inventory root recursive must be boolean")
        globs = tuple(self.include_globs)
        if any(
            not isinstance(pattern, str)
            or not pattern
            or "\x00" in pattern
            or pattern.startswith(("/", "\\"))
            or ".." in pattern.replace("\\", "/").split("/")
            for pattern in globs
        ):
            raise ValueError("inventory root globs must be safe")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "include_globs", globs)


@dataclass(frozen=True)
class AdapterContext:
    home: Path
    project_root: Path | None
    neutral_root: Path
    scope: Scope
    profile: ProjectProfile | None
    generator_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            raise ValueError("adapter scope must be valid")
        if self.scope is Scope.GLOBAL and self.profile is not None:
            raise ValueError("global adapter context requires profile=None")
        if self.scope is Scope.PROJECT:
            if not isinstance(self.profile, ProjectProfile):
                raise ValueError("project adapter context requires a profile")
            if self.project_root is None:
                raise ValueError("project adapter context requires a project root")
        if not isinstance(self.generator_version, str) or not self.generator_version:
            raise ValueError("generator version must be non-empty")
        object.__setattr__(self, "home", Path(self.home))
        object.__setattr__(
            self,
            "project_root",
            Path(self.project_root) if self.project_root is not None else None,
        )
        object.__setattr__(self, "neutral_root", Path(self.neutral_root))


class AgentAdapter(Protocol):
    id: str

    def detect(self, context: AdapterContext) -> AdapterDetection:
        raise NotImplementedError

    def plan_entrypoints(
        self, context: AdapterContext
    ) -> tuple[WriteOperation, ...]:
        raise NotImplementedError

    def validate(self, context: AdapterContext) -> tuple[Diagnostic, ...]:
        raise NotImplementedError

    def inventory_roots(
        self, context: AdapterContext
    ) -> tuple[InventoryRoot, ...]:
        raise NotImplementedError

    def map_native_artifact(
        self,
        record: ArtifactRecord,
        safe_content: object,
        target_context: NativeMappingContext,
    ) -> MappedNativeArtifact:
        raise NotImplementedError
