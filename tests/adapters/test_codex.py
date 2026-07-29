from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_workflow.adapters.base import AdapterContext, CapabilityStatus
from agent_workflow.adapters.codex.adapter import CodexAdapter
from agent_workflow.model import ProjectProfile, Scope


def context(
    tmp_path: Path,
    scope: Scope,
    profile: ProjectProfile | None = None,
) -> AdapterContext:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    home.mkdir()
    project.mkdir()
    neutral = (home / ".agents") if scope is Scope.GLOBAL else (project / ".agents")
    neutral.mkdir()
    neutral.joinpath("memory").mkdir()
    neutral.joinpath("RULES.md").write_text("common rules\n", encoding="utf-8")
    neutral.joinpath("memory/MEMORY.md").write_text(
        "memory index\n", encoding="utf-8"
    )
    return AdapterContext(
        home=home,
        project_root=project,
        neutral_root=neutral,
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def test_global_codex_entrypoint_references_neutral_rules(
    tmp_path: Path,
) -> None:
    operations = CodexAdapter().plan_entrypoints(
        context(tmp_path, Scope.GLOBAL)
    )

    assert len(operations) == 1
    assert operations[0].root_id == "scope"
    assert operations[0].path.replace("\\", "/") == ".codex/AGENTS.md"
    body = operations[0].content_bytes().decode()
    assert "~/.agents/RULES.md" in body
    assert "~/.agents/overlays/codex/RULES.md" in body
    assert "~/.agents/memory/MEMORY.md" in body
    assert "# source-sha256:" in body
    assert "agent-workflow 0.1.0" in body


def test_local_project_uses_override_and_preserves_root_agents_reference(
    tmp_path: Path,
) -> None:
    operations = CodexAdapter().plan_entrypoints(
        context(tmp_path, Scope.PROJECT, ProjectProfile.LOCAL)
    )

    assert len(operations) == 1
    assert operations[0].root_id == "scope"
    assert operations[0].path == "AGENTS.override.md"
    body = operations[0].content_bytes().decode()
    assert "Read `AGENTS.md` when it exists" in body
    assert ".agents/RULES.md" in body


def test_shared_and_split_project_profiles_use_agents_md(
    tmp_path: Path,
) -> None:
    for profile in (ProjectProfile.SHARED, ProjectProfile.SPLIT):
        root = tmp_path / profile.value
        root.mkdir()
        operation = CodexAdapter().plan_entrypoints(
            context(root, Scope.PROJECT, profile)
        )[0]
        assert operation.path == "AGENTS.md"


def test_codex_capability_baseline_is_explicit() -> None:
    manifest = CodexAdapter().manifest

    assert manifest.capabilities == {
        "commands": CapabilityStatus.PARTIAL,
        "hooks": CapabilityStatus.SUPPORTED,
        "mcp": CapabilityStatus.SUPPORTED,
        "permissions": CapabilityStatus.SUPPORTED,
        "rules": CapabilityStatus.SUPPORTED,
        "skills": CapabilityStatus.SUPPORTED,
        "subagents": CapabilityStatus.PARTIAL,
    }
    assert manifest.supported_versions == ()


def test_codex_detection_reports_unverified_version(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "agent_workflow.adapters.declarative.shutil.which",
        lambda executable: "/tools/codex",
    )
    monkeypatch.setattr(
        "agent_workflow.adapters.declarative.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="codex-cli 9.9.9\n", stderr=""
        ),
    )

    detection = CodexAdapter().detect(context(tmp_path, Scope.GLOBAL))

    assert detection.installed is True
    assert detection.executable == "/tools/codex"
    assert detection.version == "codex-cli 9.9.9"
    assert detection.warning == "detected version has not been release-smoke verified"


def test_codex_validation_detects_missing_and_drifted_entrypoint(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    adapter_context = context(tmp_path, Scope.GLOBAL)

    missing = adapter.validate(adapter_context)
    assert [(item.code, item.path) for item in missing] == [
        ("adapter.entrypoint-missing", "codex:.codex/AGENTS.md")
    ]

    operation = adapter.plan_entrypoints(adapter_context)[0]
    target = adapter_context.home / operation.path
    target.parent.mkdir()
    target.write_text("drifted\n", encoding="utf-8")

    drifted = adapter.validate(adapter_context)
    assert [(item.code, item.path) for item in drifted] == [
        ("adapter.entrypoint-drift", "codex:.codex/AGENTS.md")
    ]


def test_codex_validation_reports_unsafe_entrypoint_without_raising(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    adapter_context = context(tmp_path, Scope.GLOBAL)
    (adapter_context.home / ".codex/AGENTS.md").mkdir(parents=True)

    diagnostics = adapter.validate(adapter_context)

    assert [(item.code, item.path) for item in diagnostics] == [
        ("adapter.entrypoint-path", "codex:.codex/AGENTS.md")
    ]
