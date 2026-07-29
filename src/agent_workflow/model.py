from __future__ import annotations

from enum import StrEnum
import re
from pathlib import PurePosixPath, PureWindowsPath


ROOT_IDS = frozenset({"neutral", "scope"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class Scope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"


class ProjectProfile(StrEnum):
    LOCAL = "local"
    SHARED = "shared"
    SPLIT = "split"


class Severity(StrEnum):
    BLOCKING = "blocking"
    CONFLICT = "conflict"
    WARNING = "warning"
    INFO = "info"


class Ownership(StrEnum):
    CANONICAL = "canonical"
    GENERATED = "generated"
    UNMANAGED = "unmanaged"


def validate_sha256(value: str, *, field: str = "SHA-256") -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a 64-character lowercase hexadecimal SHA-256")


def normalize_relative_path(path: str) -> str:
    """Return a portable relative path, rejecting both POSIX and Windows escapes."""
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("path must be a safe relative path")
    windows_path = PureWindowsPath(path)
    if (
        path.startswith(("/", "\\"))
        or PurePosixPath(path).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
    ):
        raise ValueError("path must be a safe relative path")

    parts: list[str] = []
    for part in re.split(r"[\\\\/]", path):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path must be a safe relative path")
        parts.append(part)
    if not parts:
        raise ValueError("path must be a safe relative path")
    return "/".join(parts)
