from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .hashing import sha256_bytes
from .manifest import WorkflowManifest
from .model import Ownership, ProjectProfile, Scope
from .paths import HostPaths, resolve_write_target
from .plan import TransactionPlan, WriteOperation
from .profiles import plan_profile_files
from .resources import bundled_resource_source, load_bundled_resource


_GLOBAL_FILES = (
    ("RULES.md", "templates/core/global-rules.md", Ownership.CANONICAL),
    ("memory/MEMORY.md", "templates/core/global-memory-index.md", Ownership.CANONICAL),
)
_PROJECT_FILES = (
    ("RULES.md", "templates/core/project-rules.md", Ownership.CANONICAL),
    ("memory/MEMORY.md", "templates/core/project-memory-index.md", Ownership.CANONICAL),
    ("sessions/.gitkeep", None, Ownership.GENERATED),
)


def plan_neutral_init(
    paths: HostPaths,
    scope: Scope,
    profile: ProjectProfile | None,
    targets: tuple[str, ...],
    *,
    manage_syncprotect: bool = False,
) -> TransactionPlan:
    """Return a read-only, deterministic plan for a neutral agent workflow."""
    _validate_scope(scope, profile)
    normalized_targets = _normalize_targets(targets)
    scope_base = _scope_base(paths, scope)
    scope_root = scope_base / ".agents"
    target_roots = {"neutral": str(scope_root), "scope": str(scope_base)}

    desired, bootstrap_root = _desired_files(scope)
    manifest_path = resolve_write_target("neutral", "manifest.json", target_roots, (scope_base,))
    existing_manifest = _existing_manifest(manifest_path)
    if existing_manifest is not None and not _compatible(
        existing_manifest, scope, profile, normalized_targets
    ):
        raise ValueError("existing manifest is incompatible with requested layout")

    operations: list[WriteOperation] = []
    conflicts: list[str] = []
    for path, content, ownership in desired:
        target = resolve_write_target("neutral", path, target_roots, (scope_base,))
        snapshot = _file_snapshot(target)
        key = f"neutral:{path}"
        if not _can_write(existing_manifest, key, snapshot):
            kind = (
                "managed output modified"
                if existing_manifest is not None
                else "unmanaged non-empty output"
            )
            conflicts.append(f"{kind}: {key}")
            continue
        operations.append(
            WriteOperation.from_bytes(
                root_id="neutral",
                path=path,
                content=content,
                expected_sha256=snapshot.sha256,
                ownership=ownership,
            )
        )

    if scope is Scope.PROJECT:
        assert profile is not None
        operations.extend(
            plan_profile_files(
                scope_base,
                profile,
                manage_syncprotect=manage_syncprotect,
            )
        )

    if not conflicts:
        manifest = WorkflowManifest(
            schema_version=1,
            generator_version=__version__,
            scope=scope,
            profile=profile,
            targets=normalized_targets,
            generated_files={
                f"neutral:{path}": sha256_bytes(content)
                for path, content, _ in desired
            },
            bootstrap_root=str(bootstrap_root) if bootstrap_root is not None else None,
        )
        operations.append(
            WriteOperation.from_bytes(
                root_id="neutral",
                path="manifest.json",
                content=manifest.to_json().encode("utf-8"),
                expected_sha256=_file_snapshot(manifest_path).sha256,
                ownership=Ownership.GENERATED,
            )
        )

    return TransactionPlan.new(
        scope_root=str(scope_root),
        target_roots=target_roots,
        allowed_roots=(str(scope_base),),
        operations=tuple(operations),
        conflicts=tuple(sorted(conflicts)),
    )


def _validate_scope(scope: Scope, profile: ProjectProfile | None) -> None:
    if not isinstance(scope, Scope):
        raise ValueError("scope must be valid")
    if scope is Scope.GLOBAL and profile is not None:
        raise ValueError("global scope requires profile=None")
    if scope is Scope.PROJECT and not isinstance(profile, ProjectProfile):
        raise ValueError("project scope requires a project profile")


def _normalize_targets(targets: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(targets, tuple):
        raise ValueError("targets must be a tuple of names")
    normalized: set[str] = set()
    for target in targets:
        if not isinstance(target, str):
            raise ValueError("targets must contain non-empty names")
        name = target.strip().casefold()
        if not name or "/" in name or "\\" in name:
            raise ValueError("targets must contain non-empty names")
        normalized.add(name)
    return tuple(sorted(normalized))


def _scope_base(paths: HostPaths, scope: Scope) -> Path:
    if scope is Scope.GLOBAL:
        return paths.home.resolve(strict=False)
    if paths.project_root is None:
        raise ValueError("project scope requires a discovered project root")
    return paths.project_root.resolve(strict=False)


def _desired_files(scope: Scope) -> tuple[tuple[tuple[str, bytes, Ownership], ...], Path | None]:
    source_root: Path | None = None
    desired: list[tuple[str, bytes, Ownership]] = []
    definitions = _GLOBAL_FILES if scope is Scope.GLOBAL else _PROJECT_FILES
    for path, resource_path, ownership in definitions:
        if resource_path is None:
            desired.append((path, b"", ownership))
            continue
        content = load_bundled_resource(resource_path)
        loaded_from = bundled_resource_source(resource_path)
        if loaded_from is not None:
            source_root = loaded_from.resolve(strict=False)
        desired.append((path, content, ownership))
    return tuple(desired), source_root


def _existing_manifest(path: Path) -> WorkflowManifest | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("invalid existing manifest: manifest is not a file")
    try:
        return WorkflowManifest.from_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"invalid existing manifest: {error}") from error


def _compatible(
    manifest: WorkflowManifest,
    scope: Scope,
    profile: ProjectProfile | None,
    targets: tuple[str, ...],
) -> bool:
    return (
        manifest.schema_version == 1
        and manifest.scope is scope
        and manifest.profile is profile
        and manifest.targets == targets
    )


@dataclass(frozen=True)
class _FileSnapshot:
    sha256: str | None
    is_empty: bool


def _file_snapshot(path: Path) -> _FileSnapshot:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return _FileSnapshot(sha256=None, is_empty=True)
    except IsADirectoryError as error:
        raise ValueError(f"output is not a file: {path}") from error
    except OSError as error:
        raise ValueError(f"cannot read output while planning: {path}") from error
    return _FileSnapshot(sha256=sha256_bytes(content), is_empty=not content)


def _can_write(
    manifest: WorkflowManifest | None, key: str, snapshot: _FileSnapshot
) -> bool:
    if snapshot.sha256 is None:
        return True
    if manifest is None:
        return snapshot.is_empty
    return manifest.generated_files.get(key) == snapshot.sha256
