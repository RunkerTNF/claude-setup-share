from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
from typing import Iterable

from agent_workflow.adapters.base import (
    AdapterContext,
    AgentAdapter,
    InventoryRoot,
)
from agent_workflow.manifest import WorkflowManifest
from agent_workflow.model import Scope

from .model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    MigrationInventory,
    Sensitivity,
    derive_artifact_id,
)


@dataclass(frozen=True)
class _DeclaredRoot:
    agent_id: str
    root: InventoryRoot
    boundary: Path
    label: str


def scan_migration_inventory(
    context: AdapterContext,
    adapters: Iterable[AgentAdapter],
) -> MigrationInventory:
    warnings: list[str] = []
    declared = _declared_roots(context, adapters, warnings)
    manager_owned = _manager_owned_paths(context, warnings)
    neutral_roots = _neutral_roots(context)
    artifacts: list[ArtifactRecord] = []
    seen_candidates: set[tuple[str, str, str]] = set()

    for item in sorted(
        declared,
        key=lambda value: (
            -len(value.root.path.parts),
            value.agent_id,
            value.root.scope.value,
            value.label,
        ),
    ):
        candidates = _root_candidates(item, warnings)
        for candidate in candidates:
            resolved = _safe_resolve(candidate)
            if resolved is None:
                warnings.append(f"{item.label}: source path cannot be resolved")
                continue
            identity = (
                item.agent_id,
                item.root.scope.value,
                str(resolved).casefold(),
            )
            if identity in seen_candidates:
                continue
            seen_candidates.add(identity)
            if resolved in manager_owned:
                continue
            record = _record_artifact(
                item,
                candidate,
                neutral_roots,
                warnings,
            )
            if record is not None:
                artifacts.append(record)

    return MigrationInventory(
        schema_version=1,
        roots=tuple(item.label for item in declared),
        artifacts=tuple(artifacts),
        warnings=tuple(warnings),
    )


def _declared_roots(
    context: AdapterContext,
    adapters: Iterable[AgentAdapter],
    warnings: list[str],
) -> tuple[_DeclaredRoot, ...]:
    output: list[_DeclaredRoot] = []
    for adapter in sorted(adapters, key=lambda item: item.id):
        inventory_roots = getattr(adapter, "inventory_roots", None)
        if not callable(inventory_roots):
            warnings.append(
                f"{adapter.id}: adapter has no migration inventory roots"
            )
            continue
        for root in inventory_roots(context):
            boundary = _boundary_for(context, root.scope)
            relative = _logical_relative(root.path, boundary)
            if relative is None:
                warnings.append(
                    f"{adapter.id}:{root.scope.value}: "
                    "declared root is outside its boundary"
                )
                continue
            label_path = relative.as_posix()
            label = f"{adapter.id}:{root.scope.value}:{label_path}"
            output.append(
                _DeclaredRoot(
                    agent_id=adapter.id,
                    root=root,
                    boundary=boundary,
                    label=label,
                )
            )
    return tuple(output)


def _root_candidates(
    item: _DeclaredRoot,
    warnings: list[str],
) -> tuple[Path, ...]:
    path = item.root.path
    if not path.exists() and not path.is_symlink():
        return ()
    resolved = _safe_resolve(path)
    boundary = _safe_resolve(item.boundary)
    if (
        resolved is None
        or boundary is None
        or not _is_within(resolved, boundary)
    ):
        warnings.append(f"{item.label}: path escapes declared boundary")
        return ()
    if path.is_file():
        return (path,)
    if not path.is_dir():
        warnings.append(f"{item.label}: path is not a regular file or directory")
        return ()
    if item.root.kind == ArtifactKind.SKILL.value:
        return _skill_directories(item, warnings)
    return _matching_files(item, warnings)


def _matching_files(
    item: _DeclaredRoot,
    warnings: list[str],
) -> tuple[Path, ...]:
    output: list[Path] = []
    stack = [item.root.path]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        resolved_current = _safe_resolve(current)
        resolved_boundary = _safe_resolve(item.boundary)
        if (
            resolved_current is None
            or resolved_boundary is None
            or not _is_within(resolved_current, resolved_boundary)
        ):
            warnings.append(f"{item.label}: child path escapes declared boundary")
            continue
        identity = str(resolved_current).casefold()
        if identity in visited:
            continue
        visited.add(identity)
        try:
            children = sorted(
                current.iterdir(), key=lambda path: path.name.casefold()
            )
        except OSError:
            warnings.append(f"{item.label}: directory cannot be read")
            continue
        for child in children:
            resolved_child = _safe_resolve(child)
            if (
                resolved_child is None
                or not _is_within(resolved_child, resolved_boundary)
            ):
                warnings.append(
                    f"{item.label}: child path escapes declared boundary"
                )
                continue
            if child.is_dir():
                if item.root.recursive:
                    stack.append(child)
                continue
            if not child.is_file():
                warnings.append(f"{item.label}: non-regular child was skipped")
                continue
            relative = child.relative_to(item.root.path).as_posix()
            if _matches(relative, item.root.include_globs):
                output.append(child)
    return tuple(sorted(output, key=lambda path: path.as_posix()))


def _skill_directories(
    item: _DeclaredRoot,
    warnings: list[str],
) -> tuple[Path, ...]:
    output: list[Path] = []
    stack = [item.root.path]
    visited: set[str] = set()
    resolved_boundary = _safe_resolve(item.boundary)
    if resolved_boundary is None:
        return ()
    while stack:
        current = stack.pop()
        resolved_current = _safe_resolve(current)
        if (
            resolved_current is None
            or not _is_within(resolved_current, resolved_boundary)
        ):
            warnings.append(f"{item.label}: child path escapes declared boundary")
            continue
        identity = str(resolved_current).casefold()
        if identity in visited:
            continue
        visited.add(identity)
        skill_file = current / "SKILL.md"
        if current != item.root.path and _safe_regular_file(
            skill_file, resolved_boundary
        ):
            output.append(current)
            continue
        if current != item.root.path and not item.root.recursive:
            continue
        try:
            children = sorted(
                (path for path in current.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
        except OSError:
            warnings.append(f"{item.label}: directory cannot be read")
            continue
        stack.extend(reversed(children))
    return tuple(sorted(output, key=lambda path: path.as_posix()))


def _record_artifact(
    declared: _DeclaredRoot,
    candidate: Path,
    neutral_roots: tuple[Path, ...],
    warnings: list[str],
) -> ArtifactRecord | None:
    relative = _logical_relative(candidate, declared.boundary)
    if relative is None:
        warnings.append(f"{declared.label}: artifact escapes declared boundary")
        return None
    if candidate.is_dir():
        hashed = _hash_directory(candidate, declared.boundary)
        if hashed is None:
            warnings.append(f"{declared.label}: skill directory is unsafe")
            return None
        digest, size = hashed
        media_type = "application/vnd.agent-skill.directory"
    else:
        try:
            content = candidate.read_bytes()
        except OSError:
            warnings.append(f"{declared.label}: artifact cannot be read")
            return None
        digest = hashlib.sha256(content).hexdigest()
        size = len(content)
        media_type = _media_type(candidate)
    scope = ArtifactScope(declared.root.scope.value)
    relative_path = relative.as_posix()
    artifact_id = derive_artifact_id(
        agent_id=declared.agent_id,
        scope=scope,
        relative_path=relative_path,
        source_sha256=digest,
    )
    resolved = candidate.resolve(strict=False)
    return ArtifactRecord(
        artifact_id=artifact_id,
        agent_id=declared.agent_id,
        kind=ArtifactKind(declared.root.kind),
        scope=scope,
        path=resolved,
        relative_path=relative_path,
        sha256=digest,
        media_type=media_type,
        size_bytes=size,
        sensitivity=Sensitivity.SAFE,
        already_neutral=any(
            _is_within(resolved, neutral_root) for neutral_root in neutral_roots
        ),
    )


def _hash_directory(
    root: Path,
    boundary: Path,
) -> tuple[str, int] | None:
    resolved_boundary = _safe_resolve(boundary)
    resolved_root = _safe_resolve(root)
    if (
        resolved_boundary is None
        or resolved_root is None
        or not _is_within(resolved_root, resolved_boundary)
    ):
        return None
    files: list[tuple[str, bytes]] = []
    stack = [root]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        resolved_current = _safe_resolve(current)
        if (
            resolved_current is None
            or not _is_within(resolved_current, resolved_boundary)
        ):
            return None
        identity = str(resolved_current).casefold()
        if identity in visited:
            return None
        visited.add(identity)
        try:
            children = sorted(
                current.iterdir(), key=lambda path: path.name.casefold()
            )
        except OSError:
            return None
        for child in children:
            resolved_child = _safe_resolve(child)
            if (
                resolved_child is None
                or not _is_within(resolved_child, resolved_boundary)
            ):
                return None
            if child.is_dir():
                stack.append(child)
                continue
            if not child.is_file():
                return None
            try:
                content = child.read_bytes()
            except OSError:
                return None
            files.append((child.relative_to(root).as_posix(), content))
    digest = hashlib.sha256()
    total_size = 0
    for relative_path, content in sorted(files):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        total_size += len(content)
    return digest.hexdigest(), total_size


def _manager_owned_paths(
    context: AdapterContext,
    warnings: list[str],
) -> frozenset[Path]:
    output: set[Path] = set()
    for neutral_root in _neutral_roots(context):
        manifest_path = neutral_root / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        try:
            manifest = WorkflowManifest.from_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError):
            label = _portable_root_label(context, neutral_root)
            warnings.append(f"{label}: workflow manifest is invalid")
            continue
        scope_root = (
            context.home
            if manifest.scope is Scope.GLOBAL
            else context.project_root
        )
        for generated_key in manifest.generated_files:
            root_id, relative_path = generated_key.split(":", 1)
            base = neutral_root if root_id == "neutral" else scope_root
            if base is None:
                continue
            output.add(
                base.joinpath(*relative_path.split("/")).resolve(strict=False)
            )
    return frozenset(output)


def _neutral_roots(context: AdapterContext) -> tuple[Path, ...]:
    candidates = {
        context.neutral_root.resolve(strict=False),
        (context.home / ".agents").resolve(strict=False),
    }
    if context.project_root is not None:
        candidates.add((context.project_root / ".agents").resolve(strict=False))
    return tuple(sorted(candidates, key=lambda path: path.as_posix()))


def _boundary_for(context: AdapterContext, scope: Scope) -> Path:
    if scope is Scope.GLOBAL:
        return context.home
    if context.project_root is None:
        raise ValueError("project inventory root requires a project root")
    return context.project_root


def _portable_root_label(context: AdapterContext, root: Path) -> str:
    for label, boundary in (
        ("global", context.home),
        ("project", context.project_root),
    ):
        if boundary is None:
            continue
        relative = _logical_relative(root, boundary)
        if relative is not None:
            return f"{label}:{relative.as_posix()}"
    return "workflow"


def _logical_relative(path: Path, boundary: Path) -> Path | None:
    try:
        return path.relative_to(boundary)
    except ValueError:
        return None


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def _safe_regular_file(path: Path, resolved_boundary: Path) -> bool:
    resolved = _safe_resolve(path)
    return (
        resolved is not None
        and _is_within(resolved, resolved_boundary)
        and path.is_file()
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _matches(relative_path: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return True
    portable = PurePosixPath(relative_path)
    return any(portable.match(pattern) for pattern in patterns)


def _media_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown",
        ".toml": "application/toml",
        ".txt": "text/plain",
        ".py": "text/x-python",
        ".js": "text/javascript",
    }.get(path.suffix.casefold(), "application/octet-stream")
