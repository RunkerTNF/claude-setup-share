from __future__ import annotations

from importlib import resources
from pathlib import Path

from .model import normalize_relative_path


def load_bundled_resource(relative_path: str) -> bytes:
    """Load a package resource, falling back to a validated source checkout."""
    content, _ = _load_resource(relative_path)
    return content


def bundled_resource_source(relative_path: str) -> Path | None:
    """Return the source-checkout root when this resource was not bundled."""
    _, source_root = _load_resource(relative_path)
    return source_root


def _load_resource(relative_path: str) -> tuple[bytes, Path | None]:
    normalized = normalize_relative_path(relative_path)
    parts = normalized.split("/")
    package_root = resources.files("agent_workflow")
    bundled_root = package_root.joinpath("_bundled")
    _validate_filesystem_containment(package_root, bundled_root, "package resources")
    bundled = bundled_root.joinpath(*parts)
    if bundled.is_file():
        _validate_filesystem_containment(bundled_root, bundled, "bundled resources")
        return bundled.read_bytes(), None

    checkout_root = _source_checkout_root()
    if checkout_root is None:
        raise FileNotFoundError(
            f"no bundled resource and no valid source checkout fallback: {normalized}"
        )
    candidate = checkout_root.joinpath(*parts)
    _validate_filesystem_containment(checkout_root, candidate, "source checkout")
    if not candidate.is_file():
        raise FileNotFoundError(f"resource not found: {normalized}")
    return candidate.read_bytes(), checkout_root


def _source_checkout_root() -> Path | None:
    module_path = Path(__file__).resolve(strict=False)
    package_root = module_path.parent
    source_root = package_root.parent
    checkout_root = source_root.parent
    if (
        module_path.name != "resources.py"
        or package_root.name != "agent_workflow"
        or source_root.name != "src"
        or not (checkout_root / "pyproject.toml").is_file()
    ):
        return None
    return checkout_root


def _validate_filesystem_containment(root: object, candidate: object, label: str) -> None:
    if not isinstance(root, Path) or not isinstance(candidate, Path):
        return
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as error:
        raise ValueError(f"resource path escapes {label}") from error
