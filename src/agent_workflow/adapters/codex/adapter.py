from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

from agent_workflow.doctor import Diagnostic
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership, ProjectProfile, Scope, Severity
from agent_workflow.plan import WriteOperation
from agent_workflow.resources import load_bundled_resource

from ..base import AdapterContext, AdapterDetection
from ..declarative import detect_manifest
from ..manifest import AdapterManifest, InstructionEntrypoint


_SOURCE_DEFINITIONS = (
    ("RULES.md", "rules"),
    ("memory/MEMORY.md", "memory"),
    ("overlays/codex/RULES.md", "optional"),
)


class CodexAdapter:
    def __init__(
        self,
        manifest: AdapterManifest | None = None,
        package_root: Path | None = None,
    ) -> None:
        self.manifest = manifest or _load_manifest()
        if self.manifest.id != "codex":
            raise ValueError("Codex adapter requires the codex manifest")
        self.id = self.manifest.id
        self._package_root = (
            Path(package_root).resolve(strict=True)
            if package_root is not None
            else None
        )

    def detect(self, context: AdapterContext) -> AdapterDetection:
        return detect_manifest(self.manifest, context)

    def plan_entrypoints(
        self, context: AdapterContext
    ) -> tuple[WriteOperation, ...]:
        target_root = _target_root(context)
        operations: list[WriteOperation] = []
        for entrypoint, content in self._rendered_entrypoints(context):
            target = target_root.joinpath(*entrypoint.target.split("/"))
            operations.append(
                WriteOperation.from_bytes(
                    root_id="scope",
                    path=entrypoint.target,
                    content=content,
                    expected_sha256=_safe_current_hash(target, target_root),
                    ownership=Ownership.GENERATED,
                )
            )
        return tuple(operations)

    def validate(self, context: AdapterContext) -> tuple[Diagnostic, ...]:
        target_root = _target_root(context)
        diagnostics: list[Diagnostic] = []
        for entrypoint, expected_content in self._rendered_entrypoints(context):
            target = target_root.joinpath(*entrypoint.target.split("/"))
            diagnostic_path = f"{self.id}:{entrypoint.target}"
            if target.is_symlink() or (
                target.exists() and not _safe_existing_file(target, target_root)
            ):
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-path",
                        path=diagnostic_path,
                        message="generated Codex entrypoint path is unsafe",
                    )
                )
                continue
            if not target.exists():
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-missing",
                        path=diagnostic_path,
                        message="generated Codex entrypoint is missing or unsafe",
                    )
                )
                continue
            try:
                content = target.read_bytes()
            except OSError:
                content = b""
            if content != expected_content:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-drift",
                        path=diagnostic_path,
                        message="generated Codex entrypoint differs from canonical inputs",
                    )
                )
        return tuple(
            sorted(
                diagnostics,
                key=lambda item: (
                    item.severity.value,
                    item.code,
                    item.path.casefold(),
                    item.message,
                ),
            )
        )

    def _rendered_entrypoints(
        self, context: AdapterContext
    ) -> tuple[tuple[InstructionEntrypoint, bytes], ...]:
        source_sha256 = _source_sha256(context)
        rendered: list[tuple[InstructionEntrypoint, bytes]] = []
        for entrypoint in self.manifest.for_scope(
            context.scope
        ).instruction_entrypoints:
            if not _applies(entrypoint, context):
                continue
            rendered.append(
                (
                    entrypoint,
                    self._render_template(
                        entrypoint.template,
                        generator_version=context.generator_version,
                        source_sha256=source_sha256,
                    ),
                )
            )
        return tuple(rendered)

    def _render_template(
        self,
        relative_path: str,
        *,
        generator_version: str,
        source_sha256: str,
    ) -> bytes:
        source = self._read_template(relative_path)
        rendered = source.replace(
            "{{GENERATOR_VERSION}}", generator_version
        ).replace("{{SOURCE_SHA256}}", source_sha256)
        if "{{" in rendered or "}}" in rendered:
            raise ValueError(
                f"unknown placeholder in Codex template: {relative_path}"
            )
        return rendered.encode("utf-8")

    def _read_template(self, relative_path: str) -> str:
        if self._package_root is not None:
            candidate = self._package_root.joinpath(
                *relative_path.split("/")
            )
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(self._package_root)
            except (FileNotFoundError, ValueError) as error:
                raise ValueError(
                    f"Codex template is missing or unsafe: {relative_path}"
                ) from error
            if not resolved.is_file() or any(
                parent.is_symlink()
                for parent in _path_components(
                    self._package_root, candidate
                )
            ):
                raise ValueError(
                    f"Codex template is missing or unsafe: {relative_path}"
                )
            return resolved.read_text(encoding="utf-8")
        template = resources.files(__package__).joinpath(
            *relative_path.split("/")
        )
        if not template.is_file():
            raise ValueError(f"Codex template is missing: {relative_path}")
        return template.read_text(encoding="utf-8")


def create_adapter(
    manifest: AdapterManifest, package_root: Path
) -> CodexAdapter:
    return CodexAdapter(manifest=manifest, package_root=package_root)


def _load_manifest() -> AdapterManifest:
    source = resources.files(__package__).joinpath("adapter.json")
    return AdapterManifest.from_json(source.read_text(encoding="utf-8"))


def _target_root(context: AdapterContext) -> Path:
    if context.scope is Scope.GLOBAL:
        return context.home
    if context.project_root is None:
        raise ValueError("project Codex context requires a project root")
    return context.project_root


def _applies(
    entrypoint: InstructionEntrypoint, context: AdapterContext
) -> bool:
    if context.scope is Scope.GLOBAL:
        return True
    return not entrypoint.profiles or context.profile in entrypoint.profiles


def _source_sha256(context: AdapterContext) -> str:
    digest = hashlib.sha256()
    for relative_path, kind in _SOURCE_DEFINITIONS:
        path = context.neutral_root.joinpath(*relative_path.split("/"))
        if not _safe_path_components(path, context.neutral_root):
            raise ValueError(
                f"canonical Codex source path is unsafe: {relative_path}"
            )
        if path.is_file():
            content = path.read_bytes()
        elif kind == "rules":
            content = load_bundled_resource(
                "templates/core/global-rules.md"
                if context.scope is Scope.GLOBAL
                else "templates/core/project-rules.md"
            )
        elif kind == "memory":
            content = load_bundled_resource(
                "templates/core/global-memory-index.md"
                if context.scope is Scope.GLOBAL
                else "templates/core/project-memory-index.md"
            )
        else:
            content = b"<missing>"
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_current_hash(target: Path, root: Path) -> str | None:
    if not _safe_path_components(target, root):
        raise ValueError(f"Codex entrypoint path is unsafe: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"Codex entrypoint is not a file: {target}")
    return sha256_file(target)


def _safe_existing_file(target: Path, root: Path) -> bool:
    return (
        _safe_path_components(target, root)
        and target.is_file()
        and not target.is_symlink()
    )


def _safe_path_components(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    current = root
    if current.is_symlink():
        return False
    for part in target.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            return False
        if not current.exists():
            break
    return True


def _path_components(root: Path, target: Path) -> tuple[Path, ...]:
    current = root
    output: list[Path] = []
    for part in target.relative_to(root).parts:
        current /= part
        output.append(current)
    return tuple(output)
