from __future__ import annotations

from agent_workflow.migration.model import ArtifactKind
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
