from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Iterable

from agent_workflow import __version__
from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.registry import builtin_registry
from agent_workflow.hashing import sha256_file
from agent_workflow.manifest import WorkflowManifest
from agent_workflow.model import (
    Ownership,
    ProjectProfile,
    Scope,
    normalize_relative_path,
    validate_sha256,
)
from agent_workflow.plan import (
    DeleteOperation,
    TransactionPlan,
    WriteOperation,
)

from .classification import (
    ClassificationDecision,
    ClassificationResponse,
    DecisionKind,
)
from .mappings import (
    MappedNativeArtifact,
    MappingStatus,
)
from .model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    MigrationInventory,
    derive_artifact_id,
)
from .normalize import (
    ArtifactProvenance,
    NormalizationBatch,
    NormalizedArtifact,
    merge_memory_index,
    normalize_deterministic,
    resolve_normalized_collisions,
)
from .redaction import redact_artifact, redact_json, redact_text
from .report import MigrationReport


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PORTABLE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPLACEMENT_KEYS = frozenset(
    {
        "replacement_sha256",
        "scope",
        "source_agent",
        "source_relative_path",
        "source_sha256",
    }
)
_RESULT_KEYS = {
    "schema_version",
    "inventory_sha256",
    "classification_sha256",
    "normalized_sha256",
    "options",
    "source_files",
    "import_plan",
    "source_replacement_plan",
    "blocking_conflicts",
    "report",
}


@dataclass(frozen=True)
class MigrationOptions:
    home: Path
    project_root: Path | None
    scope: Scope
    profile: ProjectProfile | None
    targets: tuple[str, ...]
    replace_native: bool
    imported_at: str
    include_native_cache: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            raise ValueError("migration scope must be valid")
        if self.scope is Scope.GLOBAL:
            if self.project_root is not None or self.profile is not None:
                raise ValueError(
                    "global migration requires no project root or profile"
                )
        elif (
            self.project_root is None
            or not isinstance(self.profile, ProjectProfile)
        ):
            raise ValueError(
                "project migration requires a root and profile"
            )
        home = _safe_directory(self.home, "home")
        project = (
            _safe_directory(self.project_root, "project root")
            if self.project_root is not None
            else None
        )
        targets = tuple(sorted(set(self.targets)))
        if any(
            not isinstance(target, str)
            or _ADAPTER_ID.fullmatch(target) is None
            for target in targets
        ):
            raise ValueError("migration targets must be adapter IDs")
        if type(self.replace_native) is not bool:
            raise ValueError("replace_native must be boolean")
        if type(self.include_native_cache) is not bool:
            raise ValueError("include_native_cache must be boolean")
        if (
            not isinstance(self.imported_at, str)
            or not self.imported_at
            or any(
                character in self.imported_at
                for character in ("\x00", "\r", "\n")
            )
        ):
            raise ValueError("migration import timestamp is invalid")
        object.__setattr__(self, "home", home)
        object.__setattr__(self, "project_root", project)
        object.__setattr__(self, "targets", targets)

    @property
    def scope_base(self) -> Path:
        if self.scope is Scope.GLOBAL:
            return self.home
        assert self.project_root is not None
        return self.project_root

    @property
    def neutral_root(self) -> Path:
        return self.scope_base / ".agents"

    def payload(self) -> dict[str, object]:
        return {
            "home": str(self.home),
            "project_root": (
                str(self.project_root)
                if self.project_root is not None
                else None
            ),
            "scope": self.scope.value,
            "profile": (
                self.profile.value
                if self.profile is not None
                else None
            ),
            "targets": list(self.targets),
            "replace_native": self.replace_native,
            "imported_at": self.imported_at,
            "include_native_cache": self.include_native_cache,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "MigrationOptions":
        expected = {
            "home",
            "project_root",
            "scope",
            "profile",
            "targets",
            "replace_native",
            "imported_at",
            "include_native_cache",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("migration options fields are invalid")
        if (
            not isinstance(payload["home"], str)
            or (
                payload["project_root"] is not None
                and not isinstance(payload["project_root"], str)
            )
            or type(payload["replace_native"]) is not bool
            or type(payload["include_native_cache"]) is not bool
            or not isinstance(payload["imported_at"], str)
        ):
            raise ValueError("migration option value types are invalid")
        targets = payload["targets"]
        if not isinstance(targets, list) or any(
            not isinstance(item, str) for item in targets
        ):
            raise ValueError("migration option targets are invalid")
        try:
            scope = Scope(payload["scope"])
            profile = (
                ProjectProfile(payload["profile"])
                if payload["profile"] is not None
                else None
            )
        except (TypeError, ValueError) as error:
            raise ValueError("migration option enum is invalid") from error
        return cls(
            home=Path(payload["home"]),
            project_root=(
                Path(payload["project_root"])
                if payload["project_root"] is not None
                else None
            ),
            scope=scope,
            profile=profile,
            targets=tuple(targets),
            replace_native=payload["replace_native"],
            imported_at=payload["imported_at"],
            include_native_cache=payload["include_native_cache"],
        )


@dataclass(frozen=True)
class MigrationSourceFile:
    artifact_id: str
    source_agent_id: str
    scope: ArtifactScope
    path: Path
    relative_path: str
    source_sha256: str
    is_directory: bool
    already_neutral: bool

    def __post_init__(self) -> None:
        validate_sha256(self.artifact_id, field="source artifact ID")
        validate_sha256(
            self.source_sha256,
            field="source artifact SHA-256",
        )
        if _ADAPTER_ID.fullmatch(self.source_agent_id) is None:
            raise ValueError("source adapter ID must be kebab-case")
        if not isinstance(self.scope, ArtifactScope):
            raise ValueError("source artifact scope must be valid")
        expected_id = derive_artifact_id(
            agent_id=self.source_agent_id,
            scope=self.scope,
            relative_path=self.relative_path,
            source_sha256=self.source_sha256,
        )
        if self.artifact_id != expected_id:
            raise ValueError(
                "source artifact ID does not match source identity"
            )
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError("migration source path must be absolute")
        relative = normalize_relative_path(self.relative_path)
        if type(self.is_directory) is not bool:
            raise ValueError("source directory flag must be boolean")
        if type(self.already_neutral) is not bool:
            raise ValueError("source neutral flag must be boolean")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "relative_path", relative)

    def payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "source_agent_id": self.source_agent_id,
            "scope": self.scope.value,
            "path": str(self.path),
            "relative_path": self.relative_path,
            "source_sha256": self.source_sha256,
            "is_directory": self.is_directory,
            "already_neutral": self.already_neutral,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "MigrationSourceFile":
        expected = {
            "artifact_id",
            "source_agent_id",
            "scope",
            "path",
            "relative_path",
            "source_sha256",
            "is_directory",
            "already_neutral",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("migration source fields are invalid")
        if any(
            not isinstance(payload[key], str)
            for key in (
                "artifact_id",
                "source_agent_id",
                "scope",
                "path",
                "relative_path",
                "source_sha256",
            )
        ):
            raise ValueError("migration source value types are invalid")
        if (
            type(payload["is_directory"]) is not bool
            or type(payload["already_neutral"]) is not bool
        ):
            raise ValueError("migration source flags are invalid")
        try:
            scope = ArtifactScope(payload["scope"])
        except ValueError as error:
            raise ValueError("migration source scope is invalid") from error
        return cls(
            artifact_id=payload["artifact_id"],
            source_agent_id=payload["source_agent_id"],
            scope=scope,
            path=Path(payload["path"]),
            relative_path=payload["relative_path"],
            source_sha256=payload["source_sha256"],
            is_directory=payload["is_directory"],
            already_neutral=payload["already_neutral"],
        )


@dataclass(frozen=True)
class MigrationPlanResult:
    inventory_sha256: str
    classification_sha256: str | None
    normalized_sha256: str
    options: MigrationOptions
    source_files: tuple[MigrationSourceFile, ...]
    import_plan: TransactionPlan
    source_replacement_plan: TransactionPlan | None
    blocking_conflicts: tuple[str, ...]
    report: MigrationReport

    def __post_init__(self) -> None:
        validate_sha256(
            self.inventory_sha256,
            field="inventory SHA-256",
        )
        if self.classification_sha256 is not None:
            validate_sha256(
                self.classification_sha256,
                field="classification SHA-256",
            )
        validate_sha256(
            self.normalized_sha256,
            field="normalized SHA-256",
        )
        conflicts = tuple(sorted(set(self.blocking_conflicts)))
        if conflicts != self.report.blocking_conflicts:
            raise ValueError(
                "plan conflicts do not match migration report"
            )
        object.__setattr__(self, "blocking_conflicts", conflicts)
        for source in self.source_files:
            if source.scope.value != self.options.scope.value:
                raise ValueError(
                    "migration source scope does not match options"
                )
            expected = self.options.scope_base.joinpath(
                *source.relative_path.split("/")
            ).resolve(strict=False)
            if source.path.resolve(strict=False) != expected:
                raise ValueError(
                    "migration source path does not match its relative path"
                )

    def to_json(self) -> str:
        payload = {
            "schema_version": 1,
            "inventory_sha256": self.inventory_sha256,
            "classification_sha256": self.classification_sha256,
            "normalized_sha256": self.normalized_sha256,
            "options": self.options.payload(),
            "source_files": [
                source.payload() for source in self.source_files
            ],
            "import_plan": json.loads(self.import_plan.to_json()),
            "source_replacement_plan": (
                json.loads(self.source_replacement_plan.to_json())
                if self.source_replacement_plan is not None
                else None
            ),
            "blocking_conflicts": list(self.blocking_conflicts),
            "report": self.report.payload(),
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "MigrationPlanResult":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("invalid migration plan JSON") from error
        if not isinstance(payload, dict) or set(payload) != _RESULT_KEYS:
            raise ValueError("migration plan fields are invalid")
        if payload["schema_version"] != 1:
            raise ValueError("unsupported migration plan schema")
        source_files = payload["source_files"]
        conflicts = payload["blocking_conflicts"]
        if not isinstance(source_files, list) or not isinstance(
            conflicts,
            list,
        ):
            raise ValueError("migration plan collections are invalid")
        replacement = payload["source_replacement_plan"]
        return cls(
            inventory_sha256=payload["inventory_sha256"],
            classification_sha256=payload["classification_sha256"],
            normalized_sha256=payload["normalized_sha256"],
            options=MigrationOptions.from_payload(payload["options"]),
            source_files=tuple(
                MigrationSourceFile.from_payload(item)
                for item in source_files
            ),
            import_plan=TransactionPlan.from_json(
                json.dumps(payload["import_plan"])
            ),
            source_replacement_plan=(
                TransactionPlan.from_json(json.dumps(replacement))
                if replacement is not None
                else None
            ),
            blocking_conflicts=tuple(conflicts),
            report=MigrationReport.from_payload(payload["report"]),
        )


def build_migration_plan(
    inventory: MigrationInventory,
    normalized: NormalizationBatch,
    decisions: ClassificationResponse | None,
    mappings: Iterable[MappedNativeArtifact],
    options: MigrationOptions,
) -> MigrationPlanResult:
    records = tuple(
        record
        for record in inventory.artifacts
        if record.scope.value == options.scope.value
    )
    recomputed = resolve_normalized_collisions(
        tuple(
            normalize_deterministic(
                record,
                options.scope_base,
                include_native_cache=options.include_native_cache,
            )
            for record in records
        )
    )
    normalization_tampered = (
        normalized.to_json() != recomputed.to_json()
    )
    deterministic = recomputed if normalization_tampered else normalized
    classified, decision_conflicts, decision_warnings = (
        _classified_artifacts(records, decisions)
    )
    combined = resolve_normalized_collisions(
        (*deterministic.artifacts, *classified)
    )
    conflicts = [
        *(
            f"normalization conflict: {item.destination}"
            for item in deterministic.conflicts
        ),
        *(
            f"normalization conflict: {item.destination}"
            for item in combined.conflicts
        ),
        *decision_conflicts,
    ]
    if normalization_tampered:
        conflicts.append(
            "normalized artifact file does not match deterministic "
            "recomputation"
        )
    warnings = [*inventory.warnings, *decision_warnings]
    source_mappings: list[str] = []
    sensitive_skips: list[str] = []
    import_operations: list[WriteOperation] = []
    imported_memory: list[NormalizedArtifact] = []
    migrated_identities: set[tuple[str, str, str]] = set()
    deterministic_identities = {
        (
            artifact.provenance.source_agent,
            artifact.provenance.source_relative_path,
            artifact.provenance.source_sha256,
        )
        for artifact in deterministic.artifacts
    }
    records_by_identity = {
        (
            record.agent_id,
            record.relative_path,
            record.sha256,
        ): record
        for record in records
    }
    for artifact in combined.artifacts:
        provenance = artifact.provenance
        identity = (
            provenance.source_agent,
            provenance.source_relative_path,
            provenance.source_sha256,
        )
        if normalization_tampered and identity in deterministic_identities:
            continue
        record = records_by_identity.get(identity)
        if record is None:
            conflicts.append(
                "normalized artifact has no matching inventory source: "
                f"{provenance.source_relative_path}"
            )
            continue
        sensitive_reason = _sensitive_source_reason(record)
        if sensitive_reason is not None:
            label = (
                f"{record.agent_id}:{record.relative_path}:"
                f"{sensitive_reason}"
            )
            sensitive_skips.append(label)
            conflicts.append(
                f"sensitive source blocked: "
                f"{record.agent_id}:{record.relative_path}"
            )
            continue
        migrated_identities.add(identity)
        if artifact.kind is ArtifactKind.MANUAL_MEMORY:
            imported_memory.append(artifact)
        source_mappings.append(
            f"{provenance.source_agent}:"
            f"{provenance.source_relative_path} -> "
            f"neutral:{artifact.relative_destination}"
        )
        for path, content in _normalized_output_files(artifact):
            target = options.neutral_root.joinpath(*path.split("/"))
            current = _safe_current_hash(target)
            desired = hashlib.sha256(content).hexdigest()
            if current == desired:
                continue
            if current is not None:
                conflicts.append(
                    f"unmanaged destination differs: neutral:{path}"
                )
                continue
            import_operations.append(
                WriteOperation.from_bytes(
                    root_id="neutral",
                    path=path,
                    content=content,
                    expected_sha256=None,
                    ownership=Ownership.CANONICAL,
                )
            )

    if imported_memory:
        index_content = merge_memory_index(
            imported_memory,
            imported_at=options.imported_at,
        )
        index_path = "memory/IMPORTED.md"
        target = options.neutral_root / "memory" / "IMPORTED.md"
        current = _safe_current_hash(target)
        desired = hashlib.sha256(index_content).hexdigest()
        if current == desired:
            pass
        elif current is not None:
            conflicts.append(
                "unmanaged destination differs: "
                f"neutral:{index_path}"
            )
        else:
            import_operations.append(
                WriteOperation.from_bytes(
                    root_id="neutral",
                    path=index_path,
                    content=index_content,
                    expected_sha256=None,
                    ownership=Ownership.CANONICAL,
                )
            )

    mapping_results = tuple(mappings)
    unsupported_fields: list[str] = []
    mapping_blockers: list[str] = []
    for result in mapping_results:
        for mapping in result.mappings:
            source_mappings.append(
                f"{result.source_agent_id}:"
                f"{result.source_relative_path}:"
                f"{mapping.source_key} -> "
                f"{result.target_agent_id}:"
                f"{mapping.target_key or 'unmapped'} "
                f"({mapping.status.value})"
            )
            if mapping.status is MappingStatus.UNSUPPORTED:
                unsupported_fields.append(
                    f"{result.source_relative_path}:{mapping.source_key}"
                )
                mapping_blockers.append(
                    "unsupported native field: "
                    f"{result.source_relative_path}:{mapping.source_key}"
                )
            elif mapping.status is MappingStatus.MANUAL:
                mapping_blockers.append(
                    "manual native field: "
                    f"{result.source_relative_path}:{mapping.source_key}"
                )
            elif mapping.status is MappingStatus.SENSITIVE_SKIP:
                sensitive_skips.append(
                    f"{result.source_relative_path}:{mapping.source_key}"
                )
                mapping_blockers.append(
                    "sensitive native field: "
                    f"{result.source_relative_path}:{mapping.source_key}"
                )

    target_roots = {
        "neutral": str(options.neutral_root),
        "scope": str(options.scope_base),
    }
    allowed_roots = (str(options.scope_base),)
    conflicts = sorted(set(conflicts))
    import_plan = TransactionPlan.new(
        scope_root=str(options.neutral_root),
        target_roots=target_roots,
        allowed_roots=allowed_roots,
        operations=tuple(import_operations),
        conflicts=tuple(conflicts),
        warnings=tuple(sorted(set(warnings))),
    )
    source_files = tuple(
        MigrationSourceFile(
            artifact_id=record.artifact_id,
            source_agent_id=record.agent_id,
            scope=record.scope,
            path=record.path,
            relative_path=record.relative_path,
            source_sha256=record.sha256,
            is_directory=record.path.is_dir(),
            already_neutral=record.already_neutral,
        )
        for record in records
    )

    replacement_plan: TransactionPlan | None
    replaced_ids: set[str] = set()
    if not options.replace_native:
        replacement_plan = TransactionPlan.new(
            scope_root=str(options.neutral_root),
            target_roots=target_roots,
            allowed_roots=allowed_roots,
            operations=(),
        )
    elif conflicts or mapping_blockers:
        conflicts = sorted(set((*conflicts, *mapping_blockers)))
        replacement_plan = None
    else:
        replacement_operations: list[
            WriteOperation | DeleteOperation
        ] = []
        for record in records:
            identity = (
                record.agent_id,
                record.relative_path,
                record.sha256,
            )
            if (
                identity not in migrated_identities
                or record.already_neutral
                or record.kind in {
                    ArtifactKind.RULES,
                    ArtifactKind.SETTINGS,
                    ArtifactKind.PERMISSIONS,
                    ArtifactKind.HOOKS,
                    ArtifactKind.MCP,
                }
            ):
                continue
            operations = _source_delete_operations(
                record,
                options.scope_base,
            )
            replacement_operations.extend(operations)
            if operations:
                replaced_ids.add(record.artifact_id)
        if options.targets:
            (
                entrypoint_operations,
                entrypoint_replaced_ids,
                entrypoint_blockers,
            ) = _native_entrypoint_replacements(
                records,
                migrated_identities,
                options,
            )
        else:
            entrypoint_operations = ()
            entrypoint_replaced_ids = frozenset()
            entrypoint_blockers = ()
        replacement_operations.extend(entrypoint_operations)
        replaced_ids.update(entrypoint_replaced_ids)
        if entrypoint_blockers:
            conflicts = sorted(
                set((*conflicts, *entrypoint_blockers))
            )
            replacement_plan = None
        else:
            replacement_plan = TransactionPlan.new(
                scope_root=str(options.neutral_root),
                target_roots=target_roots,
                allowed_roots=allowed_roots,
                operations=tuple(replacement_operations),
            )

    preserved = tuple(
        f"{record.agent_id}:{record.relative_path}"
        for record in records
        if record.artifact_id not in replaced_ids
    )
    deduplications = tuple(
        f"{item.destination}:"
        + ",".join(
            f"{origin.source_agent}:{origin.source_relative_path}"
            for origin in item.origins
        )
        for item in (
            *normalized.deduplications,
            *recomputed.deduplications,
            *combined.deduplications,
        )
    )
    report = MigrationReport(
        source_mappings=tuple(source_mappings),
        source_files_preserved=preserved,
        blocking_conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        sensitive_skips=tuple(sensitive_skips),
        unsupported_fields=tuple(unsupported_fields),
        deduplications=deduplications,
        expected_doctor_checks=(
            "generated hashes",
            "manifest schema",
            "portable skill references",
        ),
    )
    return MigrationPlanResult(
        inventory_sha256=_sha256_text(inventory.to_json()),
        classification_sha256=(
            _sha256_text(decisions.to_json())
            if decisions is not None
            else None
        ),
        normalized_sha256=_sha256_text(normalized.to_json()),
        options=options,
        source_files=source_files,
        import_plan=import_plan,
        source_replacement_plan=replacement_plan,
        blocking_conflicts=tuple(conflicts),
        report=report,
    )


def _classified_artifacts(
    records: tuple[ArtifactRecord, ...],
    response: ClassificationResponse | None,
) -> tuple[
    tuple[NormalizedArtifact, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if response is None:
        return (), (), ()
    by_id = {record.artifact_id: record for record in records}
    artifacts: list[NormalizedArtifact] = []
    conflicts: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for decision in response.decisions:
        if decision.artifact_id in seen:
            conflicts.append(
                f"duplicate classification: {decision.artifact_id}"
            )
            continue
        seen.add(decision.artifact_id)
        record = by_id.get(decision.artifact_id)
        if record is None:
            conflicts.append(
                "classification references an artifact outside this scope: "
                f"{decision.artifact_id}"
            )
            continue
        if decision.kind is DecisionKind.CONFLICT:
            conflicts.append(
                f"classification conflict: {record.relative_path}"
            )
        elif decision.kind in {
            DecisionKind.UNSUPPORTED,
            DecisionKind.SENSITIVE_SKIP,
            DecisionKind.NATIVE_SETTING,
        }:
            warnings.append(
                f"{decision.kind.value}: {record.relative_path}"
            )
        else:
            try:
                artifact = _normalized_from_decision(
                    record,
                    decision,
                )
            except ValueError as error:
                conflicts.append(
                    f"classification cannot normalize "
                    f"{record.relative_path}: {error}"
                )
            else:
                artifacts.append(artifact)
    return tuple(artifacts), tuple(conflicts), tuple(warnings)


def _normalized_from_decision(
    record: ArtifactRecord,
    decision: ClassificationDecision,
) -> NormalizedArtifact:
    redacted = redact_artifact(record)
    if redacted.text is None or redacted.reasons:
        raise ValueError("source contains sensitive or unreadable text")
    name = decision.name or _portable_slug(
        Path(record.relative_path).stem
    )
    if _PORTABLE_NAME.fullmatch(name) is None:
        raise ValueError("decision name is not portable")
    text = _verified_text(record)
    provenance = ArtifactProvenance(
        source_agent=record.agent_id,
        source_scope=record.scope.value,
        source_relative_path=record.relative_path,
        source_sha256=record.sha256,
    )
    if decision.kind is DecisionKind.COMMON_RULE:
        filename = f"{name}-from-{record.agent_id}.md"
        return NormalizedArtifact(
            kind=ArtifactKind.RULES,
            root_id="neutral",
            relative_destination=f"rules/{filename}",
            files={filename: text.encode("utf-8")},
            provenance=provenance,
        )
    if decision.kind is DecisionKind.AGENT_OVERLAY:
        agent_id = decision.agent_id or record.agent_id
        return NormalizedArtifact(
            kind=ArtifactKind.RULES,
            root_id="neutral",
            relative_destination=f"overlays/{agent_id}/RULES.md",
            files={"RULES.md": text.encode("utf-8")},
            provenance=provenance,
        )
    if decision.kind is DecisionKind.SKILL:
        description = _first_content_line(text)[:200]
        content = (
            "---\n"
            f"name: {name}\n"
            f"description: {description or f'Imported workflow {name}.'}\n"
            "---\n\n"
            f"{text}"
        ).encode("utf-8")
        return NormalizedArtifact(
            kind=ArtifactKind.SKILL,
            root_id="neutral",
            relative_destination=f"skills/{name}",
            files={"SKILL.md": content},
            provenance=provenance,
        )
    if decision.kind is DecisionKind.MANUAL_MEMORY:
        filename = f"{name}-from-{record.agent_id}.md"
        content = (
            "---\n"
            "type: imported-memory\n"
            f"source-agent: {record.agent_id}\n"
            f"source-scope: {record.scope.value}\n"
            f"source-relative-path: {record.relative_path}\n"
            f"source-sha256: {record.sha256}\n"
            "---\n\n"
            f"{text}"
        ).encode("utf-8")
        return NormalizedArtifact(
            kind=ArtifactKind.MANUAL_MEMORY,
            root_id="neutral",
            relative_destination=f"memory/{filename}",
            files={filename: content},
            provenance=provenance,
        )
    if decision.kind is DecisionKind.SESSION_CONTEXT:
        filename = f"undated-{name}-from-{record.agent_id}.md"
        return NormalizedArtifact(
            kind=ArtifactKind.SESSION,
            root_id="neutral",
            relative_destination=f"sessions/{filename}",
            files={filename: text.encode("utf-8")},
            provenance=provenance,
        )
    raise ValueError("decision kind has no portable normalization")


def _normalized_output_files(
    artifact: NormalizedArtifact,
) -> tuple[tuple[str, bytes], ...]:
    if (
        len(artifact.files) == 1
        and artifact.destination_name in artifact.files
    ):
        return (
            (
                artifact.relative_destination,
                artifact.files[artifact.destination_name],
            ),
        )
    return tuple(
        (
            f"{artifact.relative_destination}/{relative}",
            content,
        )
        for relative, content in artifact.files.items()
    )


def _source_delete_operations(
    record: ArtifactRecord,
    scope_base: Path,
) -> tuple[DeleteOperation, ...]:
    try:
        record.path.resolve(strict=True).relative_to(scope_base)
    except (OSError, ValueError) as error:
        raise ValueError(
            "migration source is outside the selected scope"
        ) from error
    if record.path.is_file():
        return (
            DeleteOperation(
                root_id="scope",
                path=record.relative_path,
                expected_sha256=record.sha256,
                ownership=Ownership.UNMANAGED,
            ),
        )
    if not record.path.is_dir() or record.path.is_symlink():
        raise ValueError("migration source is not a safe file or directory")
    operations: list[DeleteOperation] = []
    for child in sorted(
        record.path.rglob("*"),
        key=lambda path: path.relative_to(record.path).as_posix(),
    ):
        if child.is_symlink():
            raise ValueError("migration source directory contains a symlink")
        if child.is_dir():
            continue
        if not child.is_file():
            raise ValueError("migration source directory is unsafe")
        relative = child.relative_to(record.path).as_posix()
        operations.append(
            DeleteOperation(
                root_id="scope",
                path=f"{record.relative_path}/{relative}",
                expected_sha256=sha256_file(child),
                ownership=Ownership.UNMANAGED,
            )
        )
    return tuple(operations)


def _native_entrypoint_replacements(
    records: tuple[ArtifactRecord, ...],
    migrated_identities: set[tuple[str, str, str]],
    options: MigrationOptions,
) -> tuple[
    tuple[WriteOperation, ...],
    frozenset[str],
    tuple[str, ...],
]:
    manifest_path = options.neutral_root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return (), frozenset(), (
            "native replacement requires a valid neutral manifest",
        )
    try:
        manifest = WorkflowManifest.from_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError):
        return (), frozenset(), (
            "native replacement requires a valid neutral manifest",
        )

    context = AdapterContext(
        home=options.home,
        project_root=options.project_root,
        neutral_root=options.neutral_root,
        scope=options.scope,
        profile=options.profile,
        generator_version=__version__,
    )
    try:
        adapters = builtin_registry().require(options.targets)
    except ValueError:
        return (), frozenset(), (
            "native replacement supports only installed built-in adapters",
        )

    rules_by_entrypoint = {
        (record.agent_id, record.relative_path): record
        for record in records
        if record.kind is ArtifactKind.RULES
    }
    operations: list[WriteOperation] = []
    replaced_ids: set[str] = set()
    replacements: list[dict[str, str]] = []
    blockers: list[str] = []
    for adapter in adapters:
        for operation in adapter.plan_entrypoints(context):
            record = rules_by_entrypoint.get(
                (adapter.id, operation.path)
            )
            if operation.expected_sha256 is not None:
                if record is None:
                    managed_digest = manifest.generated_files.get(
                        f"scope:{operation.path}"
                    )
                    if managed_digest != operation.expected_sha256:
                        blockers.append(
                            "native entrypoint is not a migrated or "
                            f"manager-owned source: {adapter.id}:"
                            f"{operation.path}"
                        )
                        continue
                else:
                    identity = (
                        record.agent_id,
                        record.relative_path,
                        record.sha256,
                    )
                    if identity not in migrated_identities:
                        blockers.append(
                            "native entrypoint was not fully migrated: "
                            f"{adapter.id}:{operation.path}"
                        )
                        continue
                    replaced_ids.add(record.artifact_id)
                    replacements.append(
                        {
                            "source_agent": record.agent_id,
                            "scope": record.scope.value,
                            "source_relative_path": (
                                record.relative_path
                            ),
                            "source_sha256": record.sha256,
                            "replacement_sha256": hashlib.sha256(
                                operation.content_bytes()
                            ).hexdigest(),
                        }
                    )
            operations.append(operation)

    if blockers:
        return (), frozenset(), tuple(sorted(set(blockers)))

    generated_files = dict(manifest.generated_files)
    for operation in operations:
        generated_files[
            f"{operation.root_id}:{operation.path}"
        ] = hashlib.sha256(operation.content_bytes()).hexdigest()

    if replacements:
        provenance_path = (
            options.neutral_root
            / "workflow"
            / "migration-replacements.json"
        )
        try:
            prior_replacements, provenance_expected = (
                _load_replacement_provenance(
                    provenance_path,
                    manifest,
                )
            )
        except ValueError as error:
            return (), frozenset(), (str(error),)
        replacement_by_identity = {
            tuple(item[key] for key in sorted(_REPLACEMENT_KEYS)): item
            for item in (*prior_replacements, *replacements)
        }
        provenance = (
            json.dumps(
                {
                    "schema_version": 1,
                    "replacements": sorted(
                        replacement_by_identity.values(),
                        key=lambda item: (
                            item["scope"],
                            item["source_agent"],
                            item["source_relative_path"],
                            item["source_sha256"],
                        ),
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        operations.append(
            WriteOperation.from_bytes(
                root_id="neutral",
                path="workflow/migration-replacements.json",
                content=provenance,
                expected_sha256=provenance_expected,
                ownership=Ownership.GENERATED,
            )
        )
        generated_files[
            "neutral:workflow/migration-replacements.json"
        ] = hashlib.sha256(provenance).hexdigest()

    updated_manifest = WorkflowManifest(
        schema_version=manifest.schema_version,
        generator_version=__version__,
        scope=manifest.scope,
        profile=manifest.profile,
        targets=tuple(
            sorted(set((*manifest.targets, *options.targets)))
        ),
        generated_files=generated_files,
        bootstrap_root=manifest.bootstrap_root,
    )
    operations.append(
        WriteOperation.from_bytes(
            root_id="neutral",
            path="manifest.json",
            content=updated_manifest.to_json().encode("utf-8"),
            expected_sha256=sha256_file(manifest_path),
            ownership=Ownership.GENERATED,
        )
    )
    return (
        tuple(operations),
        frozenset(replaced_ids),
        (),
    )


def _load_replacement_provenance(
    path: Path,
    manifest: WorkflowManifest,
) -> tuple[tuple[dict[str, str], ...], str | None]:
    current = _safe_current_hash(path)
    if current is None:
        return (), None
    if (
        manifest.generated_files.get(
            "neutral:workflow/migration-replacements.json"
        )
        != current
    ):
        raise ValueError(
            "native replacement provenance is not manager-owned"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "native replacement provenance is invalid"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "replacements"}
        or payload["schema_version"] != 1
        or not isinstance(payload["replacements"], list)
    ):
        raise ValueError("native replacement provenance is invalid")
    output: list[dict[str, str]] = []
    for item in payload["replacements"]:
        if (
            not isinstance(item, dict)
            or set(item) != _REPLACEMENT_KEYS
            or any(not isinstance(value, str) for value in item.values())
        ):
            raise ValueError(
                "native replacement provenance is invalid"
            )
        if _ADAPTER_ID.fullmatch(item["source_agent"]) is None:
            raise ValueError(
                "native replacement provenance is invalid"
            )
        try:
            ArtifactScope(item["scope"])
            normalized = normalize_relative_path(
                item["source_relative_path"]
            )
            validate_sha256(item["source_sha256"])
            validate_sha256(item["replacement_sha256"])
        except ValueError as error:
            raise ValueError(
                "native replacement provenance is invalid"
            ) from error
        if normalized != item["source_relative_path"]:
            raise ValueError(
                "native replacement provenance is invalid"
            )
        output.append(dict(item))
    return tuple(output), current


def _safe_current_hash(path: Path) -> str | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"migration destination is unsafe: {path}")
    try:
        return sha256_file(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(
            f"migration destination cannot be read: {path}"
        ) from error


def _sensitive_source_reason(
    record: ArtifactRecord,
) -> str | None:
    if not record.path.is_dir():
        redacted = redact_artifact(record)
        if redacted.text is None:
            return ",".join(redacted.reasons) or "unreadable"
        if redacted.reasons:
            return ",".join(redacted.reasons)
        return None
    if record.path.is_symlink():
        return "symlink"
    try:
        entries = sorted(
            record.path.rglob("*"),
            key=lambda path: path.relative_to(record.path).as_posix(),
        )
        for entry in entries:
            if entry.is_symlink():
                return "symlink"
            if entry.is_dir():
                continue
            if not entry.is_file():
                return "unsafe-entry"
            content = entry.read_bytes()
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            suffix = entry.suffix.casefold()
            if suffix == ".json":
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    pass
                else:
                    if redact_json(parsed) != parsed:
                        return "sensitive-key"
            elif suffix == ".toml":
                try:
                    parsed = tomllib.loads(text)
                except tomllib.TOMLDecodeError:
                    pass
                else:
                    if redact_json(parsed) != parsed:
                        return "sensitive-key"
            redaction = redact_text(text)
            if redaction.blocked:
                return ",".join(redaction.reasons)
            if redaction.reasons:
                return ",".join(redaction.reasons)
    except OSError:
        return "unreadable"
    return None


def _verified_text(record: ArtifactRecord) -> str:
    if not record.path.is_file() or record.path.is_symlink():
        raise ValueError("classified artifact must be a safe file")
    content = record.path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError("classified artifact changed after inventory")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("classified artifact is not UTF-8") from error


def _portable_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError("artifact name cannot become portable")
    return slug[:63].rstrip("-")


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        value = " ".join(line.lstrip("#").split())
        if value:
            return value.replace(":", " -")
    return ""


def _safe_directory(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required")
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"{label} must be a safe directory")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} must be an existing directory") from error
    if not resolved.is_dir() or resolved.is_symlink():
        raise ValueError(f"{label} must be a safe directory")
    return resolved


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
