from __future__ import annotations

from agent_workflow.migration.mappings import (
    MappedNativeArtifact,
    MappingStatus,
    NativeMapping,
    NativeMappingContext,
)
from agent_workflow.migration.model import ArtifactKind, ArtifactRecord
from agent_workflow.model import Scope

from ..base import AdapterContext, InventoryRoot
from ..manifest import AdapterManifest


def codex_inventory_roots(
    context: AdapterContext,
    manifest: AdapterManifest,
) -> tuple[InventoryRoot, ...]:
    roots: list[InventoryRoot] = []
    for scope, base, config in (
        (Scope.GLOBAL, context.home, manifest.global_config),
        (Scope.PROJECT, context.project_root, manifest.project_config),
    ):
        if base is None:
            continue
        for spec in config.inventory_roots:
            kind = ArtifactKind(spec.kind)
            roots.append(
                InventoryRoot(
                    kind=kind.value,
                    scope=scope,
                    path=base.joinpath(*spec.path.split("/")),
                    recursive=spec.recursive,
                    include_globs=spec.include_globs,
                )
            )
    return tuple(
        sorted(
            roots,
            key=lambda item: (
                item.scope.value,
                item.path.as_posix(),
                item.kind,
            ),
        )
    )


def codex_map_native_artifact(
    record: ArtifactRecord,
    safe_content: object,
    target_context: NativeMappingContext,
) -> MappedNativeArtifact:
    mappings: list[NativeMapping] = []
    if (
        not isinstance(safe_content, dict)
        or target_context.target_adapter_id != "claude"
    ):
        mappings.append(
            _mapping(
                record.relative_path,
                None,
                MappingStatus.UNSUPPORTED,
                target_context,
                rationale="No guaranteed Codex native mapping is available.",
            )
        )
    else:
        for key, value in safe_content.items():
            if key == "mcp_servers":
                mappings.extend(
                    _mcp_mappings(value, target_context)
                )
            elif key in {
                "approval_policy",
                "model",
                "model_provider",
                "sandbox_mode",
                "web_search",
            }:
                mappings.append(
                    _mapping(
                        str(key),
                        None,
                        MappingStatus.MANUAL,
                        target_context,
                        unmapped=(str(key),),
                        rationale=(
                            "Codex policy and model settings remain "
                            "adapter-specific."
                        ),
                    )
                )
            else:
                mappings.append(
                    _mapping(
                        str(key),
                        None,
                        MappingStatus.UNSUPPORTED,
                        target_context,
                        unmapped=(str(key),),
                        rationale=(
                            "This Codex-native setting has no documented "
                            "Claude equivalent."
                        ),
                    )
                )
    if not mappings:
        mappings.append(
            _mapping(
                record.relative_path,
                None,
                MappingStatus.EXACT,
                target_context,
                normalized={},
                rationale="The source settings object is empty.",
            )
        )
    return MappedNativeArtifact(
        artifact_id=record.artifact_id,
        source_agent_id=record.agent_id,
        target_agent_id=target_context.target_adapter_id,
        source_relative_path=record.relative_path,
        mappings=tuple(mappings),
    )


def _mcp_mappings(
    value: object,
    context: NativeMappingContext,
) -> tuple[NativeMapping, ...]:
    if not isinstance(value, dict):
        return (
            _mapping(
                "mcp_servers",
                None,
                MappingStatus.UNSUPPORTED,
                context,
                rationale="Codex MCP servers must be an object.",
            ),
        )
    output: list[NativeMapping] = []
    for raw_name, raw_server in sorted(
        value.items(),
        key=lambda item: str(item[0]).casefold(),
    ):
        name = str(raw_name)
        source_key = f"mcp_servers.{name}"
        target_key = f"mcpServers.{name}"
        if not isinstance(raw_server, dict):
            output.append(
                _mapping(
                    source_key,
                    target_key,
                    MappingStatus.UNSUPPORTED,
                    context,
                    rationale="MCP server configuration must be an object.",
                )
            )
            continue
        command = raw_server.get("command")
        args = raw_server.get("args", [])
        credential_keys = {
            "bearer_token",
            "env",
            "env_vars",
            "http_headers",
        }
        credentials: list[str] = []
        for key in sorted(credential_keys & set(raw_server)):
            raw_credentials = raw_server[key]
            if isinstance(raw_credentials, dict):
                credentials.extend(
                    f"{source_key}.{key}.{name}"
                    for name in sorted(raw_credentials)
                )
            else:
                credentials.append(f"{source_key}.{key}")
        unknown = tuple(
            sorted(
                str(key)
                for key in raw_server
                if key not in {"command", "args", *credential_keys}
            )
        )
        valid = (
            isinstance(command, str)
            and bool(command)
            and isinstance(args, list)
            and all(isinstance(arg, str) for arg in args)
        )
        normalized = (
            {
                "name": name,
                "command": command,
                "args": list(args),
            }
            if valid
            else None
        )
        if not valid:
            status = MappingStatus.UNSUPPORTED
            rationale = "MCP command or args has an invalid shape."
        elif credentials:
            status = MappingStatus.MANUAL
            rationale = (
                "MCP identity, command, and args are portable; omitted "
                "credentials require manual entry."
            )
        elif unknown:
            status = MappingStatus.PARTIAL
            rationale = (
                "MCP identity, command, and args are portable; every "
                "omitted non-sensitive field is listed in the preview."
            )
        else:
            status = MappingStatus.EXACT
            rationale = (
                "MCP server name, executable, and non-sensitive args "
                "have documented target fields."
            )
        output.append(
            _mapping(
                source_key,
                target_key,
                status,
                context,
                normalized=normalized,
                unmapped=unknown,
                credentials=tuple(credentials),
                rationale=rationale,
            )
        )
    return tuple(output)


def _mapping(
    source_key: str,
    target_key: str | None,
    status: MappingStatus,
    context: NativeMappingContext,
    *,
    normalized: object | None = None,
    unmapped: tuple[str, ...] = (),
    credentials: tuple[str, ...] = (),
    rationale: str,
) -> NativeMapping:
    return NativeMapping(
        source_key=source_key,
        target_key=target_key,
        status=status,
        normalized_value=normalized,
        unmapped_fields=unmapped,
        credential_fields=credentials,
        rationale=rationale,
        adapter_version=context.adapter_version,
    )
