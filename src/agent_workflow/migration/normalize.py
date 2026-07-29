from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Iterable, Mapping

from agent_workflow.model import normalize_relative_path
from agent_workflow.portability import (
    lint_skill,
    parse_portable_skill_frontmatter,
)

from .model import ArtifactKind, ArtifactRecord, Sensitivity


_PORTABLE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATE_PREFIX = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:-|$)")
_SHARED_RULE_MARKER = "<!-- agent-workflow:shared -->"
_DEFAULT_IMPORT_TIMESTAMP = "unspecified"
_PATH_REPLACEMENTS = (
    ("~/.claude/commands", "~/.agents/skills"),
    (".claude/commands", ".agents/skills"),
    ("~/.codex/skills", "~/.agents/skills"),
    (".codex/skills", ".agents/skills"),
)


@dataclass(frozen=True)
class ArtifactProvenance:
    source_agent: str
    source_scope: str
    source_relative_path: str
    source_sha256: str


@dataclass(frozen=True)
class NormalizedArtifact:
    kind: ArtifactKind
    root_id: str
    relative_destination: str
    files: Mapping[str, bytes]
    provenance: ArtifactProvenance
    adopt_existing: bool = False

    def __post_init__(self) -> None:
        if self.root_id != "neutral":
            raise ValueError("normalized artifacts must target the neutral root")
        destination = normalize_relative_path(self.relative_destination)
        files = dict(self.files)
        if not files:
            raise ValueError("normalized artifact files must not be empty")
        normalized_files: dict[str, bytes] = {}
        for relative_path, content in files.items():
            normalized = normalize_relative_path(relative_path)
            if not isinstance(content, bytes):
                raise ValueError("normalized artifact content must be bytes")
            if normalized in normalized_files:
                raise ValueError("normalized artifact has duplicate files")
            normalized_files[normalized] = content
        object.__setattr__(self, "relative_destination", destination)
        object.__setattr__(
            self,
            "files",
            MappingProxyType(
                dict(
                    sorted(
                        normalized_files.items(),
                        key=lambda item: item[0],
                    )
                )
            ),
        )

    @property
    def destination_name(self) -> str:
        return PurePosixPath(self.relative_destination).name


@dataclass(frozen=True)
class NormalizationConflict:
    destination: str
    candidates: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class NormalizationDeduplication:
    destination: str
    origins: tuple[ArtifactProvenance, ...]


@dataclass(frozen=True)
class NormalizationBatch:
    artifacts: tuple[NormalizedArtifact, ...]
    conflicts: tuple[NormalizationConflict, ...]
    deduplications: tuple[NormalizationDeduplication, ...]


def normalize_deterministic(
    record: ArtifactRecord,
    source_root: Path,
    *,
    include_native_cache: bool = False,
) -> NormalizedArtifact | None:
    source = _validated_source(record, source_root)
    if record.sensitivity is Sensitivity.BLOCKED:
        return None
    if record.kind is ArtifactKind.SKILL:
        return _normalize_skill(record, source)
    if record.kind is ArtifactKind.COMMAND:
        return convert_command_to_skill(record, _read_verified_text(record, source))
    if record.kind is ArtifactKind.MANUAL_MEMORY:
        return _normalize_memory(record, _read_verified_text(record, source))
    if record.kind is ArtifactKind.SESSION:
        return _normalize_session(record, _read_verified_text(record, source))
    if record.kind is ArtifactKind.RULES:
        text = _read_verified_text(record, source)
        if _SHARED_RULE_MARKER in text:
            return _normalize_rule(record, text)
        return None
    if record.kind is ArtifactKind.AUTO_MEMORY and include_native_cache:
        return _normalize_native_cache(record, source)
    return None


def resolve_normalized_collisions(
    artifacts: Iterable[NormalizedArtifact | None],
) -> NormalizationBatch:
    groups: dict[str, list[NormalizedArtifact]] = {}
    for artifact in artifacts:
        if artifact is None:
            continue
        key = f"{artifact.root_id}:{artifact.relative_destination}"
        groups.setdefault(key, []).append(artifact)

    output: list[NormalizedArtifact] = []
    conflicts: list[NormalizationConflict] = []
    deduplications: list[NormalizationDeduplication] = []
    occupied: set[str] = set(groups)
    for key, candidates in sorted(groups.items()):
        ordered = sorted(candidates, key=_normalized_identity)
        digests = {_normalized_digest(item) for item in ordered}
        if len(digests) == 1:
            chosen = ordered[0]
            output.append(chosen)
            if len(ordered) > 1:
                deduplications.append(
                    NormalizationDeduplication(
                        destination=chosen.relative_destination,
                        origins=tuple(item.provenance for item in ordered),
                    )
                )
            continue

        first = ordered[0]
        output.append(first)
        renamed = [first.relative_destination]
        for candidate in ordered[1:]:
            adjusted = _with_agent_suffix(candidate, occupied)
            output.append(adjusted)
            occupied.add(f"{adjusted.root_id}:{adjusted.relative_destination}")
            renamed.append(adjusted.relative_destination)
        conflicts.append(
            NormalizationConflict(
                destination=first.relative_destination,
                candidates=tuple(renamed),
                message=(
                    "different source bytes target the same normalized "
                    "destination and require explicit selection"
                ),
            )
        )
    return NormalizationBatch(
        artifacts=tuple(
            sorted(
                output,
                key=lambda item: (
                    item.root_id,
                    item.relative_destination,
                    _normalized_identity(item),
                ),
            )
        ),
        conflicts=tuple(conflicts),
        deduplications=tuple(deduplications),
    )


def convert_command_to_skill(
    record: ArtifactRecord,
    text: str,
) -> NormalizedArtifact:
    name = _portable_slug(Path(record.relative_path).stem)
    metadata, body = _legacy_frontmatter(text)
    description = metadata.get("description") or _first_sentence(body)
    description = _single_line(description)[:200].rstrip()
    if not description:
        description = f"Imported legacy command {name}."
    body = _replace_agent_paths(body)
    if body and not body.endswith(("\n", "\r")):
        body += "\n"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}"
    ).encode("utf-8")
    parse_portable_skill_frontmatter(content.decode("utf-8"))
    return NormalizedArtifact(
        kind=ArtifactKind.SKILL,
        root_id="neutral",
        relative_destination=f"skills/{name}",
        files={"SKILL.md": content},
        provenance=_provenance(record),
    )


def merge_memory_index(
    entries: Iterable[NormalizedArtifact | None],
    *,
    imported_at: str = _DEFAULT_IMPORT_TIMESTAMP,
) -> bytes:
    selected = sorted(
        (
            entry
            for entry in entries
            if entry is not None
            and entry.kind is ArtifactKind.MANUAL_MEMORY
        ),
        key=lambda entry: entry.relative_destination,
    )
    lines = [
        "# Imported Memory Index",
        "",
        f"Import timestamp: {imported_at}",
        "",
        "| Path | Title | Source agent | Source label | Source SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for entry in selected:
        content = entry.files[entry.destination_name].decode("utf-8")
        provenance = entry.provenance
        lines.append(
            "| "
            + " | ".join(
                (
                    _table(entry.relative_destination),
                    _table(_document_title(content)),
                    _table(provenance.source_agent),
                    _table(provenance.source_relative_path),
                    provenance.source_sha256,
                )
            )
            + " |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _normalize_skill(
    record: ArtifactRecord,
    source: Path,
) -> NormalizedArtifact:
    if not source.is_dir():
        raise ValueError("skill artifact must be a directory")
    diagnostics = lint_skill(source)
    if diagnostics:
        details = "; ".join(
            f"{item.code}:{item.path}" for item in diagnostics
        )
        raise ValueError(f"legacy skill is not portable: {details}")
    skill_text = source.joinpath("SKILL.md").read_text(encoding="utf-8")
    name, _, _ = parse_portable_skill_frontmatter(skill_text)
    files = _verified_skill_files(record, source)
    return NormalizedArtifact(
        kind=ArtifactKind.SKILL,
        root_id="neutral",
        relative_destination=f"skills/{name}",
        files=files,
        provenance=_provenance(record),
        adopt_existing=record.already_neutral,
    )


def _normalize_memory(
    record: ArtifactRecord,
    text: str,
) -> NormalizedArtifact:
    slug = _portable_slug(Path(record.relative_path).stem)
    filename = f"{slug}-from-{record.agent_id}.md"
    if _has_frontmatter(text):
        content = text
    else:
        content = (
            "---\n"
            "type: imported-memory\n"
            f"source-agent: {record.agent_id}\n"
            f"source-scope: {record.scope.value}\n"
            f"source-relative-path: {record.relative_path}\n"
            f"source-sha256: {record.sha256}\n"
            "---\n\n"
            f"{text}"
        )
    return NormalizedArtifact(
        kind=ArtifactKind.MANUAL_MEMORY,
        root_id="neutral",
        relative_destination=f"memory/{filename}",
        files={filename: content.encode("utf-8")},
        provenance=_provenance(record),
        adopt_existing=record.already_neutral,
    )


def _normalize_session(
    record: ArtifactRecord,
    text: str,
) -> NormalizedArtifact:
    stem = Path(record.relative_path).stem
    date_match = _DATE_PREFIX.match(stem)
    date = date_match.group("date") if date_match else "undated"
    remainder = stem[len(date) :].lstrip("-") if date_match else stem
    slug = _portable_slug(remainder or "session")
    filename = f"{date}-{slug}-from-{record.agent_id}.md"
    return NormalizedArtifact(
        kind=ArtifactKind.SESSION,
        root_id="neutral",
        relative_destination=f"sessions/{filename}",
        files={filename: text.encode("utf-8")},
        provenance=_provenance(record),
        adopt_existing=record.already_neutral,
    )


def _normalize_rule(
    record: ArtifactRecord,
    text: str,
) -> NormalizedArtifact:
    slug = _portable_slug(Path(record.relative_path).stem)
    filename = f"{slug}-from-{record.agent_id}.md"
    return NormalizedArtifact(
        kind=ArtifactKind.RULES,
        root_id="neutral",
        relative_destination=f"rules/{filename}",
        files={filename: text.encode("utf-8")},
        provenance=_provenance(record),
        adopt_existing=record.already_neutral,
    )


def _normalize_native_cache(
    record: ArtifactRecord,
    source: Path,
) -> NormalizedArtifact:
    filename = f"{_portable_slug(Path(record.relative_path).stem)}.md"
    text = _read_verified_text(record, source)
    return NormalizedArtifact(
        kind=ArtifactKind.AUTO_MEMORY,
        root_id="neutral",
        relative_destination=f"cache/{record.agent_id}/memory/{filename}",
        files={filename: text.encode("utf-8")},
        provenance=_provenance(record),
    )


def _validated_source(record: ArtifactRecord, source_root: Path) -> Path:
    source_root = Path(source_root).resolve(strict=True)
    source = record.path.resolve(strict=True)
    if source != source_root:
        try:
            source.relative_to(source_root)
        except ValueError as error:
            raise ValueError("artifact source escapes its supplied root") from error
    return source


def _read_verified_text(record: ArtifactRecord, source: Path) -> str:
    if not source.is_file() or source.is_symlink():
        raise ValueError("artifact source must be a safe file")
    try:
        content = source.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("artifact source must be readable UTF-8") from error
    if hashlib.sha256(content).hexdigest() != record.sha256:
        raise ValueError("artifact source hash changed after inventory")
    return text


def _verified_skill_files(
    record: ArtifactRecord,
    source: Path,
) -> Mapping[str, bytes]:
    files: dict[str, bytes] = {}
    digest = hashlib.sha256()
    try:
        entries = sorted(
            source.rglob("*"),
            key=lambda path: path.relative_to(source).as_posix(),
        )
    except OSError as error:
        raise ValueError("legacy skill cannot be read") from error
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("legacy skill contains a symlink")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError("legacy skill contains an unsafe resource")
        relative = entry.relative_to(source).as_posix()
        content = entry.read_bytes()
        files[relative] = content
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    if digest.hexdigest() != record.sha256:
        raise ValueError("legacy skill hash changed after inventory")
    return files


def _legacy_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, text
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip("\r\n")
        if stripped == "---":
            return metadata, "".join(lines[index + 1 :]).lstrip("\r\n")
        key, separator, value = stripped.partition(":")
        if separator and key.strip() in {"name", "description"}:
            metadata[key.strip()] = value.strip().strip("\"'")
    return {}, text


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        candidate = candidate.lstrip("#").strip()
        if not candidate:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", candidate, maxsplit=1)[0]
        return sentence
    return ""


def _single_line(text: str) -> str:
    return " ".join(text.split()).replace(":", " -")


def _replace_agent_paths(text: str) -> str:
    output = text
    for source, target in _PATH_REPLACEMENTS:
        output = output.replace(source, target)
    return output


def _portable_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError("artifact name cannot become a portable slug")
    slug = slug[:63].rstrip("-")
    if _PORTABLE_NAME.fullmatch(slug) is None:
        raise ValueError("artifact name is not portable")
    return slug


def _provenance(record: ArtifactRecord) -> ArtifactProvenance:
    return ArtifactProvenance(
        source_agent=record.agent_id,
        source_scope=record.scope.value,
        source_relative_path=record.relative_path,
        source_sha256=record.sha256,
    )


def _has_frontmatter(text: str) -> bool:
    lines = text.splitlines()
    return (
        len(lines) >= 2
        and lines[0] == "---"
        and "---" in lines[1:]
    )


def _document_title(text: str) -> str:
    _, body = _legacy_frontmatter(text)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
        if stripped:
            return stripped[:120]
    return "Untitled"


def _table(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def _normalized_identity(
    artifact: NormalizedArtifact,
) -> tuple[str, str, str]:
    provenance = artifact.provenance
    return (
        provenance.source_agent,
        provenance.source_relative_path,
        provenance.source_sha256,
    )


def _normalized_digest(artifact: NormalizedArtifact) -> str:
    digest = hashlib.sha256()
    digest.update(artifact.kind.value.encode("utf-8"))
    digest.update(b"\0")
    for relative_path, content in artifact.files.items():
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _with_agent_suffix(
    artifact: NormalizedArtifact,
    occupied: set[str],
) -> NormalizedArtifact:
    destination = PurePosixPath(artifact.relative_destination)
    final = destination.name
    suffix = f"-from-{artifact.provenance.source_agent}"
    if "." in final:
        stem, extension = final.rsplit(".", 1)
        candidate_name = f"{stem}{suffix}.{extension}"
    else:
        candidate_name = f"{final}{suffix}"
    parent = destination.parent
    candidate = (
        candidate_name
        if str(parent) == "."
        else f"{parent.as_posix()}/{candidate_name}"
    )
    key = f"{artifact.root_id}:{candidate}"
    if key in occupied:
        short_hash = artifact.provenance.source_sha256[:8]
        if "." in candidate_name:
            stem, extension = candidate_name.rsplit(".", 1)
            candidate_name = f"{stem}-{short_hash}.{extension}"
        else:
            candidate_name = f"{candidate_name}-{short_hash}"
        candidate = (
            candidate_name
            if str(parent) == "."
            else f"{parent.as_posix()}/{candidate_name}"
        )
    files = dict(artifact.files)
    if final in files:
        files[candidate_name] = files.pop(final)
    return replace(
        artifact,
        relative_destination=candidate,
        files=files,
    )
