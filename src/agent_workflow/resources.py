from __future__ import annotations

from importlib import resources
from pathlib import Path

from .model import normalize_relative_path


_TEXT_SUFFIXES = frozenset({".json", ".md", ".toml", ".txt"})


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
    bundled_content: bytes | None = None
    if bundled.is_file():
        _validate_filesystem_containment(bundled_root, bundled, "bundled resources")
        bundled_content = bundled.read_bytes()

    checkout_root = _source_checkout_root()
    if checkout_root is not None:
        candidate = checkout_root.joinpath(*parts)
        _validate_filesystem_containment(checkout_root, candidate, "source checkout")
        if not candidate.is_file():
            raise FileNotFoundError(f"resource not found: {normalized}")
        canonical_content = candidate.read_bytes()
        if bundled_content is not None and bundled_content != canonical_content:
            raise ValueError(f"bundled resource differs from canonical source: {normalized}")
        return _normalized_content(normalized, canonical_content), checkout_root

    if bundled_content is not None:
        return _normalized_content(normalized, bundled_content), None
    raise FileNotFoundError(
        f"no bundled resource and no valid source checkout fallback: {normalized}"
    )


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


def _normalized_content(relative_path: str, content: bytes) -> bytes:
    if Path(relative_path).suffix.casefold() not in _TEXT_SUFFIXES:
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"text resource is not UTF-8: {relative_path}"
        ) from error
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
