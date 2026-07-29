from __future__ import annotations

from pathlib import Path

from agent_workflow.portability import lint_skill
from tests.helpers import overlay_text, skill_text


def test_common_reviewer_skills_do_not_require_named_subagents(
    repo_root: Path,
) -> None:
    for name in ("plan-review", "code-review"):
        text = skill_text(repo_root, name)

        assert "Agent(subagent_type=" not in text
        assert "subagent_type" not in text
        assert "CLAUDE.md" not in text
        assert ".claude/memory" not in text
        assert ".agents/memory" in text
        assert "current agent" in text
        assert lint_skill(repo_root / "skills" / name) == ()


def test_agent_specific_delegation_lives_in_overlays(
    repo_root: Path,
) -> None:
    common = skill_text(
        repo_root,
        "plan-review",
    ) + skill_text(repo_root, "code-review")
    claude = overlay_text(
        repo_root,
        "claude",
        "review-workflow.md",
    )
    codex = overlay_text(
        repo_root,
        "codex",
        "review-workflow.md",
    )

    assert "subagent_type" not in common
    assert "subagent_type" in claude
    assert "generic worker" in codex.lower()
    assert "explicitly" in claude
    assert "explicitly" in codex
    assert "semantic source of truth" in " ".join(claude.split())
    assert "semantic source of truth" in " ".join(codex.split())
    for name in ("plan-review", "code-review"):
        assert (
            repo_root / "skills" / name / "overlays" / "claude.md"
        ).read_text(encoding="utf-8") == claude
        assert (
            repo_root / "skills" / name / "overlays" / "codex.md"
        ).read_text(encoding="utf-8") == codex


def test_review_contracts_preserve_checks_and_output(
    repo_root: Path,
) -> None:
    for name in ("plan-review", "code-review"):
        root = repo_root / "skills" / name
        body = skill_text(repo_root, name)
        contract = root.joinpath(
            "references/review-contract.md"
        ).read_text(encoding="utf-8")

        assert "references/review-contract.md" in body
        assert "read-only" in body
        assert "Triviality" in contract
        assert "Plan adherence" in contract
        assert "Convention compliance" in contract
        assert "Memory invariants" in contract
        assert "Safety" in contract
        assert "Tests and verification" in contract
        assert "Scope discipline" in contract
        assert "### Blocking" in contract
        assert "### Suggestions" in contract
        assert "### Verdict" in contract


def test_global_rules_make_review_skills_agent_neutral(
    repo_root: Path,
) -> None:
    canonical = repo_root / "templates" / "core" / "global-rules.md"
    bundled = (
        repo_root
        / "src"
        / "agent_workflow"
        / "_bundled"
        / "templates"
        / "core"
        / "global-rules.md"
    )
    text = canonical.read_text(encoding="utf-8")

    assert "plan-review" in text
    assert "code-review" in text
    assert "current agent" in text
    assert "explicitly requests delegation" in text
    assert canonical.read_bytes() == bundled.read_bytes()
