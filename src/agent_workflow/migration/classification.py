from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from agent_workflow.model import validate_sha256

from .model import ArtifactKind, MigrationInventory
from .redaction import redact_artifact, redact_text


_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PATH_LIKE = re.compile(
    r"(?:^|[\s`])(?:\.\.[\\/]|[A-Za-z]:[\\/]|/(?:home|Users|var|tmp)/)"
)
_AMBIGUOUS_KINDS = frozenset(
    {
        ArtifactKind.RULES,
        ArtifactKind.SUBAGENT_PROMPT,
        ArtifactKind.UNKNOWN,
    }
)
_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "request_sha256",
        "known_adapter_ids",
        "allowed_decision_kinds",
        "artifacts",
    }
)
_RESPONSE_KEYS = frozenset(
    {"schema_version", "request_id", "request_sha256", "decisions"}
)
_DECISION_KEYS = frozenset(
    {
        "artifact_id",
        "kind",
        "name",
        "rationale",
        "confidence",
        "agent_id",
    }
)
_CONFIDENCE = frozenset({"high", "medium", "low"})


class DecisionKind(StrEnum):
    COMMON_RULE = "common_rule"
    AGENT_OVERLAY = "agent_overlay"
    SKILL = "skill"
    MANUAL_MEMORY = "manual_memory"
    SESSION_CONTEXT = "session_context"
    NATIVE_SETTING = "native_setting"
    UNSUPPORTED = "unsupported"
    SENSITIVE_SKIP = "sensitive_skip"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ClassificationArtifact:
    artifact_id: str
    original_kind: ArtifactKind
    scope: str
    media_type: str
    relative_label: str
    text: str
    sensitivity: str
    redaction_reasons: tuple[str, ...]
    truncated: bool

    def payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "original_kind": self.original_kind.value,
            "scope": self.scope,
            "media_type": self.media_type,
            "relative_label": self.relative_label,
            "text": self.text,
            "sensitivity": self.sensitivity,
            "redaction_reasons": list(self.redaction_reasons),
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ClassificationRequest:
    schema_version: int
    request_id: str
    request_sha256: str
    known_adapter_ids: tuple[str, ...]
    allowed_decision_kinds: tuple[DecisionKind, ...]
    artifacts: tuple[ClassificationArtifact, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported classification request schema")
        validate_sha256(self.request_sha256, field="request SHA-256")
        if not self.request_id.startswith("migration-"):
            raise ValueError("classification request ID is invalid")
        if self.known_adapter_ids != tuple(
            sorted(set(self.known_adapter_ids))
        ):
            raise ValueError("known adapter IDs must be sorted and unique")
        if any(
            _ADAPTER_ID.fullmatch(adapter_id) is None
            for adapter_id in self.known_adapter_ids
        ):
            raise ValueError("known adapter ID is invalid")
        if self.allowed_decision_kinds != tuple(
            sorted(set(self.allowed_decision_kinds), key=lambda item: item.value)
        ):
            raise ValueError("allowed decision kinds must be sorted and unique")
        artifact_ids = [item.artifact_id for item in self.artifacts]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("classification request has duplicate artifacts")

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "known_adapter_ids": list(self.known_adapter_ids),
            "allowed_decision_kinds": [
                item.value for item in self.allowed_decision_kinds
            ],
            "artifacts": [item.payload() for item in self.artifacts],
        }
        if set(payload) != _REQUEST_KEYS:
            raise AssertionError("classification request payload is incomplete")
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @property
    def artifact_ids(self) -> frozenset[str]:
        return frozenset(item.artifact_id for item in self.artifacts)


@dataclass(frozen=True)
class ClassificationDecision:
    artifact_id: str
    kind: DecisionKind
    name: str | None
    rationale: str
    confidence: str
    agent_id: str | None = None

    def __post_init__(self) -> None:
        validate_sha256(self.artifact_id, field="classification artifact ID")
        if not isinstance(self.kind, DecisionKind):
            raise ValueError("classification decision kind is invalid")
        if self.name is not None and _NAME.fullmatch(self.name) is None:
            raise ValueError("classification decision name is invalid")
        if (
            not isinstance(self.rationale, str)
            or len(self.rationale) > 500
            or "\x00" in self.rationale
        ):
            raise ValueError("classification rationale is invalid")
        if self.confidence not in _CONFIDENCE:
            raise ValueError("classification confidence is invalid")
        if (
            self.agent_id is not None
            and _ADAPTER_ID.fullmatch(self.agent_id) is None
        ):
            raise ValueError("classification agent ID is invalid")

    def payload(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "name": self.name,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "agent_id": self.agent_id,
        }


@dataclass(frozen=True)
class ClassificationResponse:
    schema_version: int
    request_id: str
    request_sha256: str
    decisions: tuple[ClassificationDecision, ...]

    def to_json(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "decisions": [item.payload() for item in self.decisions],
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def build_classification_request(
    inventory: MigrationInventory,
) -> ClassificationRequest:
    artifacts: list[ClassificationArtifact] = []
    for record in inventory.artifacts:
        if record.kind not in _AMBIGUOUS_KINDS:
            continue
        redacted = redact_artifact(record)
        if redacted.text is None:
            continue
        artifacts.append(
            ClassificationArtifact(
                artifact_id=record.artifact_id,
                original_kind=record.kind,
                scope=record.scope.value,
                media_type=record.media_type,
                relative_label=redacted.relative_label,
                text=redacted.text,
                sensitivity=redacted.sensitivity.value,
                redaction_reasons=redacted.reasons,
                truncated=redacted.truncated,
            )
        )
    artifacts.sort(key=lambda item: item.artifact_id)
    known_adapter_ids = tuple(
        sorted({item.agent_id for item in inventory.artifacts})
    )
    allowed = tuple(sorted(DecisionKind, key=lambda item: item.value))
    digest_payload = {
        "schema_version": 1,
        "known_adapter_ids": list(known_adapter_ids),
        "allowed_decision_kinds": [item.value for item in allowed],
        "artifacts": [item.payload() for item in artifacts],
    }
    canonical = json.dumps(
        digest_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return ClassificationRequest(
        schema_version=1,
        request_id=f"migration-{digest[:24]}",
        request_sha256=digest,
        known_adapter_ids=known_adapter_ids,
        allowed_decision_kinds=allowed,
        artifacts=tuple(artifacts),
    )


def validate_classification_response(
    payload: object,
    *,
    allowed_artifact_ids: set[str] | frozenset[str] | None = None,
    request: ClassificationRequest | None = None,
    known_adapter_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        return ("response must be an object",)

    decisions_value = payload.get("decisions")
    decisions = decisions_value if isinstance(decisions_value, list) else []
    for index, raw_decision in enumerate(decisions):
        if not isinstance(raw_decision, dict) or not all(
            isinstance(key, str) for key in raw_decision
        ):
            errors.append(f"decisions[{index}] must be an object")
            continue
        unknown = set(raw_decision) - _DECISION_KEYS
        if unknown:
            errors.append(
                f"decisions[{index}] has unknown fields: "
                + ", ".join(sorted(unknown))
            )
        missing = _DECISION_KEYS - set(raw_decision)
        if missing:
            errors.append(
                f"decisions[{index}] is missing fields: "
                + ", ".join(sorted(missing))
            )

    unknown_top = set(payload) - _RESPONSE_KEYS
    if unknown_top:
        errors.append(
            "response has unknown fields: " + ", ".join(sorted(unknown_top))
        )
    missing_top = _RESPONSE_KEYS - set(payload)
    if missing_top:
        errors.append(
            "response is missing fields: " + ", ".join(sorted(missing_top))
        )
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(decisions_value, list):
        errors.append("decisions must be a list")

    expected_ids = (
        request.artifact_ids
        if request is not None
        else frozenset(allowed_artifact_ids or ())
    )
    known_ids = set(known_adapter_ids)
    if request is not None:
        known_ids.update(request.known_adapter_ids)
        if payload.get("request_id") != request.request_id:
            errors.append("request_id does not match request")
        if payload.get("request_sha256") != request.request_sha256:
            errors.append("request_sha256 does not match request")

    seen: list[str] = []
    for index, raw_decision in enumerate(decisions):
        if not isinstance(raw_decision, dict):
            continue
        artifact_id = raw_decision.get("artifact_id")
        if not isinstance(artifact_id, str):
            errors.append(f"decisions[{index}].artifact_id must be a string")
        else:
            seen.append(artifact_id)
            if expected_ids and artifact_id not in expected_ids:
                errors.append(
                    f"decisions[{index}].artifact_id is not in request"
                )
        try:
            DecisionKind(raw_decision.get("kind"))
        except (TypeError, ValueError):
            errors.append(f"decisions[{index}].kind is invalid")
        name = raw_decision.get("name")
        if name is not None and (
            not isinstance(name, str) or _NAME.fullmatch(name) is None
        ):
            errors.append(f"decisions[{index}].name is invalid")
        rationale = raw_decision.get("rationale")
        if (
            not isinstance(rationale, str)
            or len(rationale) > 500
            or "\x00" in rationale
            or "\n" in rationale
        ):
            errors.append(f"decisions[{index}].rationale is invalid")
        elif _PATH_LIKE.search(rationale):
            errors.append(f"decisions[{index}].rationale contains a path")
        else:
            redaction = redact_text(rationale)
            if redaction.blocked or redaction.reasons:
                errors.append(
                    f"decisions[{index}].rationale contains sensitive text"
                )
        confidence = raw_decision.get("confidence")
        if confidence not in _CONFIDENCE:
            errors.append(f"decisions[{index}].confidence is invalid")
        agent_id = raw_decision.get("agent_id")
        if agent_id is not None and (
            not isinstance(agent_id, str)
            or _ADAPTER_ID.fullmatch(agent_id) is None
            or (known_ids and agent_id not in known_ids)
        ):
            errors.append(f"decisions[{index}].agent_id is invalid")

    seen_set = set(seen)
    if len(seen_set) != len(seen):
        errors.append("response contains duplicate artifact decisions")
    missing_ids = expected_ids - seen_set
    if missing_ids:
        errors.append(
            "response is missing decisions for: "
            + ", ".join(sorted(missing_ids))
        )
    return tuple(errors)


def load_classification_response(
    path: Path,
    request: ClassificationRequest,
) -> ClassificationResponse:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("classification response is unreadable") from error
    errors = validate_classification_response(payload, request=request)
    if errors:
        raise ValueError("invalid classification response: " + "; ".join(errors))
    decisions = tuple(
        ClassificationDecision(
            artifact_id=item["artifact_id"],
            kind=DecisionKind(item["kind"]),
            name=item["name"],
            rationale=item["rationale"],
            confidence=item["confidence"],
            agent_id=item["agent_id"],
        )
        for item in payload["decisions"]
    )
    return ClassificationResponse(
        schema_version=1,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        decisions=tuple(
            sorted(decisions, key=lambda item: item.artifact_id)
        ),
    )
