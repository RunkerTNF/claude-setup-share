from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import re
import sys
from types import MappingProxyType
from typing import Iterable, Mapping

from .base import AdapterContext, AdapterDetection, AgentAdapter
from .declarative import DeclarativeAdapter
from .manifest import AdapterManifest


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AdapterRegistry:
    def __init__(
        self,
        adapters: Mapping[str, AgentAdapter],
        blocked_python_ids: Iterable[str] = (),
    ) -> None:
        self._adapters = MappingProxyType(dict(adapters))
        self._blocked_python_ids = frozenset(blocked_python_ids)

    @classmethod
    def from_pairs(
        cls, pairs: Iterable[tuple[str, object]]
    ) -> "AdapterRegistry":
        adapters: dict[str, AgentAdapter] = {}
        for adapter_id, raw_adapter in pairs:
            if (
                not isinstance(adapter_id, str)
                or _ADAPTER_ID.fullmatch(adapter_id) is None
            ):
                raise ValueError(f"invalid adapter id: {adapter_id}")
            if adapter_id in adapters:
                raise ValueError(f"duplicate adapter id: {adapter_id}")
            adapters[adapter_id] = raw_adapter  # type: ignore[assignment]
        return cls(
            dict(sorted(adapters.items(), key=lambda item: item[0]))
        )

    @classmethod
    def from_directories(
        cls,
        paths: Iterable[Path],
        trusted_python_ids: Iterable[str] = (),
    ) -> "AdapterRegistry":
        trusted = frozenset(trusted_python_ids)
        discovered: list[tuple[AdapterManifest, Path, bool]] = []
        seen: set[str] = set()
        for raw_root in paths:
            root = Path(raw_root)
            if not root.is_dir() or root.is_symlink():
                raise ValueError(f"adapter directory is missing or unsafe: {root}")
            for package in sorted(
                (child for child in root.iterdir() if child.is_dir()),
                key=lambda child: child.name.casefold(),
            ):
                if package.is_symlink():
                    raise ValueError(f"adapter package is a symlink: {package}")
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
                module_path = package / "adapter.py"
                discovered.append(
                    (manifest, package.resolve(strict=True), module_path.exists())
                )
        unknown_trust = trusted - {
            manifest.id
            for manifest, _, has_python in discovered
            if has_python
        }
        if unknown_trust:
            raise ValueError(
                "trusted adapter id is not an explicit Python adapter: "
                + ", ".join(sorted(unknown_trust))
            )

        adapters: dict[str, AgentAdapter] = {}
        blocked: set[str] = set()
        for manifest, package, has_python in sorted(
            discovered, key=lambda item: item[0].id
        ):
            if not has_python:
                adapters[manifest.id] = DeclarativeAdapter(manifest, package)
            elif manifest.id not in trusted:
                blocked.add(manifest.id)
            else:
                adapters[manifest.id] = _load_python_adapter(
                    manifest, package
                )
        return cls(adapters, blocked)

    def require(self, ids: Iterable[str]) -> tuple[AgentAdapter, ...]:
        requested = tuple(sorted(set(ids)))
        output: list[AgentAdapter] = []
        for adapter_id in requested:
            if adapter_id in self._blocked_python_ids:
                raise ValueError(
                    f"adapter requires trusted Python: {adapter_id}"
                )
            try:
                output.append(self._adapters[adapter_id])
            except KeyError as error:
                raise ValueError(f"unknown adapter: {adapter_id}") from error
        return tuple(output)

    def detect_all(
        self, context: AdapterContext
    ) -> tuple[AdapterDetection, ...]:
        detections = [
            adapter.detect(context)
            for adapter in self._adapters.values()
        ]
        detections.extend(
            AdapterDetection(
                adapter_id=adapter_id,
                installed=False,
                executable=None,
                version=None,
                warning="adapter contains Python and requires explicit trust",
            )
            for adapter_id in self._blocked_python_ids
        )
        return tuple(
            sorted(detections, key=lambda detection: detection.adapter_id)
        )


def _load_python_adapter(
    manifest: AdapterManifest, package_root: Path
) -> AgentAdapter:
    module_path = package_root / "adapter.py"
    if not module_path.is_file() or module_path.is_symlink():
        raise ValueError(
            f"trusted adapter Python is missing or unsafe: {manifest.id}"
        )
    digest = hashlib.sha256(str(module_path).encode("utf-8")).hexdigest()[:16]
    module_name = f"_agent_workflow_adapter_{manifest.id.replace('-', '_')}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load trusted adapter Python: {manifest.id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise ValueError(
            f"trusted adapter Python failed to import: {manifest.id}"
        ) from error
    finally:
        sys.modules.pop(module_name, None)
    factory = getattr(module, "create_adapter", None)
    if not callable(factory):
        raise ValueError(
            f"trusted adapter must export create_adapter: {manifest.id}"
        )
    adapter = factory(manifest, package_root)
    if getattr(adapter, "id", None) != manifest.id:
        raise ValueError(
            f"trusted adapter factory returned wrong id: {manifest.id}"
        )
    return adapter
