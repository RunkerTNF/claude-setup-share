from __future__ import annotations

from pathlib import Path

import pytest

from agent_workflow.hashing import sha256_bytes
from agent_workflow.model import Ownership, ProjectProfile, Scope
from agent_workflow.paths import HostPaths
from agent_workflow.profiles import (
    plan_profile_files,
    policy_for,
    render_managed_ignore,
)


def test_local_profile_ignores_all_project_workflow_state() -> None:
    policy = policy_for(ProjectProfile.LOCAL)

    assert policy.gitignore_entries == (
        ".agents/",
        "AGENTS.override.md",
        "CLAUDE.local.md",
    )
    assert (
        policy.share_rules,
        policy.share_memory,
        policy.share_sessions,
        policy.share_skills,
    ) == (False, False, False, False)


def test_split_profile_keeps_shared_rules_and_skills() -> None:
    policy = policy_for(ProjectProfile.SPLIT)

    assert policy.gitignore_entries == (
        ".agents/memory/",
        ".agents/sessions/",
        ".agents/overlays/",
        "AGENTS.override.md",
        "CLAUDE.local.md",
    )
    assert (
        policy.share_rules,
        policy.share_memory,
        policy.share_sessions,
        policy.share_skills,
    ) == (True, False, False, True)


def test_shared_profile_has_no_generated_ignores() -> None:
    policy = policy_for(ProjectProfile.SHARED)

    assert policy.gitignore_entries == ()
    assert (
        policy.share_rules,
        policy.share_memory,
        policy.share_sessions,
        policy.share_skills,
    ) == (True, True, True, True)


def test_managed_block_replaces_only_its_previous_content() -> None:
    existing = (
        "dist/\n"
        "# BEGIN agent-workflow\n"
        "old/\n"
        "# END agent-workflow\n"
    )

    rendered = render_managed_ignore(
        existing, policy_for(ProjectProfile.LOCAL)
    )

    assert rendered.startswith("dist/\n")
    assert rendered.count("# BEGIN agent-workflow") == 1
    assert "old/" not in rendered
    assert ".agents/" in rendered


def test_shared_profile_removes_managed_block_and_preserves_crlf() -> None:
    existing = (
        "dist/\r\n"
        "# BEGIN agent-workflow\r\n"
        "old/\r\n"
        "# END agent-workflow\r\n"
        "coverage/\r\n"
    )

    rendered = render_managed_ignore(
        existing, policy_for(ProjectProfile.SHARED)
    )

    assert rendered == "dist/\r\ncoverage/\r\n"


def test_malformed_managed_block_is_rejected() -> None:
    with pytest.raises(ValueError, match="managed ignore block"):
        render_managed_ignore(
            "# BEGIN agent-workflow\nold/\n",
            policy_for(ProjectProfile.LOCAL),
        )


def test_profile_plan_updates_full_files_with_old_hash(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    gitignore = project / ".gitignore"
    syncprotect = project / ".syncprotect"
    gitignore.write_text("dist/\n", encoding="utf-8")
    syncprotect.write_text("docs/\n", encoding="utf-8")

    operations = plan_profile_files(
        project,
        ProjectProfile.SPLIT,
        manage_syncprotect=False,
    )

    assert [(operation.root_id, operation.path) for operation in operations] == [
        ("scope", ".gitignore"),
        ("scope", ".syncprotect"),
    ]
    assert operations[0].expected_sha256 == sha256_bytes(
        gitignore.read_bytes()
    )
    assert operations[1].expected_sha256 == sha256_bytes(
        syncprotect.read_bytes()
    )
    assert {operation.ownership for operation in operations} == {
        Ownership.GENERATED
    }
    assert operations[0].content_bytes().startswith(gitignore.read_bytes())
    assert operations[1].content_bytes().startswith(syncprotect.read_bytes())


def test_syncprotect_is_created_only_when_requested(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()

    without_syncprotect = plan_profile_files(
        project,
        ProjectProfile.LOCAL,
        manage_syncprotect=False,
    )
    with_syncprotect = plan_profile_files(
        project,
        ProjectProfile.LOCAL,
        manage_syncprotect=True,
    )

    assert [operation.path for operation in without_syncprotect] == [
        ".gitignore"
    ]
    assert [operation.path for operation in with_syncprotect] == [
        ".gitignore",
        ".syncprotect",
    ]


def test_project_layout_composes_profile_files(tmp_path: Path) -> None:
    from agent_workflow.layout import plan_neutral_init

    home = tmp_path / "home"
    project = tmp_path / "repo"
    home.mkdir()
    project.mkdir()
    (project / ".git").mkdir()
    paths = HostPaths.discover(home=home, cwd=project)

    plan = plan_neutral_init(
        paths,
        Scope.PROJECT,
        ProjectProfile.LOCAL,
        (),
        manage_syncprotect=True,
    )

    assert {
        (operation.root_id, operation.path) for operation in plan.operations
    } >= {
        ("scope", ".gitignore"),
        ("scope", ".syncprotect"),
    }
