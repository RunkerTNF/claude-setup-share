import json

import pytest

from agent_workflow.manifest import WorkflowManifest
from agent_workflow.model import ProjectProfile, Scope


def test_manifest_round_trip_is_stable() -> None:
    manifest = WorkflowManifest(
        schema_version=1,
        generator_version="0.1.0",
        scope=Scope.PROJECT,
        profile=ProjectProfile.SPLIT,
        targets=("codex", "claude"),
        generated_files={"neutral:RULES.md": "a" * 64},
    )
    assert WorkflowManifest.from_json(manifest.to_json()) == manifest


def test_global_manifest_rejects_project_profile() -> None:
    manifest = WorkflowManifest(
        schema_version=1,
        generator_version="0.1.0",
        scope=Scope.GLOBAL,
        profile=ProjectProfile.LOCAL,
        targets=(),
        generated_files={},
    )
    with pytest.raises(ValueError, match="global manifest cannot have a project profile"):
        manifest.validate()


def test_manifest_json_is_strict_and_rejects_unsafe_generated_file() -> None:
    payload = {
        "schema_version": 1,
        "generator_version": "0.1.0",
        "scope": "project",
        "profile": "split",
        "targets": [],
        "generated_files": {"unknown:../RULES.md": "A" * 64},
        "unexpected": True,
    }

    with pytest.raises(ValueError, match="unknown manifest keys"):
        WorkflowManifest.from_json(json.dumps(payload))

    payload.pop("unexpected")
    with pytest.raises(ValueError, match="unknown root ID"):
        WorkflowManifest.from_json(json.dumps(payload))


def test_manifest_copies_generated_files_and_serializes_bootstrap_root() -> None:
    generated_files = {"scope:AGENTS.md": "b" * 64}
    manifest = WorkflowManifest(
        schema_version=1,
        generator_version="0.1.0",
        scope=Scope.PROJECT,
        profile=ProjectProfile.LOCAL,
        targets=("claude",),
        generated_files=generated_files,
        bootstrap_root=".agents",
    )
    generated_files["scope:extra.md"] = "c" * 64

    assert dict(manifest.generated_files) == {"scope:AGENTS.md": "b" * 64}
    with pytest.raises(TypeError):
        manifest.generated_files["scope:other.md"] = "d" * 64
    assert json.loads(manifest.to_json())["bootstrap_root"] == ".agents"
