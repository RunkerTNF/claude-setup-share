from __future__ import annotations

from pathlib import Path

from ..manifest import AdapterManifest
from ..rendered import GeneratedEntrypointAdapter


class CodexAdapter(GeneratedEntrypointAdapter):
    def __init__(
        self,
        manifest: AdapterManifest | None = None,
        package_root: Path | None = None,
    ) -> None:
        super().__init__(
            adapter_id="codex",
            package_name=__package__,
            manifest=manifest,
            package_root=package_root,
        )


def create_adapter(
    manifest: AdapterManifest, package_root: Path
) -> CodexAdapter:
    return CodexAdapter(manifest=manifest, package_root=package_root)
