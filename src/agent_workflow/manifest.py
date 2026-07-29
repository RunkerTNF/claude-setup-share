from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

from .model import ProjectProfile, ROOT_IDS, Scope, normalize_relative_path, validate_sha256


_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "generator_version",
        "scope",
        "profile",
        "targets",
        "excluded_skills",
        "generated_files",
        "bootstrap_root",
    }
)


@dataclass(frozen=True)
class WorkflowManifest:
    schema_version: int
    generator_version: str
    scope: Scope
    profile: ProjectProfile | None
    targets: tuple[str, ...]
    generated_files: Mapping[str, str]
    excluded_skills: tuple[str, ...] = ()
    bootstrap_root: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.excluded_skills, tuple):
            raise ValueError("excluded_skills must be a tuple")
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(
            self,
            "excluded_skills",
            tuple(sorted(set(self.excluded_skills))),
        )
        object.__setattr__(self, "generated_files", MappingProxyType(dict(self.generated_files)))

    def validate(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        if not isinstance(self.generator_version, str) or not self.generator_version:
            raise ValueError("generator_version must be a non-empty string")
        if not isinstance(self.scope, Scope):
            raise ValueError("scope must be valid")
        if self.profile is not None and not isinstance(self.profile, ProjectProfile):
            raise ValueError("profile must be valid")
        if self.scope is Scope.GLOBAL and self.profile is not None:
            raise ValueError("global manifest cannot have a project profile")
        if self.scope is Scope.PROJECT and self.profile is None:
            raise ValueError("project manifest requires a project profile")
        if self.bootstrap_root is not None and not isinstance(self.bootstrap_root, str):
            raise ValueError("bootstrap_root must be a string or null")
        if any(not isinstance(target, str) or not target for target in self.targets):
            raise ValueError("targets must contain non-empty strings")
        if any(
            not isinstance(skill, str) or not skill
            for skill in self.excluded_skills
        ):
            raise ValueError(
                "excluded_skills must contain non-empty strings"
            )

        normalized_keys: set[str] = set()
        for key, digest in self.generated_files.items():
            if not isinstance(key, str) or ":" not in key:
                raise ValueError("generated file key must be <root_id>:<relative-path>")
            root_id, relative_path = key.split(":", 1)
            if root_id not in ROOT_IDS:
                raise ValueError(f"unknown root ID: {root_id}")
            normalized_key = f"{root_id}:{normalize_relative_path(relative_path)}"
            if normalized_key in normalized_keys:
                raise ValueError("duplicate normalized generated file key")
            normalized_keys.add(normalized_key)
            validate_sha256(digest)

    def to_json(self) -> str:
        self.validate()
        payload = {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "scope": self.scope.value,
            "profile": self.profile.value if self.profile is not None else None,
            "targets": list(self.targets),
            "excluded_skills": list(self.excluded_skills),
            "generated_files": dict(self.generated_files),
            "bootstrap_root": self.bootstrap_root,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "WorkflowManifest":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid manifest JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("manifest JSON must be an object")
        unknown = set(payload) - _MANIFEST_KEYS
        missing = (
            _MANIFEST_KEYS - {"bootstrap_root", "excluded_skills"}
        ) - set(payload)
        if unknown:
            raise ValueError(f"unknown manifest keys: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing manifest keys: {sorted(missing)}")
        if (
            not isinstance(payload["targets"], list)
            or not isinstance(payload.get("excluded_skills", []), list)
            or not isinstance(payload["generated_files"], dict)
        ):
            raise ValueError("manifest collections must have the expected JSON types")
        try:
            result = cls(
                schema_version=payload["schema_version"],
                generator_version=payload["generator_version"],
                scope=Scope(payload["scope"]),
                profile=ProjectProfile(payload["profile"]) if payload["profile"] is not None else None,
                targets=tuple(payload["targets"]),
                excluded_skills=tuple(payload.get("excluded_skills", [])),
                generated_files=payload["generated_files"],
                bootstrap_root=payload.get("bootstrap_root"),
            )
            result.validate()
            return result
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid manifest: {error}") from error
