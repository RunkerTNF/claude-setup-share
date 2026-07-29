"""Composition of persistent global and project workflow setup plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from . import __version__
from .adapters.base import AdapterContext, AdapterDetection, AgentAdapter
from .adapters.manifest import AdapterManifest
from .adapters.registry import AdapterRegistry, builtin_registry
from .adapters.rendered import safe_current_hash
from .hashing import sha256_bytes, sha256_runtime_normalized
from .layout import plan_neutral_init
from .manifest import WorkflowManifest
from .model import Ownership, ProjectProfile, Scope
from .package import build_manager_zipapp
from .paths import HostPaths
from .plan import TransactionPlan, WriteOperation
from .skills import (
    discover_portable_skills,
    plan_canonical_skill_install,
    plan_skill_install,
)


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROFILE_FILES = frozenset(
    {("scope", ".gitignore"), ("scope", ".syncprotect")}
)


@dataclass(frozen=True)
class SetupRequest:
    home: Path
    project_root: Path | None
    source_root: Path
    scope: Scope
    profile: ProjectProfile | None
    targets: tuple[str, ...]
    manage_syncprotect: bool
    adapter_sources: tuple[Path, ...]
    trusted_adapter_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scope, Scope):
            raise ValueError("setup scope must be valid")
        if self.scope is Scope.GLOBAL:
            if self.profile is not None or self.project_root is not None:
                raise ValueError(
                    "global setup requires no project root or profile"
                )
        elif (
            not isinstance(self.profile, ProjectProfile)
            or self.project_root is None
        ):
            raise ValueError(
                "project setup requires a project root and profile"
            )
        if not isinstance(self.manage_syncprotect, bool):
            raise ValueError("manage_syncprotect must be boolean")

        home = _safe_directory(self.home, "home")
        source = _safe_directory(self.source_root, "source root")
        project = None
        if self.project_root is not None:
            project = _safe_directory(self.project_root, "project root")
            marker = project / ".git"
            if not (marker.is_file() or marker.is_dir()):
                raise ValueError("project root must contain a .git marker")
        targets = _adapter_ids(self.targets, "targets")
        trusted = _adapter_ids(
            self.trusted_adapter_ids, "trusted adapter ids"
        )
        sources = tuple(
            _safe_directory(path, "adapter source")
            for path in self.adapter_sources
        )
        if len(set(sources)) != len(sources):
            raise ValueError("adapter sources must be unique")

        object.__setattr__(self, "home", home)
        object.__setattr__(self, "source_root", source)
        object.__setattr__(self, "project_root", project)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "trusted_adapter_ids", trusted)
        object.__setattr__(self, "adapter_sources", sources)


@dataclass(frozen=True)
class _ExternalAdapter:
    manifest: AdapterManifest
    package_root: Path
    has_python: bool


def detect_setup_targets(
    context: AdapterContext,
    registry: AdapterRegistry,
) -> tuple[AdapterDetection, ...]:
    """Detect explicitly registered setup targets in stable order."""
    return registry.detect_all(context)


def build_setup_plan(request: SetupRequest) -> TransactionPlan:
    """Compose neutral, manager, skill, profile, and adapter operations."""
    registry, external, registry_warnings = _setup_registry(request)
    adapters = registry.require(request.targets)
    paths = HostPaths(
        home=request.home,
        cwd=request.project_root or request.source_root,
        project_root=request.project_root,
    )
    base = plan_neutral_init(
        paths,
        scope=request.scope,
        profile=request.profile,
        targets=request.targets,
        manage_syncprotect=request.manage_syncprotect,
    )
    target_roots = {
        root_id: Path(path) for root_id, path in base.target_roots.items()
    }
    existing_manifest = _read_manifest(target_roots["neutral"])
    operations: dict[tuple[str, str], WriteOperation] = {}
    conflicts = list(base.conflicts)
    for operation in base.operations:
        if operation.root_id == "neutral" and operation.path == "manifest.json":
            continue
        _add_operation(operations, operation)

    context = AdapterContext(
        home=request.home,
        project_root=request.project_root,
        neutral_root=target_roots["neutral"],
        scope=request.scope,
        profile=request.profile,
        generator_version=__version__,
    )
    additions: list[WriteOperation] = []
    if request.scope is Scope.GLOBAL:
        additions.append(
            _write_operation(
                root_id="neutral",
                path="workflow/agent-workflow.pyz",
                content=build_manager_zipapp(request.source_root),
                target_roots=target_roots,
                ownership=Ownership.GENERATED,
            )
        )
        skills = discover_portable_skills(request.source_root / "skills")
    else:
        _verify_global_install(request.home)
        skills = discover_portable_skills(
            target_roots["neutral"] / "skills"
        )

    additions.extend(plan_canonical_skill_install(context, skills))
    for adapter in adapters:
        additions.extend(adapter.plan_entrypoints(context))
        additions.extend(plan_skill_install(adapter, context, skills))
    additions.extend(
        _external_package_operations(
            external,
            selected=frozenset(request.targets),
            target_roots=target_roots,
        )
    )

    for raw_operation in additions:
        operation = _with_safe_expected_hash(raw_operation, target_roots)
        conflict = _generated_conflict(
            operation,
            existing_manifest,
            request,
            target_roots,
        )
        if conflict is not None:
            conflicts.append(conflict)
        _add_operation(operations, operation)

    if not conflicts:
        generated_files = {
            f"{operation.root_id}:{operation.path}": sha256_runtime_normalized(
                operation.content_bytes(),
                home=(
                    request.home
                    if request.scope is Scope.GLOBAL
                    else None
                ),
                project=request.project_root,
            )
            for key, operation in sorted(operations.items())
            if key not in _PROFILE_FILES
        }
        final_manifest = WorkflowManifest(
            schema_version=1,
            generator_version=__version__,
            scope=request.scope,
            profile=request.profile,
            targets=request.targets,
            generated_files=generated_files,
            bootstrap_root=None,
        )
        manifest_path = target_roots["neutral"] / "manifest.json"
        _add_operation(
            operations,
            WriteOperation.from_bytes(
                root_id="neutral",
                path="manifest.json",
                content=final_manifest.to_json().encode("utf-8"),
                expected_sha256=safe_current_hash(
                    manifest_path, target_roots["neutral"]
                ),
                ownership=Ownership.GENERATED,
            ),
        )

    return TransactionPlan.new(
        scope_root=base.scope_root,
        target_roots=base.target_roots,
        allowed_roots=base.allowed_roots,
        operations=tuple(operations.values()),
        conflicts=tuple(sorted(set(conflicts))),
        warnings=tuple(sorted(set((*base.warnings, *registry_warnings)))),
    )


def _setup_registry(
    request: SetupRequest,
) -> tuple[
    AdapterRegistry,
    tuple[_ExternalAdapter, ...],
    tuple[str, ...],
]:
    external = _inspect_adapter_sources(request.adapter_sources)
    if request.adapter_sources:
        external_registry = AdapterRegistry.from_directories(
            request.adapter_sources,
            request.trusted_adapter_ids,
        )
    else:
        if request.trusted_adapter_ids:
            raise ValueError(
                "adapter code trust requires an explicit adapter source"
            )
        managed = request.home / ".agents" / "workflow" / "adapters"
        external_registry = (
            AdapterRegistry.from_directories((managed,))
            if managed.is_dir() and not managed.is_symlink()
            else AdapterRegistry.from_pairs(())
        )
    registry = AdapterRegistry.combine(
        (builtin_registry(), external_registry)
    )
    warnings = tuple(
        "explicit adapter "
        f"{item.manifest.id}: "
        + (
            "trusted Python"
            if item.has_python
            and item.manifest.id in request.trusted_adapter_ids
            else "Python blocked"
            if item.has_python
            else "declarative"
        )
        for item in external
    )
    return registry, external, warnings


def _inspect_adapter_sources(
    roots: tuple[Path, ...],
) -> tuple[_ExternalAdapter, ...]:
    discovered: list[_ExternalAdapter] = []
    seen: set[str] = set()
    for root in roots:
        for package in sorted(
            (child for child in root.iterdir() if child.is_dir()),
            key=lambda path: path.name.casefold(),
        ):
            if package.is_symlink():
                raise ValueError(f"adapter package is symlinked: {package}")
            manifest_path = package / "adapter.json"
            if not manifest_path.exists():
                continue
            if not manifest_path.is_file() or manifest_path.is_symlink():
                raise ValueError(
                    f"adapter manifest is missing or unsafe: {manifest_path}"
                )
            manifest = AdapterManifest.from_path(manifest_path)
            if package.name != manifest.id:
                raise ValueError(
                    "adapter package directory must match manifest id: "
                    f"{package.name} != {manifest.id}"
                )
            if manifest.id in seen:
                raise ValueError(f"duplicate adapter id: {manifest.id}")
            seen.add(manifest.id)
            discovered.append(
                _ExternalAdapter(
                    manifest=manifest,
                    package_root=package.resolve(strict=True),
                    has_python=(package / "adapter.py").exists(),
                )
            )
    return tuple(sorted(discovered, key=lambda item: item.manifest.id))


def _external_package_operations(
    adapters: tuple[_ExternalAdapter, ...],
    *,
    selected: frozenset[str],
    target_roots: dict[str, Path],
) -> tuple[WriteOperation, ...]:
    operations: list[WriteOperation] = []
    for adapter in adapters:
        if adapter.manifest.id not in selected:
            continue
        for source in _regular_files(adapter.package_root):
            relative = source.relative_to(adapter.package_root).as_posix()
            path = (
                f"workflow/adapters/{adapter.manifest.id}/{relative}"
            )
            operations.append(
                _write_operation(
                    root_id="neutral",
                    path=path,
                    content=source.read_bytes(),
                    target_roots=target_roots,
                    ownership=Ownership.GENERATED,
                )
            )
    return tuple(operations)


def _regular_files(root: Path) -> tuple[Path, ...]:
    entries = sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    files: list[Path] = []
    for entry in entries:
        relative = entry.relative_to(root)
        if entry.is_symlink():
            raise ValueError(f"adapter package resource is symlinked: {entry}")
        if "__pycache__" in relative.parts or entry.suffix in {".pyc", ".pyo"}:
            continue
        if entry.is_file():
            files.append(entry)
        elif not entry.is_dir():
            raise ValueError(f"adapter package resource is unsafe: {entry}")
    return tuple(files)


def _verify_global_install(home: Path) -> None:
    root = home / ".agents"
    manifest = _read_manifest(root)
    if manifest is None or manifest.scope is not Scope.GLOBAL:
        raise ValueError(
            "global manager and setup skill must be installed first"
        )
    required = (
        "workflow/agent-workflow.pyz",
        "skills/agent-workflow-setup/SKILL.md",
    )
    for path in required:
        target = root.joinpath(*path.split("/"))
        digest = safe_current_hash(target, root)
        if (
            digest is None
            or manifest.generated_files.get(f"neutral:{path}") != digest
        ):
            raise ValueError(
                "global manager and setup skill must be installed first"
            )


def _read_manifest(root: Path) -> WorkflowManifest | None:
    path = root / "manifest.json"
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ValueError("existing workflow manifest is unsafe")
    try:
        return WorkflowManifest.from_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"invalid existing workflow manifest: {error}") from error


def _generated_conflict(
    operation: WriteOperation,
    manifest: WorkflowManifest | None,
    request: SetupRequest,
    target_roots: dict[str, Path],
) -> str | None:
    if operation.expected_sha256 is None:
        return None
    key = f"{operation.root_id}:{operation.path}"
    root = target_roots[operation.root_id]
    target = root.joinpath(*operation.path.split("/"))
    try:
        current = target.read_bytes()
    except OSError as error:
        raise ValueError(
            f"cannot read existing generated output: {key}"
        ) from error
    current_digests = {
        sha256_bytes(current),
        sha256_runtime_normalized(
            current,
            home=request.home if request.scope is Scope.GLOBAL else None,
            project=request.project_root,
        ),
    }
    if (
        manifest is not None
        and manifest.generated_files.get(key) in current_digests
    ):
        return None
    return f"unmanaged generated output: {key}"


def _with_safe_expected_hash(
    operation: WriteOperation,
    target_roots: dict[str, Path],
) -> WriteOperation:
    root = target_roots[operation.root_id]
    target = root.joinpath(*operation.path.split("/"))
    return WriteOperation.from_bytes(
        root_id=operation.root_id,
        path=operation.path,
        content=operation.content_bytes(),
        expected_sha256=safe_current_hash(target, root),
        ownership=operation.ownership,
    )


def _write_operation(
    *,
    root_id: str,
    path: str,
    content: bytes,
    target_roots: dict[str, Path],
    ownership: Ownership,
) -> WriteOperation:
    root = target_roots[root_id]
    target = root.joinpath(*path.split("/"))
    return WriteOperation.from_bytes(
        root_id=root_id,
        path=path,
        content=content,
        expected_sha256=safe_current_hash(target, root),
        ownership=ownership,
    )


def _add_operation(
    operations: dict[tuple[str, str], WriteOperation],
    operation: WriteOperation,
) -> None:
    key = (operation.root_id, operation.path)
    previous = operations.get(key)
    if previous is None:
        operations[key] = operation
        return
    if previous != operation:
        raise ValueError(
            "setup components produced different writes for "
            f"{operation.root_id}:{operation.path}"
        )


def _safe_directory(path: Path, label: str) -> Path:
    candidate = Path(path)
    if (
        candidate.is_symlink()
        or not candidate.is_dir()
    ):
        raise ValueError(f"{label} must be a safe existing absolute directory")
    return candidate.resolve(strict=True)


def _adapter_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{label} must contain adapter ids")
        adapter_id = value.strip().casefold()
        if _ADAPTER_ID.fullmatch(adapter_id) is None:
            raise ValueError(f"{label} must contain kebab-case adapter ids")
        normalized.add(adapter_id)
    return tuple(sorted(normalized))
