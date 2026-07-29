from __future__ import annotations

from pathlib import Path

from agent_workflow.portability import lint_skill


def test_setup_uses_manager_for_project_writes(
    repo_root: Path,
) -> None:
    skill = repo_root / "skills" / "agent-workflow-setup"
    body = skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    reference = skill / "references" / "project-inference.md"
    inference = reference.read_text(encoding="utf-8")

    assert "references/project-inference.md" in body
    assert "setup preview --scope project" in inference
    assert "setup apply --plan" in inference
    assert "read-only" in inference
    assert "project.md" in inference
    assert "idempotent" in inference
    assert "local" in inference
    assert "shared" in inference
    assert "split" in inference
    for forbidden in (".claude/", ".codex/", "CLAUDE.md", "AGENTS.md"):
        assert forbidden not in inference
    assert lint_skill(skill) == ()


def test_project_templates_bootstrap_neutral_context(
    repo_root: Path,
) -> None:
    canonical = repo_root / "templates" / "core"
    bundled = (
        repo_root
        / "src"
        / "agent_workflow"
        / "_bundled"
        / "templates"
        / "core"
    )
    rules = canonical.joinpath("project-rules.md").read_text(
        encoding="utf-8"
    )
    memory = canonical.joinpath(
        "project-memory-index.md"
    ).read_text(encoding="utf-8")

    assert ".agents/RULES.md" in rules
    assert ".agents/memory/MEMORY.md" in rules
    assert ".agents/sessions/" in rules
    assert "project.md" in rules
    assert ".agents/memory/" in memory
    for name in ("project-rules.md", "project-memory-index.md"):
        assert canonical.joinpath(name).read_bytes() == (
            bundled / name
        ).read_bytes()
