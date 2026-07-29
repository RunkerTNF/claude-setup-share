from __future__ import annotations

import hashlib
from pathlib import Path

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.migration.model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    Sensitivity,
    derive_artifact_id,
)
from agent_workflow.model import ProjectProfile, Scope


def fake_adapter_context(
    *,
    home: Path,
    project: Path | None,
) -> AdapterContext:
    home.mkdir(parents=True, exist_ok=True)
    if project is None:
        scope = Scope.GLOBAL
        profile = None
        neutral_root = home / ".agents"
    else:
        project.mkdir(parents=True, exist_ok=True)
        scope = Scope.PROJECT
        profile = ProjectProfile.LOCAL
        neutral_root = project / ".agents"
    return AdapterContext(
        home=home,
        project_root=project,
        neutral_root=neutral_root,
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def populated_mixed_context(tmp_path: Path) -> AdapterContext:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "wrap.md").write_text(
        "Create a session note.\n",
        encoding="utf-8",
    )
    (home / ".codex" / "memory").mkdir(parents=True)
    (home / ".codex" / "memory" / "preferences.md").write_text(
        "Prefer portable workflows.\n",
        encoding="utf-8",
    )
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (project / "AGENTS.md").write_text(
        "Project rules.\n",
        encoding="utf-8",
    )
    return fake_adapter_context(home=home, project=project)


def standard_skill_fixture(
    tmp_path: Path,
    *,
    name: str,
) -> tuple[ArtifactRecord, Path]:
    source = tmp_path / "home" / ".agents" / "skills" / name
    source.mkdir(parents=True)
    source.joinpath("SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Preserve a portable workflow.\n"
        "---\n\n"
        "Read references/checklist.md.\n",
        encoding="utf-8",
        newline="\n",
    )
    references = source / "references"
    references.mkdir()
    references.joinpath("checklist.md").write_text(
        "- Preserve behavior.\n",
        encoding="utf-8",
        newline="\n",
    )
    return (
        _directory_record(
            source,
            relative_path=f".agents/skills/{name}",
            agent_id="codex",
            kind=ArtifactKind.SKILL,
            already_neutral=True,
        ),
        source,
    )


def claude_command_fixture(
    tmp_path: Path,
    *,
    name: str,
    body: str,
) -> tuple[ArtifactRecord, Path]:
    source = tmp_path / "home" / ".claude" / "commands" / f"{name}.md"
    source.parent.mkdir(parents=True)
    source.write_text(body, encoding="utf-8", newline="\n")
    return (
        _file_record(
            source,
            relative_path=f".claude/commands/{name}.md",
            agent_id="claude",
            kind=ArtifactKind.COMMAND,
        ),
        source,
    )


def memory_fixture(
    tmp_path: Path,
    name: str,
) -> tuple[ArtifactRecord, Path]:
    source = tmp_path / "home" / ".codex" / "memory" / name
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Preferences\n\nPrefer reversible changes.\n",
        encoding="utf-8",
        newline="\n",
    )
    return (
        _file_record(
            source,
            relative_path=f".codex/memory/{name}",
            agent_id="codex",
            kind=ArtifactKind.MANUAL_MEMORY,
        ),
        source,
    )


def _file_record(
    path: Path,
    *,
    relative_path: str,
    agent_id: str,
    kind: ArtifactKind,
    already_neutral: bool = False,
) -> ArtifactRecord:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    scope = ArtifactScope.GLOBAL
    return ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id=agent_id,
            scope=scope,
            relative_path=relative_path,
            source_sha256=digest,
        ),
        agent_id=agent_id,
        kind=kind,
        scope=scope,
        path=path,
        relative_path=relative_path,
        sha256=digest,
        media_type="text/markdown",
        size_bytes=len(content),
        sensitivity=Sensitivity.SAFE,
        already_neutral=already_neutral,
    )


def _directory_record(
    path: Path,
    *,
    relative_path: str,
    agent_id: str,
    kind: ArtifactKind,
    already_neutral: bool,
) -> ArtifactRecord:
    digest = hashlib.sha256()
    size = 0
    for source in sorted(
        (candidate for candidate in path.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(path).as_posix(),
    ):
        content = source.read_bytes()
        digest.update(source.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        size += len(content)
    source_sha256 = digest.hexdigest()
    scope = ArtifactScope.GLOBAL
    return ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id=agent_id,
            scope=scope,
            relative_path=relative_path,
            source_sha256=source_sha256,
        ),
        agent_id=agent_id,
        kind=kind,
        scope=scope,
        path=path,
        relative_path=relative_path,
        sha256=source_sha256,
        media_type="application/vnd.agent-skill.directory",
        size_bytes=size,
        sensitivity=Sensitivity.SAFE,
        already_neutral=already_neutral,
    )
