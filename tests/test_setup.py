from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.registry import builtin_registry
from agent_workflow.doctor import run_doctor
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.setup import (
    SetupRequest,
    build_setup_plan,
    detect_setup_targets,
)
from agent_workflow.transactions import apply_plan


def _global_request(
    tmp_path: Path,
    *,
    targets: tuple[str, ...] = ("claude", "codex"),
    adapter_sources: tuple[Path, ...] = (),
    trusted_adapter_ids: tuple[str, ...] = (),
) -> SetupRequest:
    home = tmp_path / "home"
    home.mkdir()
    return SetupRequest(
        home=home,
        project_root=None,
        source_root=Path.cwd(),
        scope=Scope.GLOBAL,
        profile=None,
        targets=targets,
        manage_syncprotect=False,
        adapter_sources=adapter_sources,
        trusted_adapter_ids=trusted_adapter_ids,
    )


def test_global_setup_composes_core_manager_skill_and_targets(
    tmp_path: Path,
) -> None:
    request = _global_request(tmp_path)

    plan = build_setup_plan(request)

    paths = {
        (operation.root_id, operation.path.replace("\\", "/"))
        for operation in plan.operations
    }
    assert ("neutral", "workflow/agent-workflow.pyz") in paths
    assert ("neutral", "skills/agent-workflow-setup/SKILL.md") in paths
    assert ("scope", ".claude/CLAUDE.md") in paths
    assert ("scope", ".codex/AGENTS.md") in paths
    assert (
        "scope",
        ".claude/skills/agent-workflow-setup/SKILL.md",
    ) in paths
    assert plan.conflicts == ()

    manifest_operation = next(
        operation
        for operation in plan.operations
        if operation.root_id == "neutral"
        and operation.path == "manifest.json"
    )
    manifest = json.loads(manifest_operation.content_bytes())
    assert manifest["targets"] == ["claude", "codex"]
    assert manifest["bootstrap_root"] is None
    assert "scope:.claude/CLAUDE.md" in manifest["generated_files"]
    assert "scope:.codex/AGENTS.md" in manifest["generated_files"]


def test_global_setup_installs_manager_skill_without_agent_target(
    tmp_path: Path,
) -> None:
    request = _global_request(tmp_path, targets=())

    plan = build_setup_plan(request)

    assert {
        operation.path for operation in plan.operations
    } >= {
        "workflow/agent-workflow.pyz",
        "skills/agent-workflow-setup/SKILL.md",
    }


def test_existing_unmanaged_native_entrypoint_is_a_conflict(
    tmp_path: Path,
) -> None:
    request = _global_request(tmp_path, targets=("codex",))
    entrypoint = request.home / ".codex" / "AGENTS.md"
    entrypoint.parent.mkdir()
    entrypoint.write_text("personal instructions\n", encoding="utf-8")

    plan = build_setup_plan(request)

    assert plan.conflicts == (
        "unmanaged generated output: scope:.codex/AGENTS.md",
    )
    assert not any(
        operation.path == "manifest.json"
        for operation in plan.operations
    )


def test_matching_manifest_allows_deterministic_setup_rerun(
    tmp_path: Path,
) -> None:
    request = _global_request(tmp_path, targets=("codex",))
    first = build_setup_plan(request)
    apply_plan(first)

    second = build_setup_plan(request)

    assert second.conflicts == ()
    assert {
        (operation.root_id, operation.path)
        for operation in first.operations
    } == {
        (operation.root_id, operation.path)
        for operation in second.operations
    }


def test_project_setup_requires_verified_global_manager(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    home.mkdir()
    project.mkdir()
    (project / ".git").mkdir()
    request = SetupRequest(
        home=home,
        project_root=project,
        source_root=Path.cwd(),
        scope=Scope.PROJECT,
        profile=ProjectProfile.SPLIT,
        targets=("codex",),
        manage_syncprotect=False,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )

    with pytest.raises(ValueError, match="global manager"):
        build_setup_plan(request)


def test_applied_global_setup_unlocks_project_setup(tmp_path: Path) -> None:
    global_request = _global_request(tmp_path, targets=("codex",))
    apply_plan(build_setup_plan(global_request))
    assert run_doctor(global_request.home / ".agents") == ()
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".git").mkdir()
    project_request = SetupRequest(
        home=global_request.home,
        project_root=project,
        source_root=Path.cwd(),
        scope=Scope.PROJECT,
        profile=ProjectProfile.LOCAL,
        targets=("codex",),
        manage_syncprotect=True,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )

    plan = build_setup_plan(project_request)

    assert plan.conflicts == ()
    assert {
        (operation.root_id, operation.path)
        for operation in plan.operations
    } >= {
        ("scope", ".gitignore"),
        ("scope", ".syncprotect"),
        ("scope", "AGENTS.override.md"),
    }
    apply_plan(plan)
    assert run_doctor(project / ".agents") == ()


def test_installed_manager_plans_project_without_checkout(
    tmp_path: Path,
) -> None:
    global_request = _global_request(tmp_path, targets=("codex",))
    apply_plan(build_setup_plan(global_request))
    manager = (
        global_request.home
        / ".agents"
        / "workflow"
        / "agent-workflow.pyz"
    )
    project = tmp_path / "standalone-project"
    project.mkdir()
    (project / ".git").mkdir()
    output = tmp_path / "project-plan.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(manager),
            "plan",
            "setup",
            "--scope",
            "project",
            "--profile",
            "local",
            "--target",
            "codex",
            "--home",
            str(global_request.home),
            "--cwd",
            str(project),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()


def test_explicit_declarative_adapter_is_copied_without_network(
    tmp_path: Path,
) -> None:
    source = Path("tests/fixtures/adapters/declarative")
    request = _global_request(
        tmp_path,
        targets=("fixture-agent",),
        adapter_sources=(source,),
    )

    plan = build_setup_plan(request)

    assert {
        operation.path for operation in plan.operations
    } >= {
        "workflow/adapters/fixture-agent/adapter.json",
        "workflow/adapters/fixture-agent/templates/project.md",
    }


def test_detection_uses_registry_in_stable_order(tmp_path: Path) -> None:
    context = AdapterContext(
        home=tmp_path,
        project_root=None,
        neutral_root=tmp_path / ".agents",
        scope=Scope.GLOBAL,
        profile=None,
        generator_version="0.1.0",
    )

    detections = detect_setup_targets(context, builtin_registry())

    assert [item.adapter_id for item in detections] == ["claude", "codex"]
