"""Reproducible packaging for the persistent workflow manager."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile


_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_TEXT_SUFFIXES = frozenset({".json", ".md", ".py", ".toml", ".txt"})
_MAIN = (
    "from agent_workflow.cli import main\n\n"
    "raise SystemExit(main())\n"
).encode("utf-8")
_BUNDLED_SKILLS = (
    "agent-workflow-migrate",
    "agent-workflow-setup",
)


def build_manager_zipapp(source_root: Path) -> bytes:
    """Build a deterministic, standard-library-only agent-workflow zipapp."""
    source_root = _safe_source_root(source_root)
    files: dict[str, bytes] = {"__main__.py": _MAIN}
    _add_tree(
        files,
        source_root / "src" / "agent_workflow",
        "agent_workflow",
    )
    _add_tree(
        files,
        source_root / "templates",
        "agent_workflow/_bundled/templates",
    )
    for skill_name in _BUNDLED_SKILLS:
        _add_tree(
            files,
            source_root / "skills" / skill_name,
            f"agent_workflow/_bundled/skills/{skill_name}",
        )

    output = BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[name])
    return output.getvalue()


def _safe_source_root(source_root: Path) -> Path:
    candidate = Path(source_root)
    if (
        candidate.is_symlink()
        or not candidate.is_dir()
        or not candidate.is_absolute()
    ):
        raise ValueError("source root must be a safe existing absolute directory")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(
            "source root must be a safe existing absolute directory"
        ) from error
    required = (
        resolved / "src" / "agent_workflow",
        resolved / "templates",
        *(
            resolved / "skills" / skill_name
            for skill_name in _BUNDLED_SKILLS
        ),
    )
    if any(
        not _safe_subdirectory(resolved, path)
        for path in required
    ):
        raise ValueError("source root is missing workflow package resources")
    return resolved


def _add_tree(
    files: dict[str, bytes],
    root: Path,
    archive_prefix: str,
) -> None:
    try:
        entries = sorted(
            root.rglob("*"),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    except OSError as error:
        raise ValueError(f"cannot package resource tree: {root}") from error
    for entry in entries:
        relative = entry.relative_to(root)
        if entry.is_symlink():
            raise ValueError(f"package resource is symlinked: {entry}")
        if "__pycache__" in relative.parts or entry.suffix in {".pyc", ".pyo"}:
            continue
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError(f"package resource is unsafe: {entry}")
        name = f"{archive_prefix}/{relative.as_posix()}"
        content = _packaged_content(entry)
        previous = files.get(name)
        if previous is not None and previous != content:
            raise ValueError(f"package resource collision: {name}")
        files[name] = content


def _safe_subdirectory(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or not current.is_dir():
            return False
    return True


def _packaged_content(path: Path) -> bytes:
    content = path.read_bytes()
    if path.suffix.casefold() not in _TEXT_SUFFIXES:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"text package resource is not UTF-8: {path}") from error
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
