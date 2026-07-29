from __future__ import annotations

from pathlib import Path

from agent_workflow.portability import lint_skill
from tests.helpers import load_skill


def test_session_skills_use_only_neutral_canonical_paths(
    repo_root: Path,
) -> None:
    for name in ("wrap", "backlog", "pick"):
        skill = repo_root / "skills" / name
        text = skill.joinpath("SKILL.md").read_text(encoding="utf-8")

        assert ".agents/sessions" in text
        assert ".agents/memory" in text
        assert ".claude/" not in text
        assert ".codex/" not in text
        assert lint_skill(skill) == ()


def test_wrap_and_backlog_contracts_remain_compatible(
    repo_root: Path,
) -> None:
    wrap = load_skill(repo_root, "wrap")
    backlog = load_skill(repo_root, "backlog")

    assert wrap.emitted_tags
    assert wrap.emitted_tags == backlog.accepted_tags
    assert "_backlog.md" in backlog.body
    assert "Active" in backlog.body
    assert "Resolved" in backlog.body
    assert "Processed sources" in backlog.body


def test_wrap_preserves_session_information_model(
    repo_root: Path,
) -> None:
    wrap = load_skill(repo_root, "wrap")

    required = (
        "YYYY-MM-DD-<slug>.md",
        "Summary",
        "What changed",
        "Decisions",
        "Challenges / dead ends",
        "Observed behavior",
        "Open threads",
        "one-shot administrative chores",
    )
    for phrase in required:
        assert phrase in wrap.body


def test_backlog_and_pick_preserve_selection_contract(
    repo_root: Path,
) -> None:
    backlog = load_skill(repo_root, "backlog").body
    pick = load_skill(repo_root, "pick").body

    for phrase in (
        "[H]",
        "[M]",
        "[L]",
        "stable `id`",
        "mtime",
        "hash",
        "Source",
    ):
        assert phrase in backlog
    for phrase in (
        "exact `id`",
        "`id` substring",
        "title substring",
        "Zero matches",
        "Multiple matches",
        "available planning workflow",
    ):
        assert phrase in pick
