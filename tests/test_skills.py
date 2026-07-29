from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.claude import ClaudeAdapter
from agent_workflow.adapters.codex import CodexAdapter
from agent_workflow.model import Scope
from agent_workflow.skills import (
    discover_portable_skills,
    plan_skill_install,
    render_native_skill_wrapper,
)


def _context(tmp_path: Path) -> AdapterContext:
    home = tmp_path / "home"
    home.mkdir()
    return AdapterContext(
        home=home,
        project_root=None,
        neutral_root=home / ".agents",
        scope=Scope.GLOBAL,
        profile=None,
        generator_version="0.1.0",
    )


def test_discovery_reads_name_description_and_resources() -> None:
    root = Path("tests/fixtures/skills")

    skills = discover_portable_skills(root)

    assert [(item.name, item.description) for item in skills] == [
        ("portable-review", "Review pending code changes.")
    ]
    skill = skills[0]
    expected = hashlib.sha256()
    for relative_path in ("SKILL.md", "references/checklist.md"):
        expected.update(relative_path.encode("utf-8"))
        expected.update(b"\0")
        expected.update((skill.root / relative_path).read_bytes())
    assert skill.source_sha256 == expected.hexdigest()


def test_discovery_rejects_invalid_directory_name(tmp_path: Path) -> None:
    skill = tmp_path / "wrong-name"
    skill.mkdir()
    skill.joinpath("SKILL.md").write_text(
        "---\n"
        "name: another-name\n"
        "description: Invalid fixture.\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="portable skill"):
        discover_portable_skills(tmp_path)


def test_claude_wrapper_keeps_workflow_in_canonical_source() -> None:
    skill = discover_portable_skills(Path("tests/fixtures/skills"))[0]

    body = render_native_skill_wrapper(
        skill,
        agent_id="claude",
        canonical_path=Path("/home/user/.agents/skills/portable-review"),
    ).decode()

    assert "description: Review pending code changes." in body
    assert "Read the canonical `SKILL.md` completely" in body
    assert "/home/user/.agents/skills/portable-review/SKILL.md" in body
    assert "overlays/claude.md" in body
    assert "# source-sha256:" in body
    assert "Review pending code changes." not in body.split("---", 2)[-1]


def test_skill_install_writes_canonical_source_and_only_claude_wrapper(
    tmp_path: Path,
) -> None:
    skill = discover_portable_skills(Path("tests/fixtures/skills"))[0]
    adapter_context = _context(tmp_path)

    claude_operations = plan_skill_install(
        ClaudeAdapter(), adapter_context, (skill,)
    )
    codex_operations = plan_skill_install(
        CodexAdapter(), adapter_context, (skill,)
    )

    assert {
        (operation.root_id, operation.path)
        for operation in claude_operations
    } == {
        ("neutral", "skills/portable-review/SKILL.md"),
        ("neutral", "skills/portable-review/references/checklist.md"),
        ("scope", ".claude/skills/portable-review/SKILL.md"),
    }
    assert {
        (operation.root_id, operation.path)
        for operation in codex_operations
    } == {
        ("neutral", "skills/portable-review/SKILL.md"),
        ("neutral", "skills/portable-review/references/checklist.md"),
    }


def test_already_canonical_skill_creates_only_native_wrapper(
    tmp_path: Path,
) -> None:
    adapter_context = _context(tmp_path)
    canonical_parent = adapter_context.neutral_root / "skills"
    source = Path("tests/fixtures/skills/portable-review")
    destination = canonical_parent / "portable-review"
    destination.mkdir(parents=True)
    destination.joinpath("references").mkdir()
    destination.joinpath("SKILL.md").write_bytes(
        source.joinpath("SKILL.md").read_bytes()
    )
    destination.joinpath("references/checklist.md").write_bytes(
        source.joinpath("references/checklist.md").read_bytes()
    )
    skill = discover_portable_skills(canonical_parent)[0]

    operations = plan_skill_install(
        ClaudeAdapter(), adapter_context, (skill,)
    )

    assert [(operation.root_id, operation.path) for operation in operations] == [
        ("scope", ".claude/skills/portable-review/SKILL.md")
    ]
