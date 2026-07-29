from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="regenerate reviewed migration golden snapshots",
    )


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
