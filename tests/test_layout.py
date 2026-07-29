from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_workflow.resources as resources_module
from agent_workflow.layout import plan_neutral_init
from agent_workflow.model import Ownership, ProjectProfile, Scope
from agent_workflow.paths import HostPaths
from agent_workflow.resources import load_bundled_resource


def operation_paths(plan) -> set[str]:
    return {operation.path.replace("\\", "/") for operation in plan.operations}


def make_paths(tmp_path: Path, *, project: bool = True) -> HostPaths:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    if project:
        (repo / ".git").mkdir()
    return HostPaths.discover(home=home, cwd=repo)


def test_global_plan_contains_neutral_core_only(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    plan = plan_neutral_init(
        paths,
        scope=Scope.GLOBAL,
        profile=None,
        targets=(),
    )

    assert operation_paths(plan) == {
        "RULES.md",
        "manifest.json",
        "memory/MEMORY.md",
    }
    assert {operation.ownership for operation in plan.operations} == {
        Ownership.CANONICAL,
        Ownership.GENERATED,
    }
    assert plan.allowed_roots == (str(paths.home),)
    assert dict(plan.target_roots) == {
        "neutral": str(paths.home / ".agents"),
        "scope": str(paths.home),
    }


def test_project_plan_includes_sessions_and_profile(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    plan = plan_neutral_init(
        paths,
        scope=Scope.PROJECT,
        profile=ProjectProfile.SPLIT,
        targets=("Codex", "codex"),
    )

    assert "sessions/.gitkeep" in operation_paths(plan)
    assert next(
        operation
        for operation in plan.operations
        if operation.path == "sessions/.gitkeep"
    ).ownership is Ownership.GENERATED
    manifest_write = next(op for op in plan.operations if op.path == "manifest.json")
    manifest = json.loads(manifest_write.content_bytes())
    assert manifest["profile"] == "split"
    assert manifest["targets"] == ["codex"]
    assert set(manifest["generated_files"]) == {
        "neutral:RULES.md",
        "neutral:memory/MEMORY.md",
        "neutral:sessions/.gitkeep",
    }


def test_planning_is_deterministic_and_does_not_create_files(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    before = sorted(tmp_path.rglob("*"))

    first = plan_neutral_init(paths, Scope.GLOBAL, None, ("codex", "claude"))
    second = plan_neutral_init(paths, Scope.GLOBAL, None, ("claude", "CODEX"))

    assert first.to_json() == second.to_json()
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    ("scope", "profile"),
    ((Scope.GLOBAL, ProjectProfile.LOCAL), (Scope.PROJECT, None)),
)
def test_scope_profile_mismatches_are_rejected(
    tmp_path: Path, scope: Scope, profile: ProjectProfile | None
) -> None:
    paths = make_paths(tmp_path)

    with pytest.raises(ValueError, match="profile"):
        plan_neutral_init(paths, scope, profile, ())


def test_project_scope_requires_discovered_project_root(tmp_path: Path) -> None:
    paths = make_paths(tmp_path, project=False)

    with pytest.raises(ValueError, match="project root"):
        plan_neutral_init(paths, Scope.PROJECT, ProjectProfile.LOCAL, ())


def test_existing_unmanaged_nonempty_file_becomes_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    output = paths.home / ".agents" / "RULES.md"
    output.parent.mkdir()
    output.write_text("user rules\n", encoding="utf-8")

    plan = plan_neutral_init(paths, Scope.GLOBAL, None, ())

    assert "RULES.md" not in operation_paths(plan)
    assert plan.conflicts == ("unmanaged non-empty output: neutral:RULES.md",)
    assert "manifest.json" not in operation_paths(plan)


def test_existing_empty_unmanaged_rules_file_is_safe_to_initialize(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    output = paths.home / ".agents" / "RULES.md"
    output.parent.mkdir()
    output.write_bytes(b"")

    plan = plan_neutral_init(paths, Scope.GLOBAL, None, ())

    rules_write = next(operation for operation in plan.operations if operation.path == "RULES.md")
    assert rules_write.expected_sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_existing_unmanaged_nonempty_session_marker_becomes_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    marker = paths.project_root / ".agents" / "sessions" / ".gitkeep"
    marker.parent.mkdir(parents=True)
    marker.write_text("personal session\n", encoding="utf-8")

    plan = plan_neutral_init(paths, Scope.PROJECT, ProjectProfile.LOCAL, ())

    assert "sessions/.gitkeep" not in operation_paths(plan)
    assert plan.conflicts == (
        "unmanaged non-empty output: neutral:sessions/.gitkeep",
    )


def test_modified_managed_file_becomes_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    initial = plan_neutral_init(paths, Scope.GLOBAL, None, ())
    root = paths.home / ".agents"
    for operation in initial.operations:
        target = root / operation.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(operation.content_bytes())
    (root / "RULES.md").write_text("edited\n", encoding="utf-8")

    plan = plan_neutral_init(paths, Scope.GLOBAL, None, ())

    assert "RULES.md" not in operation_paths(plan)
    assert plan.conflicts == ("managed output modified: neutral:RULES.md",)
    assert "manifest.json" not in operation_paths(plan)


def test_modified_managed_nonempty_session_marker_becomes_a_conflict(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    initial = plan_neutral_init(paths, Scope.PROJECT, ProjectProfile.LOCAL, ())
    root = paths.project_root / ".agents"
    for operation in initial.operations:
        target = root / operation.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(operation.content_bytes())
    (root / "sessions" / ".gitkeep").write_text("personal session\n", encoding="utf-8")

    plan = plan_neutral_init(paths, Scope.PROJECT, ProjectProfile.LOCAL, ())

    assert "sessions/.gitkeep" not in operation_paths(plan)
    assert plan.conflicts == (
        "managed output modified: neutral:sessions/.gitkeep",
    )


def test_invalid_existing_manifest_blocks_planning(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    manifest = paths.home / ".agents" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid existing manifest"):
        plan_neutral_init(paths, Scope.GLOBAL, None, ())


@pytest.mark.parametrize("path", ("/templates/core/global-rules.md", "templates/../core/global-rules.md", r"C:\\templates\\core\\global-rules.md"))
def test_resource_loader_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        load_bundled_resource(path)


def test_resource_loader_reads_source_checkout_template() -> None:
    assert load_bundled_resource("templates/core/global-rules.md")


def test_resource_loader_rejects_bundled_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_root = tmp_path / "package"
    bundled_root = package_root / "_bundled" / "templates" / "core"
    bundled_root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    link = bundled_root / "global-rules.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(resources_module.resources, "files", lambda _: package_root)

    with pytest.raises(ValueError, match="escapes bundled resources"):
        load_bundled_resource("templates/core/global-rules.md")


def test_resource_loader_does_not_infer_source_checkout_from_installed_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed_package = tmp_path / "site-packages" / "agent_workflow"
    installed_package.mkdir(parents=True)
    (tmp_path / "templates" / "core").mkdir(parents=True)
    (tmp_path / "templates" / "core" / "global-rules.md").write_text(
        "unrelated", encoding="utf-8"
    )
    monkeypatch.setattr(resources_module.resources, "files", lambda _: installed_package)
    monkeypatch.setattr(resources_module, "__file__", installed_package / "resources.py")

    with pytest.raises(FileNotFoundError, match="no bundled resource"):
        load_bundled_resource("templates/core/global-rules.md")
