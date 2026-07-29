from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_workflow.adapters.registry import builtin_registry
from agent_workflow.migration.mappings import (
    MappingStatus,
    map_native_artifacts,
    mapping_groups,
)
from agent_workflow.migration.model import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactScope,
    Sensitivity,
    derive_artifact_id,
)


FIXTURES = Path("tests/fixtures/legacy/settings")


def test_claude_permissions_map_only_known_safe_rules(
    tmp_path: Path,
) -> None:
    result = _map_fixture(
        tmp_path,
        "claude-permissions.json",
        from_agent="claude",
        to_agent="codex",
    )

    assert result.status is MappingStatus.MANUAL
    assert not result.write_operations
    assert result.unmapped == (
        "Read",
        "Glob",
        "Grep",
        "Bash(rm:*)",
    )
    assert result.source_file_required


def test_mcp_credentials_are_never_copied(tmp_path: Path) -> None:
    result = _map_fixture(
        tmp_path,
        "claude-mcp-credentials.json",
        from_agent="claude",
        to_agent="codex",
    )

    assert result.status is MappingStatus.MANUAL
    assert "secret-value" not in result.serialized_preview()
    assert result.credential_fields == (
        "mcpServers.demo.env.API_TOKEN",
    )
    assert result.source_file_required


def test_safe_mcp_identity_command_and_args_are_exact(
    tmp_path: Path,
) -> None:
    result = _map_fixture(
        tmp_path,
        "claude-mcp-safe.json",
        from_agent="claude",
        to_agent="codex",
    )

    assert result.status is MappingStatus.EXACT
    preview = json.loads(result.serialized_preview())
    assert preview["mappings"][0]["normalized_value"] == {
        "args": ["--stdio"],
        "command": "demo-server",
        "name": "demo",
    }
    assert not result.source_file_required


def test_unknown_hook_is_preserved_at_source(tmp_path: Path) -> None:
    result = _map_fixture(
        tmp_path,
        "claude-unknown-hook.json",
        from_agent="claude",
        to_agent="codex",
    )

    assert result.status is MappingStatus.UNSUPPORTED
    assert not result.write_operations
    assert result.source_file_required


def test_reports_group_every_mapping_status(tmp_path: Path) -> None:
    results = (
        _map_fixture(
            tmp_path,
            "claude-mcp-safe.json",
            from_agent="claude",
            to_agent="codex",
        ),
        _map_fixture(
            tmp_path,
            "claude-permissions.json",
            from_agent="claude",
            to_agent="codex",
        ),
        _map_fixture(
            tmp_path,
            "claude-unknown-hook.json",
            from_agent="claude",
            to_agent="codex",
        ),
    )

    groups = mapping_groups(results)

    assert set(groups) == set(MappingStatus)
    assert len(groups[MappingStatus.EXACT]) == 1
    assert len(groups[MappingStatus.MANUAL]) == 1
    assert len(groups[MappingStatus.UNSUPPORTED]) == 1


def _map_fixture(
    tmp_path: Path,
    fixture_name: str,
    *,
    from_agent: str,
    to_agent: str,
):
    source = tmp_path / from_agent / "settings.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes((FIXTURES / fixture_name).read_bytes())
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    scope = ArtifactScope.GLOBAL
    relative_path = f".{from_agent}/settings.json"
    record = ArtifactRecord(
        artifact_id=derive_artifact_id(
            agent_id=from_agent,
            scope=scope,
            relative_path=relative_path,
            source_sha256=digest,
        ),
        agent_id=from_agent,
        kind=ArtifactKind.SETTINGS,
        scope=scope,
        path=source.resolve(),
        relative_path=relative_path,
        sha256=digest,
        media_type="application/json",
        size_bytes=len(content),
        sensitivity=Sensitivity.SAFE,
        already_neutral=False,
    )
    registry = builtin_registry()
    source_adapter = registry.require((from_agent,))[0]
    target_adapter = registry.require((to_agent,))[0]

    results = map_native_artifacts(
        (record,),
        source_adapter,
        (target_adapter,),
    )

    assert len(results) == 1
    assert str(tmp_path) not in results[0].serialized_preview()
    return results[0]
