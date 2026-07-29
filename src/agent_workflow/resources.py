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
    bundled = resources.files("agent_workflow").joinpath("_bundled", *parts)
    if bundled.is_file():
        return bundled.read_bytes(), None

    checkout_root = Path(__file__).resolve().parents[2]
    candidate = checkout_root.joinpath(*parts)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(checkout_root)
    except ValueError as error:
        raise ValueError("resource path escapes source checkout") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"resource not found: {normalized}")
    return candidate.read_bytes(), checkout_root
