from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_workflow.migration.classification import (
    ClassificationDecision,
    DecisionKind,
    build_classification_request,
    validate_classification_response,
)
from agent_workflow.migration.model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    MigrationInventory,
    Sensitivity,
    derive_artifact_id,
)


def test_response_cannot_choose_a_raw_destination() -> None:
    response = {
        "schema_version": 1,
        "request_id": "request-1",
        "decisions": [
            {
                "artifact_id": "artifact-1",
                "kind": "skill",
                "name": "wrap",
                "destination": "../../escape",
            }
        ],
    }

    errors = validate_classification_response(
        response, allowed_artifact_ids={"artifact-1"}
    )

    assert "destination" in errors[0]


def test_decision_kind_is_closed() -> None:
    decision = ClassificationDecision(
        artifact_id="a" * 64,
        kind=DecisionKind.COMMON_RULE,
        name=None,
        rationale="Shared behavior.",
        confidence="high",
    )

    assert decision.kind.value == "common_rule"


def test_request_contains_only_redacted_ambiguous_text(
    tmp_path: Path,
) -> None:
    rules = _record(
        tmp_path,
        "rules.md",
        ArtifactKind.RULES,
        "Use this rule.\ntoken=secret-value\n",
    )
    skill = _record(
        tmp_path,
        "skills/wrap/SKILL.md",
        ArtifactKind.SKILL,
        "---\nname: wrap\n---\nWrap work.\n",
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude",),
        artifacts=(rules, skill),
        warnings=(),
    )

    request = build_classification_request(inventory)
    serialized = request.to_json()
    payload = json.loads(serialized)

    assert [item["artifact_id"] for item in payload["artifacts"]] == [
        rules.artifact_id
    ]
    assert "secret-value" not in serialized
    assert "<redacted>" in serialized
    assert str(tmp_path) not in serialized
    assert tmp_path.as_posix() not in serialized


def test_request_redacts_absolute_paths_without_redacting_urls(
    tmp_path: Path,
) -> None:
    rules = _record(
        tmp_path,
        "rules.md",
        ArtifactKind.RULES,
        "Read /private/project/rules.md and https://example.com/docs.\n",
    )
    inventory = MigrationInventory(
        schema_version=1,
        roots=("claude:global:.claude",),
        artifacts=(rules,),
        warnings=(),
    )

    serialized = build_classification_request(inventory).to_json()

    assert "/private/project/rules.md" not in serialized
    assert "<absolute-path>" in serialized
    assert "https://example.com/docs" in serialized


def test_response_requires_exact_coverage_and_request_hash(
    tmp_path: Path,
) -> None:
    record = _record(
        tmp_path,
        "AGENTS.md",
        ArtifactKind.RULES,
        "Project behavior.\n",
    )
    request = build_classification_request(
        MigrationInventory(1, ("codex:project:AGENTS.md",), (record,), ())
    )
    response = {
        "schema_version": 1,
        "request_id": request.request_id,
        "request_sha256": "0" * 64,
        "decisions": [],
    }

    errors = validate_classification_response(response, request=request)

    assert any("request_sha256" in error for error in errors)
    assert any("missing decisions" in error for error in errors)


def _record(
    tmp_path: Path,
    relative_path: str,
    kind: ArtifactKind,
    content: str,
) -> ArtifactRecord:
    path = tmp_path.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    source = path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    scope = ArtifactScope.GLOBAL
    return ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id="claude",
            scope=scope,
            relative_path=relative_path,
            source_sha256=digest,
        ),
        agent_id="claude",
        kind=kind,
        scope=scope,
        path=path,
        relative_path=relative_path,
        sha256=digest,
        media_type="text/markdown",
        size_bytes=len(source),
        sensitivity=Sensitivity.SAFE,
        already_neutral=False,
    )
