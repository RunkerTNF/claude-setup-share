from __future__ import annotations

from pathlib import Path

from agent_workflow.adapters.base import AdapterContext, CapabilityStatus
from agent_workflow.adapters.claude.adapter import ClaudeAdapter
from agent_workflow.model import ProjectProfile, Scope


def make_context(
    tmp_path: Path,
    scope: Scope,
    profile: ProjectProfile | None = None,
) -> AdapterContext:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    neutral = (home / ".agents") if scope is Scope.GLOBAL else (repo / ".agents")
    neutral.mkdir()
    neutral.joinpath("memory").mkdir()
    neutral.joinpath("RULES.md").write_text("common rules\n", encoding="utf-8")
    neutral.joinpath("memory/MEMORY.md").write_text(
        "memory index\n", encoding="utf-8"
    )
    return AdapterContext(
        home=home,
        project_root=repo,
        neutral_root=neutral,
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def test_global_claude_uses_native_imports(tmp_path: Path) -> None:
    adapter_context = make_context(tmp_path, Scope.GLOBAL)
    overlay = adapter_context.neutral_root / "overlays/claude/RULES.md"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("Claude overlay\n", encoding="utf-8")

    operation = ClaudeAdapter().plan_entrypoints(adapter_context)[0]

    assert operation.root_id == "scope"
    assert operation.path.replace("\\", "/") == ".claude/CLAUDE.md"
    body = operation.content_bytes().decode()
    assert "@~/.agents/RULES.md" in body
    assert "@~/.agents/overlays/claude/RULES.md" in body
    assert "@~/.agents/memory/MEMORY.md" in body
    assert "# source-sha256:" in body


def test_global_claude_omits_missing_optional_overlay(tmp_path: Path) -> None:
    operation = ClaudeAdapter().plan_entrypoints(
        make_context(tmp_path, Scope.GLOBAL)
    )[0]

    assert "@~/.agents/overlays/claude/RULES.md" not in (
        operation.content_bytes().decode()
    )


def test_local_project_uses_claude_local(tmp_path: Path) -> None:
    operation = ClaudeAdapter().plan_entrypoints(
        make_context(tmp_path, Scope.PROJECT, ProjectProfile.LOCAL)
    )[0]

    assert operation.root_id == "scope"
    assert operation.path == "CLAUDE.local.md"
    body = operation.content_bytes().decode()
    assert "@.agents/RULES.md" in body
    assert "@.agents/memory/MEMORY.md" in body


def test_shared_and_split_project_profiles_use_claude_md(
    tmp_path: Path,
) -> None:
    for profile in (ProjectProfile.SHARED, ProjectProfile.SPLIT):
        root = tmp_path / profile.value
        root.mkdir()
        operation = ClaudeAdapter().plan_entrypoints(
            make_context(root, Scope.PROJECT, profile)
        )[0]
        assert operation.path == "CLAUDE.md"


def test_claude_capability_baseline_and_wrapper_locations_are_explicit() -> None:
    manifest = ClaudeAdapter().manifest

    assert set(manifest.capabilities.values()) == {
        CapabilityStatus.SUPPORTED
    }
    assert manifest.supported_versions == ()
    assert [
        (location.path, location.mode)
        for location in manifest.global_config.skill_locations
    ] == [(".claude/skills", "wrapper")]
    assert [
        (location.path, location.mode)
        for location in manifest.project_config.skill_locations
    ] == [(".claude/skills", "wrapper")]


def test_claude_validation_detects_missing_and_drifted_entrypoint(
    tmp_path: Path,
) -> None:
    adapter = ClaudeAdapter()
    adapter_context = make_context(tmp_path, Scope.GLOBAL)

    assert [(item.code, item.path) for item in adapter.validate(adapter_context)] == [
        ("adapter.entrypoint-missing", "claude:.claude/CLAUDE.md")
    ]

    operation = adapter.plan_entrypoints(adapter_context)[0]
    target = adapter_context.home / operation.path
    target.parent.mkdir()
    target.write_text("drifted\n", encoding="utf-8")

    assert [(item.code, item.path) for item in adapter.validate(adapter_context)] == [
        ("adapter.entrypoint-drift", "claude:.claude/CLAUDE.md")
    ]
