from __future__ import annotations


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="regenerate reviewed migration golden snapshots",
    )
