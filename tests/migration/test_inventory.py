from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.adapters.registry import AdapterRegistry
from agent_workflow.migration.inventory import scan_migration_inventory
from agent_workflow.migration.model import ArtifactKind, ArtifactScope
from tests.migration.helpers import (
    fake_adapter_context,
    populated_mixed_context,
)


def test_scans_claude_and_codex_without_reading_outside_declared_roots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "wrap.md").write_text(
        "Create a session note.",
        encoding="utf-8",
    )
    project.mkdir()
    (project / "AGENTS.md").write_text("Project rules.", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be scanned", encoding="utf-8")

    inventory = scan_migration_inventory(
        context=fake_adapter_context(home=home, project=project),
        adapters=AdapterRegistry.builtins().require(("claude", "codex")),
    )

    assert {
        (item.agent_id, item.kind, item.scope)
        for item in inventory.artifacts
    } == {
        ("claude", ArtifactKind.COMMAND, ArtifactScope.GLOBAL),
        ("codex", ArtifactKind.RULES, ArtifactScope.PROJECT),
    }
    assert all(item.path != outside for item in inventory.artifacts)
    assert all(len(item.sha256) == 64 for item in inventory.artifacts)


def test_inventory_order_is_stable(tmp_path: Path) -> None:
    context = populated_mixed_context(tmp_path)
    registry = AdapterRegistry.builtins()

    first = scan_migration_inventory(
        context, registry.require(("codex", "claude"))
    )
    second = scan_migration_inventory(
        context, registry.require(("claude", "codex"))
    )

    assert first.to_json() == second.to_json()


def test_portable_inventory_json_omits_absolute_paths(tmp_path: Path) -> None:
    context = populated_mixed_context(tmp_path)

    inventory = scan_migration_inventory(
        context,
        AdapterRegistry.builtins().require(("claude", "codex")),
    )
    serialized = inventory.to_json()
    payload = json.loads(serialized)

    assert str(tmp_path) not in serialized
    assert tmp_path.as_posix() not in serialized
    assert all("path" not in item for item in payload["artifacts"])
    assert all("\\" not in item["relative_path"] for item in payload["artifacts"])


def test_manager_owned_generated_file_is_not_reimported(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    generated = home / ".codex" / "AGENTS.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("Generated rules.\n", encoding="utf-8")
    neutral = home / ".agents"
    neutral.mkdir()
    neutral.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator_version": "0.1.0",
                "scope": "global",
                "profile": None,
                "targets": ["codex"],
                "generated_files": {
                    "scope:.codex/AGENTS.md": "0" * 64,
                },
                "bootstrap_root": None,
            }
        ),
        encoding="utf-8",
    )

    inventory = scan_migration_inventory(
        fake_adapter_context(home=home, project=None),
        AdapterRegistry.builtins().require(("codex",)),
    )

    assert inventory.artifacts == ()


def test_escaping_declared_root_is_warned_and_skipped(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("wrap.md").write_text("unsafe", encoding="utf-8")
    commands = home / ".claude" / "commands"
    commands.parent.mkdir(parents=True)
    try:
        commands.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    inventory = scan_migration_inventory(
        fake_adapter_context(home=home, project=None),
        AdapterRegistry.builtins().require(("claude",)),
    )

    assert inventory.artifacts == ()
    assert any("escapes declared boundary" in item for item in inventory.warnings)
