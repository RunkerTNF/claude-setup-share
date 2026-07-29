from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path
from typing import Mapping

from agent_workflow.doctor import Diagnostic
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership, Scope, Severity
from agent_workflow.plan import WriteOperation
from agent_workflow.resources import load_bundled_resource

from .base import AdapterContext, AdapterDetection
from .declarative import detect_manifest
from .manifest import AdapterManifest, InstructionEntrypoint


class GeneratedEntrypointAdapter:
    def __init__(
        self,
        *,
        adapter_id: str,
        package_name: str,
        manifest: AdapterManifest | None = None,
        package_root: Path | None = None,
    ) -> None:
        self.manifest = manifest or load_adapter_manifest(package_name)
        if self.manifest.id != adapter_id:
            raise ValueError(
                f"{adapter_id} adapter requires the {adapter_id} manifest"
            )
        self.id = adapter_id
        self._package_name = package_name
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
        target_root = target_root_for(context)
        operations: list[WriteOperation] = []
        for entrypoint, content in self._rendered_entrypoints(context):
            target = target_root.joinpath(*entrypoint.target.split("/"))
            operations.append(
                WriteOperation.from_bytes(
                    root_id="scope",
                    path=entrypoint.target,
                    content=content,
                    expected_sha256=safe_current_hash(target, target_root),
                    ownership=Ownership.GENERATED,
                )
            )
        return tuple(operations)

    def validate(self, context: AdapterContext) -> tuple[Diagnostic, ...]:
        target_root = target_root_for(context)
        diagnostics: list[Diagnostic] = []
        for entrypoint, expected_content in self._rendered_entrypoints(context):
            target = target_root.joinpath(*entrypoint.target.split("/"))
            diagnostic_path = f"{self.id}:{entrypoint.target}"
            if (
                not safe_path_components(target, target_root)
                or target.is_symlink()
                or (
                    target.exists()
                    and not safe_existing_file(target, target_root)
                )
            ):
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-path",
                        path=diagnostic_path,
                        message=f"generated {self.id} entrypoint path is unsafe",
                    )
                )
                continue
            if not target.exists():
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-missing",
                        path=diagnostic_path,
                        message=f"generated {self.id} entrypoint is missing",
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
                        message=(
                            f"generated {self.id} entrypoint differs from "
                            "canonical inputs"
                        ),
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

    def optional_overlay_exists(self, context: AdapterContext) -> bool:
        path = context.neutral_root / "overlays" / self.id / "RULES.md"
        if not safe_path_components(path, context.neutral_root):
            raise ValueError(
                f"canonical {self.id} overlay path is unsafe"
            )
        if path.exists() and not path.is_file():
            raise ValueError(
                f"canonical {self.id} overlay is not a file"
            )
        return path.is_file()

    def _rendered_entrypoints(
        self, context: AdapterContext
    ) -> tuple[tuple[InstructionEntrypoint, bytes], ...]:
        source_digest = source_sha256(context, self.id)
        replacements = self._template_replacements(
            context, source_digest
        )
        rendered: list[tuple[InstructionEntrypoint, bytes]] = []
        for entrypoint in self.manifest.for_scope(
            context.scope
        ).instruction_entrypoints:
            if not entrypoint_applies(entrypoint, context):
                continue
            rendered.append(
                (
                    entrypoint,
                    self._render_template(entrypoint.template, replacements),
                )
            )
        return tuple(rendered)

    def _template_replacements(
        self, context: AdapterContext, source_sha256: str
    ) -> Mapping[str, str]:
        return {
            "GENERATOR_VERSION": context.generator_version,
            "SOURCE_SHA256": source_sha256,
        }

    def _render_template(
        self, relative_path: str, replacements: Mapping[str, str]
    ) -> bytes:
        rendered = self._read_template(relative_path)
        for name, value in replacements.items():
            rendered = rendered.replace(f"{{{{{name}}}}}", value)
        if "{{" in rendered or "}}" in rendered:
            raise ValueError(
                f"unknown placeholder in {self.id} template: {relative_path}"
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
                    f"{self.id} template is missing or unsafe: {relative_path}"
                ) from error
            if not resolved.is_file() or any(
                component.is_symlink()
                for component in path_components(
                    self._package_root, candidate
                )
            ):
                raise ValueError(
                    f"{self.id} template is missing or unsafe: {relative_path}"
                )
            return resolved.read_text(encoding="utf-8")
        template = resources.files(self._package_name).joinpath(
            *relative_path.split("/")
        )
        if not template.is_file():
            raise ValueError(
                f"{self.id} template is missing: {relative_path}"
            )
        return template.read_text(encoding="utf-8")


def load_adapter_manifest(package_name: str) -> AdapterManifest:
    source = resources.files(package_name).joinpath("adapter.json")
    return AdapterManifest.from_json(source.read_text(encoding="utf-8"))


def target_root_for(context: AdapterContext) -> Path:
    if context.scope is Scope.GLOBAL:
        return context.home
    if context.project_root is None:
        raise ValueError("project adapter context requires a project root")
    return context.project_root


def entrypoint_applies(
    entrypoint: InstructionEntrypoint, context: AdapterContext
) -> bool:
    if context.scope is Scope.GLOBAL:
        return True
    return not entrypoint.profiles or context.profile in entrypoint.profiles


def source_sha256(context: AdapterContext, adapter_id: str) -> str:
    definitions = (
        ("RULES.md", "rules"),
        ("memory/MEMORY.md", "memory"),
        (f"overlays/{adapter_id}/RULES.md", "optional"),
    )
    digest = hashlib.sha256()
    for relative_path, kind in definitions:
        path = context.neutral_root.joinpath(*relative_path.split("/"))
        if not safe_path_components(path, context.neutral_root):
            raise ValueError(
                f"canonical {adapter_id} source path is unsafe: {relative_path}"
            )
        if path.exists() and not path.is_file():
            raise ValueError(
                f"canonical {adapter_id} source is not a file: {relative_path}"
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


def safe_current_hash(target: Path, root: Path) -> str | None:
    if not safe_path_components(target, root):
        raise ValueError(f"adapter entrypoint path is unsafe: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"adapter entrypoint is not a file: {target}")
    return sha256_file(target)


def safe_existing_file(target: Path, root: Path) -> bool:
    return (
        safe_path_components(target, root)
        and target.is_file()
        and not target.is_symlink()
    )


def safe_path_components(target: Path, root: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return False
    current = root
    if current.is_symlink():
        return False
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return False
        if not current.exists():
            break
    return True


def path_components(root: Path, target: Path) -> tuple[Path, ...]:
    current = root
    output: list[Path] = []
    for part in target.relative_to(root).parts:
        current /= part
        output.append(current)
    return tuple(output)
