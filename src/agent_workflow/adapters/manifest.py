from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from agent_workflow.model import ProjectProfile, Scope, normalize_relative_path

from .base import CapabilityStatus


_ADAPTER_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "display_name",
        "executables",
        "version_args",
        "supported_versions",
        "global",
        "project",
        "capabilities",
        "sensitive_keys",
        "validation",
        "smoke",
    }
)
_SCOPE_REQUIRED_KEYS = frozenset(
    {"discovery_paths", "instruction_entrypoints", "skill_locations"}
)
_SCOPE_ALLOWED_KEYS = _SCOPE_REQUIRED_KEYS | {"inventory_roots"}
_ENTRYPOINT_KEYS = frozenset({"target", "template", "profiles"})
_SKILL_LOCATION_KEYS = frozenset({"path", "mode"})
_INVENTORY_ROOT_KEYS = frozenset(
    {"path", "kind", "recursive", "include_globs"}
)


@dataclass(frozen=True)
class InstructionEntrypoint:
    target: str
    template: str
    profiles: tuple[ProjectProfile, ...]


@dataclass(frozen=True)
class SkillLocation:
    path: str
    mode: str


@dataclass(frozen=True)
class InventoryRootSpec:
    path: str
    kind: str
    recursive: bool
    include_globs: tuple[str, ...]


@dataclass(frozen=True)
class AdapterScopeManifest:
    discovery_paths: tuple[str, ...]
    instruction_entrypoints: tuple[InstructionEntrypoint, ...]
    skill_locations: tuple[SkillLocation, ...]
    inventory_roots: tuple[InventoryRootSpec, ...]


@dataclass(frozen=True)
class AdapterManifest:
    schema_version: int
    id: str
    display_name: str
    executables: tuple[str, ...]
    version_args: tuple[str, ...]
    supported_versions: tuple[str, ...]
    global_config: AdapterScopeManifest
    project_config: AdapterScopeManifest
    capabilities: Mapping[str, CapabilityStatus]
    sensitive_keys: tuple[str, ...]
    validation: tuple[str, ...]
    smoke: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: object) -> "AdapterManifest":
        data = _mapping(payload, "adapter manifest")
        _require_keys(data, _TOP_LEVEL_KEYS, "adapter manifest")
        if data["schema_version"] != 1:
            raise ValueError("unsupported adapter manifest schema version")
        adapter_id = _nonempty_string(data["id"], "adapter id")
        if _ADAPTER_ID.fullmatch(adapter_id) is None:
            raise ValueError("adapter id must be kebab-case")
        display_name = _nonempty_string(data["display_name"], "display_name")
        executables = _string_tuple(
            data["executables"], "executables", require_nonempty=True
        )
        version_args = _string_tuple(
            data["version_args"], "version_args", require_nonempty=True
        )
        supported_versions = _string_tuple(
            data["supported_versions"], "supported_versions"
        )
        if supported_versions != tuple(sorted(set(supported_versions))):
            raise ValueError(
                "supported_versions must be sorted and contain no duplicates"
            )
        capabilities_payload = _mapping(data["capabilities"], "capabilities")
        capabilities: dict[str, CapabilityStatus] = {}
        for name, raw_status in sorted(
            capabilities_payload.items(), key=lambda item: item[0]
        ):
            capability_name = _nonempty_string(name, "capability name")
            try:
                capabilities[capability_name] = CapabilityStatus(raw_status)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"invalid capability status for {capability_name}"
                ) from error
        sensitive_keys = _canonical_string_tuple(
            data["sensitive_keys"], "sensitive_keys"
        )
        validation = tuple(
            normalize_relative_path(path)
            for path in _string_tuple(data["validation"], "validation")
        )
        smoke = _string_tuple(data["smoke"], "smoke")
        return cls(
            schema_version=1,
            id=adapter_id,
            display_name=display_name,
            executables=executables,
            version_args=version_args,
            supported_versions=supported_versions,
            global_config=_scope_manifest(data["global"], "global"),
            project_config=_scope_manifest(data["project"], "project"),
            capabilities=MappingProxyType(capabilities),
            sensitive_keys=sensitive_keys,
            validation=validation,
            smoke=smoke,
        )

    @classmethod
    def from_json(cls, source: str) -> "AdapterManifest":
        try:
            payload = json.loads(source)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid adapter manifest JSON: {error}") from error
        return cls.from_dict(payload)

    @classmethod
    def from_path(cls, path: Path) -> "AdapterManifest":
        try:
            source = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"cannot read adapter manifest: {path}") from error
        return cls.from_json(source)

    def for_scope(self, scope: Scope) -> AdapterScopeManifest:
        if scope is Scope.GLOBAL:
            return self.global_config
        if scope is Scope.PROJECT:
            return self.project_config
        raise ValueError("adapter scope must be valid")


def _scope_manifest(payload: object, label: str) -> AdapterScopeManifest:
    data = _mapping(payload, f"{label} adapter section")
    _require_keys(
        data,
        _SCOPE_REQUIRED_KEYS,
        f"{label} adapter section",
        allowed=_SCOPE_ALLOWED_KEYS,
    )
    discovery_paths = tuple(
        normalize_relative_path(path)
        for path in _string_tuple(
            data["discovery_paths"], f"{label}.discovery_paths"
        )
    )
    entrypoints_payload = _sequence(
        data["instruction_entrypoints"], f"{label}.instruction_entrypoints"
    )
    entrypoints: list[InstructionEntrypoint] = []
    for index, raw_entrypoint in enumerate(entrypoints_payload):
        entrypoint = _mapping(
            raw_entrypoint, f"{label}.instruction_entrypoints[{index}]"
        )
        _require_keys(
            entrypoint,
            _ENTRYPOINT_KEYS,
            f"{label}.instruction_entrypoints[{index}]",
        )
        raw_profiles = _string_tuple(
            entrypoint["profiles"],
            f"{label}.instruction_entrypoints[{index}].profiles",
        )
        try:
            profiles = tuple(ProjectProfile(profile) for profile in raw_profiles)
        except ValueError as error:
            raise ValueError(
                f"invalid profile in {label}.instruction_entrypoints[{index}]"
            ) from error
        if profiles != tuple(
            sorted(set(profiles), key=lambda profile: profile.value)
        ):
            raise ValueError(
                f"{label}.instruction_entrypoints[{index}].profiles "
                "must be sorted and unique"
            )
        entrypoints.append(
            InstructionEntrypoint(
                target=normalize_relative_path(
                    _nonempty_string(entrypoint["target"], "entrypoint target")
                ),
                template=normalize_relative_path(
                    _nonempty_string(
                        entrypoint["template"], "entrypoint template"
                    )
                ),
                profiles=profiles,
            )
        )
    locations_payload = _sequence(
        data["skill_locations"], f"{label}.skill_locations"
    )
    locations: list[SkillLocation] = []
    for index, raw_location in enumerate(locations_payload):
        location = _mapping(
            raw_location, f"{label}.skill_locations[{index}]"
        )
        _require_keys(
            location, _SKILL_LOCATION_KEYS, f"{label}.skill_locations[{index}]"
        )
        mode = _nonempty_string(location["mode"], "skill location mode")
        if mode not in {"direct", "wrapper"}:
            raise ValueError("skill location mode must be direct or wrapper")
        locations.append(
            SkillLocation(
                path=normalize_relative_path(
                    _nonempty_string(location["path"], "skill location path")
                ),
                mode=mode,
            )
        )
    inventory_payload = _sequence(
        data.get("inventory_roots", []), f"{label}.inventory_roots"
    )
    inventory_roots: list[InventoryRootSpec] = []
    for index, raw_inventory_root in enumerate(inventory_payload):
        inventory_root = _mapping(
            raw_inventory_root, f"{label}.inventory_roots[{index}]"
        )
        _require_keys(
            inventory_root,
            _INVENTORY_ROOT_KEYS,
            f"{label}.inventory_roots[{index}]",
        )
        recursive = inventory_root["recursive"]
        if type(recursive) is not bool:
            raise ValueError(
                f"{label}.inventory_roots[{index}].recursive must be boolean"
            )
        inventory_roots.append(
            InventoryRootSpec(
                path=normalize_relative_path(
                    _nonempty_string(
                        inventory_root["path"], "inventory root path"
                    )
                ),
                kind=_nonempty_string(
                    inventory_root["kind"], "inventory root kind"
                ),
                recursive=recursive,
                include_globs=_string_tuple(
                    inventory_root["include_globs"],
                    f"{label}.inventory_roots[{index}].include_globs",
                ),
            )
        )
    return AdapterScopeManifest(
        discovery_paths=discovery_paths,
        instruction_entrypoints=tuple(entrypoints),
        skill_locations=tuple(locations),
        inventory_roots=tuple(inventory_roots),
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(value)


def _string_tuple(
    value: object, label: str, *, require_nonempty: bool = False
) -> tuple[str, ...]:
    values = _sequence(value, label)
    if require_nonempty and not values:
        raise ValueError(f"{label} must not be empty")
    output = tuple(_nonempty_string(item, label) for item in values)
    if len(set(output)) != len(output):
        raise ValueError(f"{label} must not contain duplicates")
    return output


def _canonical_string_tuple(value: object, label: str) -> tuple[str, ...]:
    output = _string_tuple(value, label)
    if output != tuple(sorted(output)):
        raise ValueError(f"{label} must be sorted")
    return output


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if value != value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be canonical")
    return value


def _require_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    label: str,
    *,
    allowed: frozenset[str] | None = None,
) -> None:
    actual = set(payload)
    unknown = actual - (allowed or expected)
    if unknown:
        raise ValueError(
            f"unknown {label} fields: {', '.join(sorted(unknown))}"
        )
    missing = expected - actual
    if missing:
        raise ValueError(
            f"missing {label} fields: {', '.join(sorted(missing))}"
        )
