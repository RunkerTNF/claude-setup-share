from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import tomllib
from typing import Mapping

from .model import ArtifactRecord, Sensitivity


_REDACTED = "<redacted>"
_MAX_CLASSIFICATION_BYTES = 64 * 1024
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "private_key",
        "access_key",
        "secret_key",
        "authorization",
        "cookie",
        "session",
    }
)
_SENSITIVE_SUFFIXES = (
    "_token",
    "_secret",
    "_password",
    "_key",
    "_credential",
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_BEARER_ASSIGNMENT = re.compile(
    r"(?im)\b(?:authorization|auth_token|bearer_token)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_CLOUD_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_SECRET_LABEL = re.compile(
    r"(?im)^(?P<prefix>\s*(?:password|passwd|token|secret|api[_ -]?key)"
    r"\s*[:=]\s*)(?P<value>[^\r\n]*)(?P<cr>\r?)$"
)
_SIMPLE_SCALAR = re.compile(r"^[^\s,;\"']+$")
_QUOTED_SCALAR = re.compile(r"^(?P<quote>[\"'])(?P<value>.*)(?P=quote)$")
_PLACEHOLDER = re.compile(
    r"(?i)^(?:<[^>]+>|\$\{[^}]+\}|your[-_].+|example|placeholder|"
    r"redacted|changeme|none|null)$"
)


@dataclass(frozen=True)
class TextRedaction:
    text: str | None
    blocked: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RedactedArtifact:
    artifact_id: str
    relative_label: str
    text: str | None
    sensitivity: Sensitivity
    reasons: tuple[str, ...]
    truncated: bool


def redact_json(source: object) -> object:
    reasons: set[str] = set()
    return _redact_json(source, reasons)


def redact_text(text: str) -> TextRedaction:
    if not isinstance(text, str):
        raise TypeError("redaction input must be text")
    blocking_reasons: set[str] = set()
    if _PRIVATE_KEY.search(text):
        blocking_reasons.add("private-key")
    if _BEARER_ASSIGNMENT.search(text):
        blocking_reasons.add("bearer-token")
    if _CLOUD_ACCESS_KEY.search(text):
        blocking_reasons.add("cloud-access-key")
    if blocking_reasons:
        return TextRedaction(
            text=None,
            blocked=True,
            reasons=tuple(sorted(blocking_reasons)),
        )

    reasons: set[str] = set()
    output: list[str] = []
    position = 0
    for match in _SECRET_LABEL.finditer(text):
        output.append(text[position : match.start()])
        raw_value = match.group("value")
        stripped = raw_value.strip()
        if not stripped or _PLACEHOLDER.fullmatch(stripped):
            output.append(match.group(0))
            position = match.end()
            continue
        quoted = _QUOTED_SCALAR.fullmatch(stripped)
        if quoted is not None:
            replacement = f"{quoted.group('quote')}{_REDACTED}{quoted.group('quote')}"
        elif _SIMPLE_SCALAR.fullmatch(stripped):
            replacement = _REDACTED
        else:
            return TextRedaction(
                text=None,
                blocked=True,
                reasons=("ambiguous-secret",),
            )
        trailing = raw_value[len(raw_value.rstrip()) :]
        output.append(
            f"{match.group('prefix')}{replacement}{trailing}{match.group('cr')}"
        )
        reasons.add("labeled-secret")
        position = match.end()
    output.append(text[position:])
    return TextRedaction(
        text="".join(output),
        blocked=False,
        reasons=tuple(sorted(reasons)),
    )


def redact_artifact(record: ArtifactRecord) -> RedactedArtifact:
    if record.path.is_dir():
        return RedactedArtifact(
            artifact_id=record.artifact_id,
            relative_label=record.relative_path,
            text=None,
            sensitivity=Sensitivity.BLOCKED,
            reasons=("directory-artifact",),
            truncated=False,
        )
    try:
        content = record.path.read_bytes()
    except OSError:
        return RedactedArtifact(
            artifact_id=record.artifact_id,
            relative_label=record.relative_path,
            text=None,
            sensitivity=Sensitivity.BLOCKED,
            reasons=("unreadable-artifact",),
            truncated=False,
        )
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError(
            f"artifact changed after inventory: {record.relative_path}"
        )
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        return RedactedArtifact(
            artifact_id=record.artifact_id,
            relative_label=record.relative_path,
            text=None,
            sensitivity=Sensitivity.BLOCKED,
            reasons=("non-utf8-artifact",),
            truncated=False,
        )

    structured_reasons: set[str] = set()
    if record.media_type == "application/json":
        try:
            parsed = json.loads(source)
        except json.JSONDecodeError:
            result = redact_text(source)
        else:
            redacted = _redact_json(parsed, structured_reasons)
            result = TextRedaction(
                text=json.dumps(redacted, indent=2, sort_keys=True) + "\n",
                blocked=False,
                reasons=tuple(sorted(structured_reasons)),
            )
    elif record.media_type == "application/toml":
        try:
            parsed = tomllib.loads(source)
        except tomllib.TOMLDecodeError:
            result = redact_text(source)
        else:
            redacted = _redact_json(parsed, structured_reasons)
            result = TextRedaction(
                text=json.dumps(redacted, indent=2, sort_keys=True) + "\n",
                blocked=False,
                reasons=tuple(sorted(structured_reasons)),
            )
    else:
        result = redact_text(source)

    if result.blocked or result.text is None:
        return RedactedArtifact(
            artifact_id=record.artifact_id,
            relative_label=record.relative_path,
            text=None,
            sensitivity=Sensitivity.BLOCKED,
            reasons=result.reasons,
            truncated=False,
        )
    text, truncated = _truncate_utf8(result.text)
    sensitivity = (
        Sensitivity.REDACTED if result.reasons else Sensitivity.SAFE
    )
    return RedactedArtifact(
        artifact_id=record.artifact_id,
        relative_label=record.relative_path,
        text=text,
        sensitivity=sensitivity,
        reasons=result.reasons,
        truncated=truncated,
    )


def _redact_json(source: object, reasons: set[str]) -> object:
    if isinstance(source, Mapping):
        output: dict[str, object] = {}
        for raw_key, value in source.items():
            key = str(raw_key)
            if _sensitive_key(key):
                output[key] = _REDACTED
                reasons.add("sensitive-key")
            else:
                output[key] = _redact_json(value, reasons)
        return output
    if isinstance(source, list):
        return [_redact_json(value, reasons) for value in source]
    return source


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        _SENSITIVE_SUFFIXES
    )


def _truncate_utf8(text: str) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= _MAX_CLASSIFICATION_BYTES:
        return text, False
    return encoded[:_MAX_CLASSIFICATION_BYTES].decode(
        "utf-8", errors="ignore"
    ), True
