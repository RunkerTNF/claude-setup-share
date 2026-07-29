from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import apply_setup_fixture, assert_tree_matches


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_global_setup_matches_golden(
    tmp_path: Path,
    agent: str,
) -> None:
    actual = apply_setup_fixture(
        tmp_path,
        agent=agent,
        profile=None,
    )
    expected = Path("tests/golden") / agent / "global"

    assert_tree_matches(actual, expected)


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("profile", ["local", "shared", "split"])
def test_project_setup_matches_golden(
    tmp_path: Path,
    agent: str,
    profile: str,
) -> None:
    actual = apply_setup_fixture(
        tmp_path,
        agent=agent,
        profile=profile,
    )
    expected = Path("tests/golden") / agent / f"project-{profile}"

    assert_tree_matches(actual, expected)
