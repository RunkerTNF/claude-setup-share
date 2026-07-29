from __future__ import annotations

from pathlib import Path
import zipfile

from agent_workflow.model import Scope
from agent_workflow.package import build_manager_zipapp
from agent_workflow.portability import lint_skill
from agent_workflow.setup import SetupRequest, build_setup_plan


def test_migrate_skill_is_portable_and_encodes_safe_workflow() -> None:
    skill = Path("skills/agent-workflow-migrate")

    assert lint_skill(skill) == ()
    source = (skill / "SKILL.md").read_text(encoding="utf-8")
    required_order = (
        "read-only inventory",
        "artifact counts",
        "deterministic normalization",
        "redacted classification request",
        "enumerated artifact IDs",
        "validate-response",
        "preview",
        "explicit user confirmation",
        "doctor",
        "backup and rollback",
    )
    positions = [source.index(phrase) for phrase in required_order]
    assert positions == sorted(positions)
    assert "repository checkout may be deleted" in source
    assert ".agents/skills/agent-workflow-migrate/" in source
    assert "OpenAI API" not in source
    assert "Anthropic API" not in source


def test_zipapp_bundles_migrate_skill_and_contract(tmp_path: Path) -> None:
    archive = tmp_path / "agent-workflow.pyz"
    archive.write_bytes(build_manager_zipapp(Path.cwd()))

    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())

    prefix = "agent_workflow/_bundled/skills/agent-workflow-migrate/"
    assert prefix + "SKILL.md" in names
    assert prefix + "references/classification-contract.md" in names


def test_global_setup_materializes_migrate_skill(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    request = SetupRequest(
        home=home,
        project_root=None,
        source_root=Path.cwd(),
        scope=Scope.GLOBAL,
        profile=None,
        targets=(),
        manage_syncprotect=False,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )

    plan = build_setup_plan(request)

    paths = {
        (operation.root_id, operation.path)
        for operation in plan.operations
    }
    assert (
        "neutral",
        "skills/agent-workflow-migrate/SKILL.md",
    ) in paths
    assert (
        "neutral",
        "skills/agent-workflow-migrate/references/classification-contract.md",
    ) in paths
