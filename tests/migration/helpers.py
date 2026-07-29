from __future__ import annotations

from pathlib import Path

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.model import ProjectProfile, Scope


def fake_adapter_context(
    *,
    home: Path,
    project: Path | None,
) -> AdapterContext:
    home.mkdir(parents=True, exist_ok=True)
    if project is None:
        scope = Scope.GLOBAL
        profile = None
        neutral_root = home / ".agents"
    else:
        project.mkdir(parents=True, exist_ok=True)
        scope = Scope.PROJECT
        profile = ProjectProfile.LOCAL
        neutral_root = project / ".agents"
    return AdapterContext(
        home=home,
        project_root=project,
        neutral_root=neutral_root,
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def populated_mixed_context(tmp_path: Path) -> AdapterContext:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "wrap.md").write_text(
        "Create a session note.\n",
        encoding="utf-8",
    )
    (home / ".codex" / "memory").mkdir(parents=True)
    (home / ".codex" / "memory" / "preferences.md").write_text(
        "Prefer portable workflows.\n",
        encoding="utf-8",
    )
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (project / "AGENTS.md").write_text(
        "Project rules.\n",
        encoding="utf-8",
    )
    return fake_adapter_context(home=home, project=project)
