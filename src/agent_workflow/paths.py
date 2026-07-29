from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping, Sequence

from .model import ROOT_IDS, normalize_relative_path


@dataclass(frozen=True)
class HostPaths:
    home: Path
    cwd: Path
    project_root: Path | None

    @classmethod
    def discover(cls, home: Path, cwd: Path) -> "HostPaths":
        resolved_home = home.resolve(strict=False)
        resolved_cwd = cwd.resolve(strict=False)
        return cls(
            home=resolved_home,
            cwd=resolved_cwd,
            project_root=_find_project_root(resolved_cwd),
        )


def resolve_write_target(
    root_id: str,
    relative_path: str,
    target_roots: Mapping[str, Path],
    allowed_roots: Sequence[Path],
) -> Path:
    if root_id not in ROOT_IDS or root_id not in target_roots:
        raise ValueError(f"unknown root ID: {root_id}")

    normalized_path = normalize_relative_path(relative_path)
    logical_allowed_roots = tuple(_absolute_path(root) for root in allowed_roots)
    resolved_allowed_roots = tuple(root.resolve(strict=False) for root in logical_allowed_roots)
    if not resolved_allowed_roots:
        raise ValueError("allowed roots must not be empty")

    target_root = _absolute_path(target_roots[root_id])
    target = target_root.joinpath(*normalized_path.split("/"))
    _reject_escaping_symlinks(target, logical_allowed_roots, resolved_allowed_roots)

    resolved_target_root = target_root.resolve(strict=False)
    if not _is_within_any(resolved_target_root, resolved_allowed_roots):
        raise ValueError("target root is outside allowed roots")

    resolved_target = target.resolve(strict=False)
    if not _is_within_any(resolved_target, resolved_allowed_roots):
        raise ValueError("target is outside allowed roots")
    if any(resolved_target == root for root in resolved_allowed_roots):
        raise ValueError("target must not equal an allowed root")
    return resolved_target


def _find_project_root(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        marker = candidate / ".git"
        if marker.is_dir() or marker.is_file():
            return candidate
    return None


def _is_within_any(path: Path, roots: Sequence[Path]) -> bool:
    return any(_is_within(path, root) for root in roots)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _absolute_path(path: Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else Path.cwd() / path


def _reject_escaping_symlinks(
    target: Path,
    logical_allowed_roots: Sequence[Path],
    resolved_allowed_roots: Sequence[Path],
) -> None:
    boundaries = [
        root for root in logical_allowed_roots if _is_within(target, root)
    ]
    if not boundaries:
        return

    boundary = max(boundaries, key=lambda root: len(root.parts))
    current = boundary
    for part in target.relative_to(boundary).parts:
        current /= part
        if current.is_symlink() and not _is_within_any(
            current.resolve(strict=False), resolved_allowed_roots
        ):
            raise ValueError("symlink escapes allowed roots")
        if not current.exists() and not current.is_symlink():
            break
