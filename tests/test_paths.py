from pathlib import Path

import pytest

from agent_workflow.hashing import sha256_bytes, sha256_file
from agent_workflow.paths import HostPaths, resolve_write_target


def test_discover_finds_git_project_without_running_git(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()

    paths = HostPaths.discover(home=tmp_path / "home", cwd=nested)

    assert paths.project_root == root.resolve()


def test_discover_accepts_git_file_as_project_marker(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    nested = root / "src"
    nested.mkdir(parents=True)
    (root / ".git").write_text("gitdir: /elsewhere")

    paths = HostPaths.discover(home=tmp_path / "home", cwd=nested)

    assert paths.project_root == root.resolve()


def test_target_outside_allowed_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside allowed roots"):
        resolve_write_target(
            "scope",
            "file",
            {
                "neutral": tmp_path / "home" / ".agents",
                "scope": tmp_path / "other",
            },
            [tmp_path / "home"],
        )


def test_unknown_root_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown root ID"):
        resolve_write_target(
            "unknown",
            "file",
            {"neutral": tmp_path / "home" / ".agents", "scope": tmp_path / "home"},
            [tmp_path / "home"],
        )


@pytest.mark.parametrize("relative_path", (".", "../file", "/file", r"C:\\file"))
def test_unsafe_relative_path_is_rejected(tmp_path: Path, relative_path: str) -> None:
    home = tmp_path / "home"
    with pytest.raises(ValueError, match="safe relative path"):
        resolve_write_target(
            "scope",
            relative_path,
            {"neutral": home / ".agents", "scope": home},
            [home],
        )


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    link = home / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ValueError, match="symlink"):
        resolve_write_target(
            "scope",
            "link/file",
            {"neutral": home / ".agents", "scope": home},
            [home],
        )


def test_target_root_symlink_escape_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    link = home / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ValueError, match="symlink"):
        resolve_write_target(
            "scope",
            "file",
            {"neutral": home / ".agents", "scope": link},
            [home],
        )


def test_hashing_returns_lowercase_digest_and_missing_file_is_none(tmp_path: Path) -> None:
    file_path = tmp_path / "content.bin"
    file_path.write_bytes(b"hello world")

    assert sha256_bytes(b"hello world") == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert sha256_file(file_path) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert sha256_file(tmp_path / "missing.bin") is None
