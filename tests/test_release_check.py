from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

from scripts.release_check import (
    build_release_artifact,
    release_steps,
)


def test_release_steps_keep_required_fail_fast_order() -> None:
    assert [step.name for step in release_steps("python")] == [
        "portable skill lint",
        "documentation and forbidden content",
        "unit and migration tests",
        "setup and migration goldens",
        "transaction fault injection",
        "installed artifact tests",
    ]


def test_release_artifact_is_reproducible_and_checksummed(
    tmp_path: Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first, first_checksum, first_digest = build_release_artifact(
        first_dir,
        Path.cwd(),
    )
    second, second_checksum, second_digest = build_release_artifact(
        second_dir,
        Path.cwd(),
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == second_digest == hashlib.sha256(
        first.read_bytes()
    ).hexdigest()
    assert (
        first_checksum.read_text(encoding="utf-8")
        == second_checksum.read_text(encoding="utf-8")
        == f"{first_digest}  agent-workflow.pyz\n"
    )
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
