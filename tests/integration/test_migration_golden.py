from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.doctor import run_doctor
from tests.migration.golden_helpers import (
    FIXTURE_NAMES,
    fixture_is_sanitized,
    golden_json,
    golden_text,
    run_fixture_migration,
    tree_snapshot,
    update_golden,
)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_migration_fixture_matches_golden_tree(
    fixture_name: str,
    tmp_path: Path,
    pytestconfig,
) -> None:
    assert fixture_is_sanitized(fixture_name)

    result = run_fixture_migration(fixture_name, tmp_path)
    if pytestconfig.getoption("--update-goldens"):
        update_golden(fixture_name, result)

    assert result.preview == golden_text(
        fixture_name,
        "preview.md",
    )
    assert result.tree == golden_json(fixture_name, "tree.json")
    assert run_doctor(result.install_root) == ()


def test_conflict_fixture_remains_dry_run_only(tmp_path: Path) -> None:
    result = run_fixture_migration("conflicts", tmp_path)

    assert result.applied is False
    assert "Blocking conflicts" in result.preview


def test_imported_rules_and_memory_are_discoverable(
    tmp_path: Path,
) -> None:
    result = run_fixture_migration("claude-only", tmp_path)

    assert "rules/" in result.tree["RULES.md"]["text"]
    assert "memory/IMPORTED.md" in result.tree[
        "memory/MEMORY.md"
    ]["text"]
    imported_index = result.tree["memory/IMPORTED.md"]["text"]
    assert "memory/preferences-from-claude.md" in imported_index


def test_tree_snapshot_ignores_runtime_bootstrap_source(
    tmp_path: Path,
) -> None:
    snapshots = []
    for name, bootstrap_root in (
        ("source", str(tmp_path / "checkout")),
        ("wheel", None),
    ):
        root = tmp_path / name
        root.mkdir()
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "bootstrap_root": bootstrap_root,
                    "generated_files": {},
                    "generator_version": "0.1.0",
                    "profile": None,
                    "schema_version": 1,
                    "scope": "global",
                    "targets": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        snapshots.append(tree_snapshot(root))

    assert snapshots[0] == snapshots[1]


def test_current_repository_fixture_keeps_full_legacy_shape() -> None:
    fixture = Path("tests/fixtures/legacy/current-repository")
    expected = {
        ".claude/CLAUDE.md",
        ".claude/settings.json",
        ".claude/statusline.js",
        ".claude/workitems-rendering.md",
        ".claude/agents/code-reviewer.md",
        ".claude/agents/plan-reviewer.md",
        ".claude/commands/backlog.md",
        ".claude/commands/feedback.md",
        ".claude/commands/init-claude.md",
        ".claude/commands/morning.md",
        ".claude/commands/my-reviews.md",
        ".claude/commands/pick.md",
        ".claude/commands/tasks.md",
        ".claude/commands/wrap.md",
        "SOURCE.md",
    }

    assert {
        path.relative_to(fixture).as_posix()
        for path in fixture.rglob("*")
        if path.is_file()
    } == expected
