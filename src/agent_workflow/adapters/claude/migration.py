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


def claude_inventory_roots(
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


def claude_map_native_artifact(
    record: ArtifactRecord,
    safe_content: object,
    target_context: NativeMappingContext,
) -> MappedNativeArtifact:
    if not isinstance(safe_content, dict):
        mappings = (
            _mapping(
                record.relative_path,
                None,
                MappingStatus.UNSUPPORTED,
                target_context,
                rationale="Claude native settings are not an object.",
            ),
        )
    elif target_context.target_adapter_id != "codex":
        mappings = (
            _mapping(
                record.relative_path,
                None,
                MappingStatus.UNSUPPORTED,
                target_context,
                rationale="No guaranteed target mapping is registered.",
            ),
        )
    else:
        output: list[NativeMapping] = []
        for key, value in safe_content.items():
            if key == "permissions":
                output.append(
                    _permissions_mapping(value, target_context)
                )
            elif key == "mcpServers":
                output.extend(
                    _mcp_mappings(value, target_context)
                )
            elif key == "hooks":
                output.append(
                    _mapping(
                        "hooks",
                        None,
                        MappingStatus.UNSUPPORTED,
                        target_context,
                        unmapped=_mapping_keys(value),
                        rationale=(
                            "Claude and Codex hook lifecycle semantics "
                            "are not guaranteed equivalent."
                        ),
                    )
                )
            else:
                output.append(
                    _mapping(
                        str(key),
                        None,
                        MappingStatus.MANUAL,
                        target_context,
                        unmapped=(str(key),),
                        rationale=(
                            "This Claude-native setting remains "
                            "adapter-specific."
                        ),
                    )
                )
        mappings = tuple(output) or (
            _mapping(
                record.relative_path,
                None,
                MappingStatus.EXACT,
                target_context,
                normalized={},
                rationale="The source settings object is empty.",
            ),
        )
    return MappedNativeArtifact(
        artifact_id=record.artifact_id,
        source_agent_id=record.agent_id,
        target_agent_id=target_context.target_adapter_id,
        source_relative_path=record.relative_path,
        mappings=mappings,
    )


def _permissions_mapping(
    value: object,
    context: NativeMappingContext,
) -> NativeMapping:
    unmapped: list[str] = []
    if isinstance(value, dict):
        for key in ("allow", "deny", "ask"):
            entries = value.get(key)
            if isinstance(entries, list):
                unmapped.extend(str(entry) for entry in entries)
    if not unmapped:
        unmapped.extend(_mapping_keys(value))
    return _mapping(
        "permissions",
        None,
        MappingStatus.MANUAL,
        context,
        unmapped=tuple(unmapped),
        rationale=(
            "Claude permission matchers are not equivalent to Codex "
            "sandbox and approval policies."
        ),
    )


def _mcp_mappings(
    value: object,
    context: NativeMappingContext,
) -> tuple[NativeMapping, ...]:
    if not isinstance(value, dict):
        return (
            _mapping(
                "mcpServers",
                None,
                MappingStatus.UNSUPPORTED,
                context,
                rationale="Claude MCP servers must be an object.",
            ),
        )
    output: list[NativeMapping] = []
    for raw_name, raw_server in sorted(
        value.items(),
        key=lambda item: str(item[0]).casefold(),
    ):
        name = str(raw_name)
        source_key = f"mcpServers.{name}"
        target_key = f"mcp_servers.{name}"
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
        env = raw_server.get("env")
        unknown = tuple(
            sorted(
                str(key)
                for key in raw_server
                if key not in {"command", "args", "env"}
            )
        )
        valid_command = isinstance(command, str) and bool(command)
        valid_args = isinstance(args, list) and all(
            isinstance(arg, str) for arg in args
        )
        credentials = (
            tuple(
                f"{source_key}.env.{key}"
                for key in sorted(env)
            )
            if isinstance(env, dict)
            else ()
        )
        normalized = (
            {
                "name": name,
                "command": command,
                "args": list(args),
            }
            if valid_command and valid_args
            else None
        )
        if (
            not valid_command
            or not valid_args
            or (env is not None and not isinstance(env, dict))
        ):
            status = MappingStatus.UNSUPPORTED
            rationale = "MCP command, args, or env has an invalid shape."
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
                credentials=credentials,
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


def _mapping_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(sorted(str(key) for key in value))
    return ()
