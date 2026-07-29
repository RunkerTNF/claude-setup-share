from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("name", "reference"),
    (
        ("agent-workflow-setup", "references/setup-flow.md"),
        ("agent-workflow-migrate", "references/recovery.md"),
    ),
)
def test_management_skill_is_self_contained(
    repo_root: Path,
    name: str,
    reference: str,
) -> None:
    skill_root = repo_root / "skills" / name
    text = (skill_root / "SKILL.md").read_text(encoding="utf-8")

    assert (skill_root / reference).is_file()
    assert reference in text
    assert "SETUP.md" not in text
    assert "Agent(subagent_type=" not in text
    assert "/commands/" not in text


@pytest.mark.parametrize(
    "name",
    ("agent-workflow-setup", "agent-workflow-migrate"),
)
def test_management_skill_resolves_persistent_manager_in_order(
    repo_root: Path,
    name: str,
) -> None:
    text = (
        repo_root / "skills" / name / "SKILL.md"
    ).read_text(encoding="utf-8")

    path_command = text.index("agent-workflow` on `PATH")
    archive = text.index(".agents/workflow/agent-workflow.pyz")
    assert path_command < archive
