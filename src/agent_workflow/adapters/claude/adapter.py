from __future__ import annotations

from pathlib import Path
from typing import Mapping

from agent_workflow.model import Scope
from agent_workflow.migration.mappings import (
    MappedNativeArtifact,
    NativeMappingContext,
)
from agent_workflow.migration.model import ArtifactRecord

from ..base import AdapterContext, InventoryRoot
from ..manifest import AdapterManifest
from ..rendered import GeneratedEntrypointAdapter
from .migration import (
    claude_inventory_roots,
    claude_map_native_artifact,
)


class ClaudeAdapter(GeneratedEntrypointAdapter):
    def __init__(
        self,
        manifest: AdapterManifest | None = None,
        package_root: Path | None = None,
    ) -> None:
        super().__init__(
            adapter_id="claude",
            package_name=__package__,
            manifest=manifest,
            package_root=package_root,
        )

    def _template_replacements(
        self, context: AdapterContext, source_sha256: str
    ) -> Mapping[str, str]:
        neutral = (
            "~/.agents"
            if context.scope is Scope.GLOBAL
            else ".agents"
        )
        overlay = (
            f"@{neutral}/overlays/claude/RULES.md"
            if self.optional_overlay_exists(context)
            else ""
        )
        return {
            **super()._template_replacements(context, source_sha256),
            "RULES_IMPORT": f"@{neutral}/RULES.md",
            "OVERLAY_IMPORT": overlay,
            "MEMORY_IMPORT": f"@{neutral}/memory/MEMORY.md",
        }

    def inventory_roots(
        self, context: AdapterContext
    ) -> tuple[InventoryRoot, ...]:
        return claude_inventory_roots(context, self.manifest)

    def map_native_artifact(
        self,
        record: ArtifactRecord,
        safe_content: object,
        target_context: NativeMappingContext,
    ) -> MappedNativeArtifact:
        return claude_map_native_artifact(
            record,
            safe_content,
            target_context,
        )


def create_adapter(
    manifest: AdapterManifest, package_root: Path
) -> ClaudeAdapter:
    return ClaudeAdapter(manifest=manifest, package_root=package_root)
