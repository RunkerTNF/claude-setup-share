from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    apply_setup_fixture,
    assert_tree_matches,
    update_tree_golden,
)


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_global_setup_matches_golden(
    tmp_path: Path,
    agent: str,
    pytestconfig: pytest.Config,
) -> None:
    actual = apply_setup_fixture(
        tmp_path,
        agent=agent,
        profile=None,
    )
    expected = Path("tests/golden") / agent / "global"

    if pytestconfig.getoption("--update-goldens"):
        update_tree_golden(actual, expected)
    assert_tree_matches(actual, expected)


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("profile", ["local", "shared", "split"])
def test_project_setup_matches_golden(
    tmp_path: Path,
    agent: str,
    profile: str,
    pytestconfig: pytest.Config,
) -> None:
    actual = apply_setup_fixture(
        tmp_path,
        agent=agent,
        profile=profile,
    )
    expected = Path("tests/golden") / agent / f"project-{profile}"

    if pytestconfig.getoption("--update-goldens"):
        update_tree_golden(actual, expected)
    assert_tree_matches(actual, expected)
