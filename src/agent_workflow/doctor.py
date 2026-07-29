"""Read-only diagnostics for an installed neutral workflow scope."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from .manifest import WorkflowManifest
from .model import Severity, normalize_relative_path


_MAX_TEXT_BYTES = 1024 * 1024
_TRANSACTION_STORAGE_PREFIXES = (
    ("workflow", "backups"),
    ("workflow", "journals"),
    ("workflow", "staging"),
    ("workflow", "locks"),
)


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    path: str
    message: str


def run_doctor(
    scope_root: Path,
    registry: object | None = None,
) -> tuple[Diagnostic, ...]:
    """Inspect an installed scope without raising or changing its filesystem state."""
    root = Path(scope_root)
    diagnostics: list[Diagnostic] = []
    if not _safe_directory(root, root):
        return _ordered([_diagnostic("scope.invalid", ".", "scope root is missing or unsafe")])

    manifest = _load_manifest(root, diagnostics)
    if manifest is None:
        _check_required_core(root, diagnostics)
        return _ordered(diagnostics)

    _check_generated(root, manifest, diagnostics)
    _check_required_core(root, diagnostics)
    _lint_skills(root, diagnostics)
    _scan_bootstrap_dependencies(root, manifest, diagnostics)
    _validate_selected_adapters(root, manifest, registry, diagnostics)
    return _ordered(diagnostics)


def _validate_selected_adapters(
    root: Path,
    manifest: WorkflowManifest,
    registry: object | None,
    diagnostics: list[Diagnostic],
) -> None:
    from .adapters.base import AdapterContext
    from .adapters.registry import AdapterRegistry, builtin_registry

    selected_registry: AdapterRegistry
    if registry is not None:
        if not isinstance(registry, AdapterRegistry):
            diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "adapter.registry-invalid",
                    "manifest.json",
                    "adapter registry is unavailable",
                )
            )
            return
        selected_registry = registry
    else:
        managed = root / "workflow" / "adapters"
        try:
            external = (
                AdapterRegistry.from_directories((managed,))
                if managed.is_dir() and not managed.is_symlink()
                else AdapterRegistry.from_pairs(())
            )
            selected_registry = AdapterRegistry.combine(
                (builtin_registry(), external)
            )
        except (OSError, UnicodeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "adapter.registry-invalid",
                    "workflow/adapters",
                    f"managed adapter registry is invalid: {error}",
                )
            )
            selected_registry = builtin_registry()

    project_root = (
        root.parent if manifest.scope.value == "project" else None
    )
    context = AdapterContext(
        home=root.parent,
        project_root=project_root,
        neutral_root=root,
        scope=manifest.scope,
        profile=manifest.profile,
        generator_version=manifest.generator_version,
    )
    for adapter_id in manifest.targets:
        try:
            adapter = selected_registry.require((adapter_id,))[0]
        except ValueError as error:
            diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "adapter.unavailable",
                    adapter_id,
                    str(error),
                )
            )
            continue
        try:
            diagnostics.extend(adapter.validate(context))
        except Exception as error:
            diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "adapter.validation-error",
                    adapter_id,
                    f"adapter validation failed: {type(error).__name__}",
                )
            )


def _load_manifest(root: Path, diagnostics: list[Diagnostic]) -> WorkflowManifest | None:
    manifest_path = root / "manifest.json"
    if not _safe_file(manifest_path, root):
        code = "manifest.missing" if not manifest_path.exists() else "manifest.invalid"
        diagnostics.append(_diagnostic(code, "manifest.json", "missing or unsafe manifest"))
        return None
    try:
        manifest = WorkflowManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        diagnostics.append(_diagnostic("manifest.invalid", "manifest.json", f"invalid manifest: {error}"))
        return None
    if not _canonical_generated_keys(manifest):
        diagnostics.append(
            _diagnostic("manifest.invalid", "manifest.json", "manifest generated file keys are not canonical")
        )
        return None
    return manifest


def _canonical_generated_keys(manifest: WorkflowManifest) -> bool:
    try:
        return all(
            key == f"{key.split(':', 1)[0]}:{normalize_relative_path(key.split(':', 1)[1])}"
            for key in manifest.generated_files
        )
    except (IndexError, ValueError):
        return False


def _check_generated(root: Path, manifest: WorkflowManifest, diagnostics: list[Diagnostic]) -> None:
    target_roots = {"neutral": root, "scope": root.parent}
    for key, expected_digest in sorted(manifest.generated_files.items(), key=lambda item: item[0].casefold()):
        root_id, relative_path = key.split(":", 1)
        target_root = target_roots[root_id]
        target = target_root.joinpath(*relative_path.split("/"))
        if not _safe_file(target, target_root):
            code = "generated.missing" if not target.exists() else "generated.path"
            diagnostics.append(_diagnostic(code, key, "missing or unsafe managed file"))
            continue
        try:
            actual_digest = _sha256_regular_file(target)
        except OSError:
            diagnostics.append(_diagnostic("generated.path", key, "cannot read managed file safely"))
            continue
        if actual_digest != expected_digest:
            diagnostics.append(_diagnostic("generated.drift", key, "managed file hash differs from manifest"))


def _check_required_core(root: Path, diagnostics: list[Diagnostic]) -> None:
    for relative_path in ("RULES.md", "memory/MEMORY.md"):
        if not _safe_file(root / relative_path, root):
            diagnostics.append(_diagnostic("core.missing", relative_path, "required core file is missing or unsafe"))


def _lint_skills(root: Path, diagnostics: list[Diagnostic]) -> None:
    skills_root = root / "skills"
    if not skills_root.exists():
        return
    if not _safe_directory(skills_root, root):
        diagnostics.append(_diagnostic("skills.invalid-entry", "skills", "skills directory is unsafe"))
        return
    try:
        children = sorted(skills_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        diagnostics.append(_diagnostic("skills.invalid-entry", "skills", "cannot list skills directory"))
        return
    from .portability import lint_skill

    for child in children:
        if child.is_symlink() or not child.is_dir():
            diagnostics.append(
                _diagnostic("skills.invalid-entry", _relative(child, root), "skill entry is not a safe directory")
            )
            continue
        for diagnostic in lint_skill(child):
            path = f"{_relative(child, root)}/{diagnostic.path}"
            diagnostics.append(Diagnostic(diagnostic.severity, diagnostic.code, path, diagnostic.message))


def _scan_bootstrap_dependencies(
    root: Path, manifest: WorkflowManifest, diagnostics: list[Diagnostic]
) -> None:
    if not manifest.bootstrap_root:
        return
    needle = _normalize_for_scan(manifest.bootstrap_root)
    if not needle:
        return
    candidates: dict[str, Path] = {
        _relative(path, root): path for path in _bounded_safe_files(root)
    }
    target_roots = {"neutral": root, "scope": root.parent}
    for key in manifest.generated_files:
        root_id, relative_path = key.split(":", 1)
        candidate = target_roots[root_id].joinpath(*relative_path.split("/"))
        if _safe_file(candidate, target_roots[root_id]) and candidate not in candidates.values():
            candidates.setdefault(key, candidate)
    for display_path, path in sorted(candidates.items(), key=lambda item: item[0].casefold()):
        relative = _relative(path, root) if _is_within(path, root) else display_path
        if relative == "manifest.json" or _excluded_from_bootstrap_scan(relative):
            continue
        text = _read_bounded_utf8(path)
        if text is None:
            continue
        if needle in _normalize_for_scan(text):
            diagnostics.append(
                _diagnostic("bootstrap.reference", display_path, "references the disposable bootstrap root")
            )


def _bounded_safe_files(root: Path):
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        safe_names: list[str] = []
        for name in names:
            child = current / name
            relative = _relative(child, root)
            if _excluded_from_bootstrap_scan(relative) or child.is_symlink():
                continue
            safe_names.append(name)
        names[:] = safe_names
        for name in sorted(filenames, key=str.casefold):
            path = current / name
            if path.is_symlink():
                continue
            if _safe_file(path, root):
                yield path


def _read_bounded_utf8(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_TEXT_BYTES:
            return None
        with path.open("rb") as file:
            content = file.read(_MAX_TEXT_BYTES + 1)
    except OSError:
        return None
    if len(content) > _MAX_TEXT_BYTES:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _excluded_from_bootstrap_scan(relative_path: str) -> bool:
    parts = tuple(part.casefold() for part in Path(relative_path).parts)
    return relative_path.casefold() == ".workflow.lock" or any(
        parts[: len(prefix)] == prefix for prefix in _TRANSACTION_STORAGE_PREFIXES
    )


def _safe_directory(path: Path, root: Path) -> bool:
    try:
        if not path.is_dir() or path.is_symlink():
            return False
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return not _has_symlink_component(path, root)
    except (OSError, ValueError):
        return False


def _safe_file(path: Path, root: Path) -> bool:
    try:
        if not path.is_file() or path.is_symlink():
            return False
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return not _has_symlink_component(path, root)
    except (OSError, ValueError):
        return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_symlink_component(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    cursor = root
    if cursor.is_symlink():
        return True
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _sha256_regular_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_for_scan(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(Severity.BLOCKING, code, path, message)


def _ordered(diagnostics: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(set(diagnostics), key=lambda item: (item.path, item.code, item.message)))
