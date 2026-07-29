from __future__ import annotations

from pathlib import Path
import re


_PERSONAL_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/]Users[\\/](?!<)[^\\/\s]+"
    r"|/(?:home|Users)/(?!<)[^/\s]+)"
)
_TEXT_SUFFIXES = frozenset({".json", ".js", ".md", ".py", ".toml", ".txt"})


def test_home_claude_is_not_a_runtime_source(repo_root: Path) -> None:
    assert not (repo_root / "home-claude").exists()


def test_neutral_templates_have_no_agent_canonical_paths(
    repo_root: Path,
) -> None:
    forbidden = (
        ".claude/memory",
        ".claude/sessions",
        ".codex/memory",
        ".codex/sessions",
    )
    for path in (repo_root / "templates" / "core").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), path


def test_personal_absolute_paths_do_not_ship(repo_root: Path) -> None:
    shipped_roots = (
        repo_root / "skills",
        repo_root / "templates" / "core",
        repo_root / "src" / "agent_workflow",
    )
    for root in shipped_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in _TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            assert "Runker" not in text, path
            assert _PERSONAL_PATH.search(text) is None, path


def test_two_machine_workflow_is_optional_and_parameterized(
    repo_root: Path,
) -> None:
    example = (
        repo_root / "templates" / "examples" / "two-machine-workflow.md"
    )
    syncprotect = repo_root / "templates" / "examples" / "syncprotect"

    assert example.is_file()
    assert syncprotect.is_file()
    text = example.read_text(encoding="utf-8")
    assert "<sync-root>" in text
    assert "<corporate-machine>" in text
    assert "Runker" not in text


def test_claude_optional_assets_are_sanitized(repo_root: Path) -> None:
    adapter = repo_root / "src" / "agent_workflow" / "adapters" / "claude"
    settings = adapter / "templates" / "settings.example.json"
    statusline = adapter / "assets" / "statusline.js"

    assert settings.is_file()
    assert statusline.is_file()
    for path in (settings, statusline):
        text = path.read_text(encoding="utf-8")
        assert "Runker" not in text
        assert _PERSONAL_PATH.search(text) is None
