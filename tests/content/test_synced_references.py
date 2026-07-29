from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scripts.sync_skill_reference import synchronize


_SKILLS = ("morning", "tasks", "my-reviews", "feedback")


def _write_fixture(root: Path) -> None:
    canonical = root / "resources" / "workitems-rendering.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"# Canonical\n")
    for name in _SKILLS:
        destination = (
            root
            / "skills"
            / name
            / "references"
            / "workitems-rendering.md"
        )
        destination.parent.mkdir(parents=True)
        destination.write_bytes(canonical.read_bytes())


def test_check_mode_accepts_repository_copies(
    repo_root: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "sync_skill_reference.py"),
            "--check",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_synchronizer_detects_and_repairs_fixed_destinations(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path)
    drifted = (
        tmp_path
        / "skills"
        / "feedback"
        / "references"
        / "workitems-rendering.md"
    )
    drifted.write_bytes(b"drift\n")

    assert synchronize(tmp_path, write=False) is False
    assert synchronize(tmp_path, write=True) is True
    assert synchronize(tmp_path, write=False) is True
    for name in _SKILLS:
        assert (
            tmp_path
            / "skills"
            / name
            / "references"
            / "workitems-rendering.md"
        ).read_bytes() == b"# Canonical\n"


def test_synchronizer_rejects_escaping_reference_directory(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path)
    reference = (
        tmp_path
        / "skills"
        / "feedback"
        / "references"
        / "workitems-rendering.md"
    )
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    reference.unlink()
    reference.parent.rmdir()
    try:
        reference.parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        synchronize(tmp_path, write=True)
