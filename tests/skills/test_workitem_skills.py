from __future__ import annotations

from pathlib import Path

from agent_workflow.portability import lint_skill
from tests.helpers import skill_text


_SKILLS = ("morning", "tasks", "my-reviews", "feedback")


def test_each_workitem_skill_has_a_local_reference(
    repo_root: Path,
) -> None:
    canonical = repo_root / "resources" / "workitems-rendering.md"

    for name in _SKILLS:
        skill_dir = repo_root / "skills" / name
        body = skill_text(repo_root, name)
        reference = (
            skill_dir / "references" / "workitems-rendering.md"
        )

        assert reference.is_file()
        assert "references/workitems-rendering.md" in body
        assert "~/.claude" not in body
        assert reference.read_bytes() == canonical.read_bytes()
        assert lint_skill(skill_dir) == ()


def test_workitem_skills_use_capabilities_and_local_data_contracts(
    repo_root: Path,
) -> None:
    combined = "\n".join(
        skill_text(repo_root, name) for name in _SKILLS
    )

    assert "~/sync-workitems/tasks/" in combined
    assert "~/sync-projects/<repo>/.sync-workitems/" in combined
    for forbidden in (
        "Read(",
        "Glob(",
        "Bash:",
        "MCP server",
        "connector",
        "slash command",
    ):
        assert forbidden not in combined


def test_digest_scope_and_argument_resolution_are_preserved(
    repo_root: Path,
) -> None:
    morning = skill_text(repo_root, "morning")
    tasks = skill_text(repo_root, "tasks")
    reviews = skill_text(repo_root, "my-reviews")
    feedback = skill_text(repo_root, "feedback")

    assert "tasks, reviews by repository, then feedback" in morning
    assert "combined total" in morning
    assert "without a combined total" in tasks
    for body in (reviews, feedback):
        assert "current working directory" in body
        assert "`all`" in body
        assert "available repositories" in body
        assert "MR Level 2" in body
    assert "review observations" in reviews
    assert "reply drafts" in feedback


def test_shared_reference_preserves_rendering_levels(
    repo_root: Path,
) -> None:
    text = (
        repo_root / "resources" / "workitems-rendering.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "Level 1",
        "Level 2",
        "Level 3",
        "status_changed",
        "comment_resolved",
        "Status mapping",
        "Empty and edge states",
        "Jira normalization",
        "Diff statistics",
        "Review observations",
        "Reply drafting",
    ):
        assert phrase in text
