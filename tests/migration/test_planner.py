from __future__ import annotations

import json
import hashlib
from pathlib import Path

from agent_workflow.migration.classification import (
    ClassificationDecision,
    ClassificationResponse,
    DecisionKind,
    build_classification_request,
)
from agent_workflow.migration.mappings import (
    MappedNativeArtifact,
    MappingStatus,
    NativeMapping,
)
from agent_workflow.migration.planner import (
    MigrationOptions,
    MigrationPlanResult,
    build_migration_plan,
)
from agent_workflow.migration.model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    MigrationInventory,
    Sensitivity,
    derive_artifact_id,
)
from agent_workflow.migration.normalize import (
    NormalizationBatch,
    NormalizedArtifact,
    normalize_deterministic,
    resolve_normalized_collisions,
)
from agent_workflow.layout import plan_neutral_init
from agent_workflow.manifest import WorkflowManifest
from agent_workflow.migration.apply import apply_migration
from agent_workflow.model import Scope
from agent_workflow.paths import HostPaths
from agent_workflow.plan import WriteOperation
from agent_workflow.transactions import apply_plan, rollback_transaction
from tests.migration.helpers import claude_command_fixture


def test_plan_separates_import_writes_from_source_replacement(
    tmp_path: Path,
) -> None:
    inputs = _migration_inputs(tmp_path, replace_native=False)

    result = build_migration_plan(**inputs)

    assert result.import_plan.operations
    assert not result.source_replacement_plan.operations
    assert result.report.source_files_preserved


def test_replace_native_is_blocked_by_unsupported_fields(
    tmp_path: Path,
) -> None:
    inputs = _migration_inputs(tmp_path, replace_native=True)
    record = inputs["inventory"].artifacts[0]
    inputs["mappings"] = (
        MappedNativeArtifact(
            artifact_id=record.artifact_id,
            source_agent_id=record.agent_id,
            target_agent_id="codex",
            source_relative_path=record.relative_path,
            mappings=(
                NativeMapping(
                    source_key="future-setting",
                    target_key=None,
                    status=MappingStatus.UNSUPPORTED,
                    normalized_value=None,
                    unmapped_fields=("future-setting",),
                    credential_fields=(),
                    rationale="No proven equivalent exists.",
                    adapter_version="manifest-1",
                ),
            ),
        ),
    )

    result = build_migration_plan(**inputs)

    assert result.blocking_conflicts
    assert result.source_replacement_plan is None


def test_import_plan_never_clobbers_unmanaged_destination(
    tmp_path: Path,
) -> None:
    inputs = _migration_inputs(tmp_path, replace_native=False)
    destination = (
        inputs["options"].home
        / ".agents"
        / "skills"
        / "pick"
        / "SKILL.md"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("unmanaged\n", encoding="utf-8")

    result = build_migration_plan(**inputs)

    assert result.blocking_conflicts
    assert any(
        "unmanaged destination" in conflict
        for conflict in result.blocking_conflicts
    )


def test_materialized_migration_plan_round_trips_exactly(
    tmp_path: Path,
) -> None:
    result = build_migration_plan(
        **_migration_inputs(tmp_path, replace_native=True)
    )

    restored = MigrationPlanResult.from_json(result.to_json())

    assert restored.to_json() == result.to_json()
    assert restored.import_plan.plan_id == result.import_plan.plan_id
    assert (
        restored.source_replacement_plan is not None
        and result.source_replacement_plan is not None
    )
    assert (
        restored.source_replacement_plan.plan_id
        == result.source_replacement_plan.plan_id
    )


def test_materialized_plan_rejects_source_path_retargeting(
    tmp_path: Path,
) -> None:
    result = build_migration_plan(
        **_migration_inputs(tmp_path, replace_native=False)
    )
    payload = json.loads(result.to_json())
    payload["source_files"][0]["path"] = str(
        tmp_path / "outside" / "pick.md"
    )

    try:
        MigrationPlanResult.from_json(json.dumps(payload))
    except ValueError as error:
        assert "source path" in str(error)
    else:
        raise AssertionError("retargeted source path was accepted")


def test_validated_common_rule_decision_gets_python_owned_destination(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    source = home / ".claude" / "CLAUDE.md"
    source.parent.mkdir(parents=True)
    source.write_text("Use reversible changes.\n", encoding="utf-8")
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    scope = ArtifactScope.GLOBAL
    record = ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id="claude",
            scope=scope,
            relative_path=".claude/CLAUDE.md",
            source_sha256=digest,
        ),
        agent_id="claude",
        kind=ArtifactKind.RULES,
        scope=scope,
        path=source.resolve(),
        relative_path=".claude/CLAUDE.md",
        sha256=digest,
        media_type="text/markdown",
        size_bytes=len(content),
        sensitivity=Sensitivity.SAFE,
        already_neutral=False,
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude/CLAUDE.md",),
        artifacts=(record,),
        warnings=(),
    )
    request = build_classification_request(inventory)
    response = ClassificationResponse(
        schema_version=1,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        decisions=(
            ClassificationDecision(
                artifact_id=record.artifact_id,
                kind=DecisionKind.COMMON_RULE,
                name="shared-behavior",
                rationale="The behavior applies to every selected agent.",
                confidence="high",
            ),
        ),
    )

    result = build_migration_plan(
        inventory=inventory,
        normalized=NormalizationBatch((), (), ()),
        decisions=response,
        mappings=(),
        options=MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=("claude", "codex"),
            replace_native=False,
            imported_at="2026-07-29T00:00:00Z",
        ),
    )

    operation = result.import_plan.operations[0]
    assert operation.path == "rules/shared-behavior-from-claude.md"
    assert operation.content_bytes() == content
    assert result.classification_sha256 == hashlib.sha256(
        response.to_json().encode("utf-8")
    ).hexdigest()


def test_tampered_normalized_content_is_blocking(
    tmp_path: Path,
) -> None:
    inputs = _migration_inputs(tmp_path, replace_native=False)
    original = inputs["normalized"].artifacts[0]
    inputs["normalized"] = NormalizationBatch(
        artifacts=(
            NormalizedArtifact(
                kind=original.kind,
                root_id=original.root_id,
                relative_destination=original.relative_destination,
                files={"SKILL.md": b"tampered"},
                provenance=original.provenance,
            ),
        ),
        conflicts=(),
        deduplications=(),
    )

    result = build_migration_plan(**inputs)

    assert any(
        "deterministic recomputation" in conflict
        for conflict in result.blocking_conflicts
    )
    assert not result.import_plan.operations


def test_sensitive_deterministic_source_is_never_imported(
    tmp_path: Path,
) -> None:
    fresh_record, fresh_source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="token=secret-value\n",
    )
    fresh_home = tmp_path / "home"
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude/commands",),
        artifacts=(fresh_record,),
        warnings=(),
    )
    normalized = resolve_normalized_collisions(
        (normalize_deterministic(fresh_record, fresh_source),)
    )
    options = MigrationOptions(
        home=fresh_home,
        project_root=None,
        scope=Scope.GLOBAL,
        profile=None,
        targets=("claude", "codex"),
        replace_native=False,
        imported_at="2026-07-29T00:00:00Z",
    )

    result = build_migration_plan(
        inventory=inventory,
        normalized=normalized,
        decisions=None,
        mappings=(),
        options=options,
    )

    assert any(
        "sensitive source blocked" in conflict
        for conflict in result.blocking_conflicts
    )
    assert "secret-value" not in result.report.to_json()
    assert not result.import_plan.operations


def test_replace_native_rule_writes_generated_entrypoint_and_provenance(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    apply_plan(
        plan_neutral_init(
            HostPaths(home=home, cwd=tmp_path, project_root=None),
            scope=Scope.GLOBAL,
            profile=None,
            targets=(),
        )
    )
    source = home / ".claude" / "CLAUDE.md"
    source.parent.mkdir()
    source.write_text("Use reversible changes.\n", encoding="utf-8")
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    scope = ArtifactScope.GLOBAL
    record = ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id="claude",
            scope=scope,
            relative_path=".claude/CLAUDE.md",
            source_sha256=digest,
        ),
        agent_id="claude",
        kind=ArtifactKind.RULES,
        scope=scope,
        path=source.resolve(),
        relative_path=".claude/CLAUDE.md",
        sha256=digest,
        media_type="text/markdown",
        size_bytes=len(content),
        sensitivity=Sensitivity.SAFE,
        already_neutral=False,
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude/CLAUDE.md",),
        artifacts=(record,),
        warnings=(),
    )
    request = build_classification_request(inventory)
    response = ClassificationResponse(
        schema_version=1,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        decisions=(
            ClassificationDecision(
                artifact_id=record.artifact_id,
                kind=DecisionKind.COMMON_RULE,
                name="shared-behavior",
                rationale="The behavior applies to every selected agent.",
                confidence="high",
            ),
        ),
    )

    result = build_migration_plan(
        inventory=inventory,
        normalized=NormalizationBatch((), (), ()),
        decisions=response,
        mappings=(),
        options=MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=("claude",),
            replace_native=True,
            imported_at="2026-07-29T00:00:00Z",
        ),
    )

    assert result.source_replacement_plan is not None
    operations = {
        (operation.root_id, operation.path): operation
        for operation in result.source_replacement_plan.operations
    }
    entrypoint = operations[("scope", ".claude/CLAUDE.md")]
    assert isinstance(entrypoint, WriteOperation)
    assert entrypoint.expected_sha256 == digest
    assert b"@~/.agents/RULES.md" in entrypoint.content_bytes()

    provenance = operations[
        ("neutral", "workflow/migration-replacements.json")
    ]
    assert isinstance(provenance, WriteOperation)
    provenance_payload = json.loads(
        provenance.content_bytes().decode("utf-8")
    )
    assert provenance_payload["replacements"] == [
        {
            "replacement_sha256": hashlib.sha256(
                entrypoint.content_bytes()
            ).hexdigest(),
            "scope": "global",
            "source_agent": "claude",
            "source_relative_path": ".claude/CLAUDE.md",
            "source_sha256": digest,
        }
    ]

    manifest_operation = operations[("neutral", "manifest.json")]
    assert isinstance(manifest_operation, WriteOperation)
    manifest = WorkflowManifest.from_json(
        manifest_operation.content_bytes().decode("utf-8")
    )
    assert manifest.targets == ("claude",)
    assert manifest.generated_files["scope:.claude/CLAUDE.md"] == (
        provenance_payload["replacements"][0]["replacement_sha256"]
    )
    assert (
        "neutral:workflow/migration-replacements.json"
        in manifest.generated_files
    )

    applied = apply_migration(result, confirm_replacement=True)
    assert applied.replacement_journal is not None
    assert source.read_bytes() == entrypoint.content_bytes()
    installed_manifest = WorkflowManifest.from_json(
        (home / ".agents" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert installed_manifest.targets == ("claude",)

    rollback_transaction(
        Path(applied.replacement_journal.journal_path)
    )
    assert source.read_bytes() == content
    restored_manifest = WorkflowManifest.from_json(
        (home / ".agents" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert restored_manifest.targets == ()
    assert not (
        home
        / ".agents"
        / "workflow"
        / "migration-replacements.json"
    ).exists()


def test_replace_native_merges_manager_owned_provenance(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    apply_plan(
        plan_neutral_init(
            HostPaths(home=home, cwd=tmp_path, project_root=None),
            scope=Scope.GLOBAL,
            profile=None,
            targets=("claude",),
        )
    )
    provenance_path = (
        home
        / ".agents"
        / "workflow"
        / "migration-replacements.json"
    )
    provenance_path.parent.mkdir(exist_ok=True)
    prior_replacement = {
        "replacement_sha256": "1" * 64,
        "scope": "global",
        "source_agent": "claude",
        "source_relative_path": ".claude/CLAUDE.md",
        "source_sha256": "2" * 64,
    }
    existing_provenance = (
        json.dumps(
            {
                "schema_version": 1,
                "replacements": [prior_replacement],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    provenance_path.write_bytes(existing_provenance)
    existing_digest = hashlib.sha256(existing_provenance).hexdigest()
    manifest_path = home / ".agents" / "manifest.json"
    manifest = WorkflowManifest.from_json(
        manifest_path.read_text(encoding="utf-8")
    )
    generated_files = dict(manifest.generated_files)
    generated_files[
        "neutral:workflow/migration-replacements.json"
    ] = existing_digest
    manifest_path.write_text(
        WorkflowManifest(
            schema_version=manifest.schema_version,
            generator_version=manifest.generator_version,
            scope=manifest.scope,
            profile=manifest.profile,
            targets=manifest.targets,
            generated_files=generated_files,
            bootstrap_root=manifest.bootstrap_root,
        ).to_json(),
        encoding="utf-8",
    )

    source = home / ".codex" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("Keep project state recoverable.\n", encoding="utf-8")
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    record = ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id="codex",
            scope=ArtifactScope.GLOBAL,
            relative_path=".codex/AGENTS.md",
            source_sha256=digest,
        ),
        agent_id="codex",
        kind=ArtifactKind.RULES,
        scope=ArtifactScope.GLOBAL,
        path=source.resolve(),
        relative_path=".codex/AGENTS.md",
        sha256=digest,
        media_type="text/markdown",
        size_bytes=len(content),
        sensitivity=Sensitivity.SAFE,
        already_neutral=False,
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("codex:global:.codex/AGENTS.md",),
        artifacts=(record,),
        warnings=(),
    )
    request = build_classification_request(inventory)
    response = ClassificationResponse(
        schema_version=1,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        decisions=(
            ClassificationDecision(
                artifact_id=record.artifact_id,
                kind=DecisionKind.COMMON_RULE,
                name="codex-behavior",
                rationale="The behavior applies to every selected agent.",
                confidence="high",
            ),
        ),
    )

    result = build_migration_plan(
        inventory=inventory,
        normalized=NormalizationBatch((), (), ()),
        decisions=response,
        mappings=(),
        options=MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=("codex",),
            replace_native=True,
            imported_at="2026-07-29T00:00:00Z",
        ),
    )

    assert not result.blocking_conflicts
    assert result.source_replacement_plan is not None
    operations = {
        (operation.root_id, operation.path): operation
        for operation in result.source_replacement_plan.operations
    }
    provenance = operations[
        ("neutral", "workflow/migration-replacements.json")
    ]
    assert isinstance(provenance, WriteOperation)
    assert provenance.expected_sha256 == existing_digest
    payload = json.loads(provenance.content_bytes().decode("utf-8"))
    assert prior_replacement in payload["replacements"]
    assert {
        "replacement_sha256": hashlib.sha256(
            operations[("scope", ".codex/AGENTS.md")].content_bytes()
        ).hexdigest(),
        "scope": "global",
        "source_agent": "codex",
        "source_relative_path": ".codex/AGENTS.md",
        "source_sha256": digest,
    } in payload["replacements"]


def _migration_inputs(
    tmp_path: Path,
    *,
    replace_native: bool,
) -> dict[str, object]:
    record, source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="Resolve one backlog item.\n",
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude/commands",),
        artifacts=(record,),
        warnings=(),
    )
    normalized = resolve_normalized_collisions(
        (normalize_deterministic(record, source),)
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    apply_plan(
        plan_neutral_init(
            HostPaths(home=home, cwd=tmp_path, project_root=None),
            scope=Scope.GLOBAL,
            profile=None,
            targets=(),
        )
    )
    return {
        "inventory": inventory,
        "normalized": normalized,
        "decisions": None,
        "mappings": (),
        "options": MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=("claude", "codex"),
            replace_native=replace_native,
            imported_at="2026-07-29T00:00:00Z",
        ),
    }
