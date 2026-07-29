from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_workflow.adapters.base import (
    AdapterContext,
    AdapterDetection,
    CapabilityStatus,
)
from agent_workflow.adapters.manifest import AdapterManifest
from agent_workflow.adapters.registry import AdapterRegistry
from agent_workflow.model import Scope


def _manifest_dict(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "id": "codex",
        "display_name": "Codex",
        "executables": ["codex"],
        "version_args": ["--version"],
        "supported_versions": [],
        "global": {
            "discovery_paths": [".codex/AGENTS.md"],
            "instruction_entrypoints": [],
            "skill_locations": [{"path": ".agents/skills", "mode": "direct"}],
        },
        "project": {
            "discovery_paths": ["AGENTS.md", "AGENTS.override.md"],
            "instruction_entrypoints": [],
            "skill_locations": [{"path": ".agents/skills", "mode": "direct"}],
        },
        "capabilities": {"skills": "supported"},
        "sensitive_keys": ["api_key"],
        "validation": [],
        "smoke": [],
    }
    payload.update(overrides)
    return payload


def _context(tmp_path: Path) -> AdapterContext:
    home = tmp_path / "home"
    home.mkdir()
    return AdapterContext(
        home=home,
        project_root=None,
        neutral_root=home / ".agents",
        scope=Scope.GLOBAL,
        profile=None,
        generator_version="0.1.0",
    )


def test_manifest_requires_unique_id_and_version_command() -> None:
    manifest = AdapterManifest.from_dict(_manifest_dict())

    assert manifest.id == "codex"
    assert manifest.capabilities["skills"] is CapabilityStatus.SUPPORTED
    assert manifest.version_args == ("--version",)


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"id": "Not Portable"}, "adapter id"),
        ({"executables": []}, "executables"),
        ({"version_args": []}, "version_args"),
        ({"supported_versions": ["2.0", "1.0"]}, "supported_versions"),
        ({"unexpected": True}, "unknown adapter manifest fields"),
    ),
)
def test_manifest_rejects_noncanonical_schema(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AdapterManifest.from_dict(_manifest_dict(**override))


def test_manifest_rejects_escaping_entrypoint_path() -> None:
    project = dict(_manifest_dict()["project"])
    project["instruction_entrypoints"] = [
        {
            "target": "../CLAUDE.md",
            "template": "templates/project.md",
            "profiles": ["local"],
        }
    ]

    with pytest.raises(ValueError, match="safe relative path"):
        AdapterManifest.from_dict(_manifest_dict(project=project))


def test_registry_rejects_duplicate_adapter_ids() -> None:
    adapter = object()
    with pytest.raises(ValueError, match="duplicate adapter id"):
        AdapterRegistry.from_pairs((("same", adapter), ("same", adapter)))


def test_unknown_target_is_explicit() -> None:
    registry = AdapterRegistry.from_pairs(())
    with pytest.raises(ValueError, match="unknown adapter: pi"):
        registry.require(("pi",))


def test_declarative_adapter_loads_without_python_module() -> None:
    registry = AdapterRegistry.from_directories(
        (Path("tests/fixtures/adapters/declarative"),)
    )

    adapter = registry.require(("fixture-agent",))[0]

    assert adapter.id == "fixture-agent"
    assert type(adapter).__name__ == "DeclarativeAdapter"


def test_declarative_adapter_plans_packaged_template(tmp_path: Path) -> None:
    registry = AdapterRegistry.from_directories(
        (Path("tests/fixtures/adapters/declarative"),)
    )

    operation = registry.require(("fixture-agent",))[0].plan_entrypoints(
        _context(tmp_path)
    )[0]

    assert operation.root_id == "scope"
    assert operation.path == ".fixture-agent/PROJECT.md"
    assert operation.content_bytes().startswith(b"# Fixture Agent")


def test_registry_does_not_import_untrusted_python_adapter(
    tmp_path: Path,
) -> None:
    package = tmp_path / "adapters" / "fixture-agent"
    package.mkdir(parents=True)
    fixture = Path(
        "tests/fixtures/adapters/declarative/fixture-agent/adapter.json"
    )
    package.joinpath("adapter.json").write_bytes(fixture.read_bytes())
    package.joinpath("adapter.py").write_text(
        "raise RuntimeError('untrusted adapter executed')\n",
        encoding="utf-8",
    )

    registry = AdapterRegistry.from_directories((package.parent,))

    with pytest.raises(ValueError, match="requires trusted Python"):
        registry.require(("fixture-agent",))
    detection = registry.detect_all(_context(tmp_path))[0]
    assert detection.adapter_id == "fixture-agent"
    assert detection.installed is False
    assert detection.warning == "adapter contains Python and requires explicit trust"


def test_trusted_python_adapter_must_export_factory(tmp_path: Path) -> None:
    package = tmp_path / "adapters" / "fixture-agent"
    package.mkdir(parents=True)
    fixture = Path(
        "tests/fixtures/adapters/declarative/fixture-agent/adapter.json"
    )
    package.joinpath("adapter.json").write_bytes(fixture.read_bytes())
    package.joinpath("adapter.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="create_adapter"):
        AdapterRegistry.from_directories(
            (package.parent,), trusted_python_ids=("fixture-agent",)
        )


def test_trusted_python_adapter_loads_only_after_explicit_trust(
    tmp_path: Path,
) -> None:
    package = tmp_path / "adapters" / "fixture-agent"
    package.mkdir(parents=True)
    fixture = Path(
        "tests/fixtures/adapters/declarative/fixture-agent/adapter.json"
    )
    package.joinpath("adapter.json").write_bytes(fixture.read_bytes())
    package.joinpath("templates").mkdir()
    package.joinpath("templates/project.md").write_text(
        "# Trusted fixture\n", encoding="utf-8"
    )
    package.joinpath("adapter.py").write_text(
        "from agent_workflow.adapters.declarative import DeclarativeAdapter\n"
        "def create_adapter(manifest, package_root):\n"
        "    return DeclarativeAdapter(manifest, package_root)\n",
        encoding="utf-8",
    )

    registry = AdapterRegistry.from_directories(
        (package.parent,), trusted_python_ids=("fixture-agent",)
    )

    assert registry.require(("fixture-agent",))[0].id == "fixture-agent"


def test_registry_selection_and_detection_are_sorted(tmp_path: Path) -> None:
    class FakeAdapter:
        def __init__(self, adapter_id: str) -> None:
            self.id = adapter_id

        def detect(self, context: AdapterContext) -> AdapterDetection:
            return AdapterDetection(self.id, False, None, None)

        def plan_entrypoints(self, context: AdapterContext) -> tuple[object, ...]:
            return ()

        def validate(self, context: AdapterContext) -> tuple[object, ...]:
            return ()

    registry = AdapterRegistry.from_pairs(
        (("zeta", FakeAdapter("zeta")), ("alpha", FakeAdapter("alpha")))
    )

    assert [adapter.id for adapter in registry.require(("zeta", "alpha"))] == [
        "alpha",
        "zeta",
    ]
    assert [
        detection.adapter_id
        for detection in registry.detect_all(_context(tmp_path))
    ] == ["alpha", "zeta"]


def test_fixture_manifest_is_strict_json() -> None:
    payload = json.loads(
        Path(
            "tests/fixtures/adapters/declarative/fixture-agent/adapter.json"
        ).read_text(encoding="utf-8")
    )

    assert AdapterManifest.from_dict(payload).id == "fixture-agent"
