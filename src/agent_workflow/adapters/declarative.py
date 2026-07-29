from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from agent_workflow.doctor import Diagnostic
from agent_workflow.hashing import sha256_file
from agent_workflow.model import Ownership, Scope, Severity
from agent_workflow.plan import WriteOperation

from .base import AdapterContext, AdapterDetection
from .manifest import AdapterManifest, InstructionEntrypoint


class DeclarativeAdapter:
    def __init__(
        self, manifest: AdapterManifest, package_root: Path
    ) -> None:
        self.manifest = manifest
        self.package_root = _safe_package_root(package_root)
        self.id = manifest.id

    def detect(self, context: AdapterContext) -> AdapterDetection:
        del context
        executable = next(
            (
                discovered
                for candidate in self.manifest.executables
                if (discovered := shutil.which(candidate)) is not None
            ),
            None,
        )
        if executable is None:
            return AdapterDetection(self.id, False, None, None)
        try:
            completed = subprocess.run(
                [executable, *self.manifest.version_args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return AdapterDetection(
                self.id,
                True,
                executable,
                None,
                f"version detection failed: {type(error).__name__}",
            )
        output = completed.stdout.strip() or completed.stderr.strip()
        version = output.splitlines()[0].strip() if output else None
        if completed.returncode != 0:
            return AdapterDetection(
                self.id,
                True,
                executable,
                version,
                f"version command exited with {completed.returncode}",
            )
        if version is None:
            warning = "version command returned no version"
        elif not self.manifest.supported_versions:
            warning = "detected version has not been release-smoke verified"
        elif version not in self.manifest.supported_versions:
            warning = f"unsupported or unverified version: {version}"
        else:
            warning = None
        return AdapterDetection(self.id, True, executable, version, warning)

    def plan_entrypoints(
        self, context: AdapterContext
    ) -> tuple[WriteOperation, ...]:
        scope_manifest = self.manifest.for_scope(context.scope)
        scope_root = _scope_root(context)
        operations: list[WriteOperation] = []
        for entrypoint in scope_manifest.instruction_entrypoints:
            if not _applies(entrypoint, context):
                continue
            template = _safe_package_file(
                self.package_root, entrypoint.template
            )
            target = scope_root.joinpath(*entrypoint.target.split("/"))
            operations.append(
                WriteOperation.from_bytes(
                    root_id="scope",
                    path=entrypoint.target,
                    content=template.read_bytes(),
                    expected_sha256=sha256_file(target),
                    ownership=Ownership.GENERATED,
                )
            )
        return tuple(operations)

    def validate(self, context: AdapterContext) -> tuple[Diagnostic, ...]:
        scope_root = _scope_root(context)
        diagnostics: list[Diagnostic] = []
        for relative_path in self.manifest.validation:
            target = scope_root.joinpath(*relative_path.split("/"))
            if not target.is_file() or target.is_symlink():
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.CONFLICT,
                        code="adapter.entrypoint-missing",
                        path=f"{self.id}:{relative_path}",
                        message="required native adapter path is missing or unsafe",
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


def _scope_root(context: AdapterContext) -> Path:
    if context.scope is Scope.GLOBAL:
        return context.home
    if context.project_root is None:
        raise ValueError("project adapter context requires a project root")
    return context.project_root


def _applies(
    entrypoint: InstructionEntrypoint, context: AdapterContext
) -> bool:
    if context.scope is Scope.GLOBAL:
        return True
    return not entrypoint.profiles or context.profile in entrypoint.profiles


def _safe_package_root(package_root: Path) -> Path:
    root = Path(package_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"adapter package root is missing or unsafe: {root}")
    return root.resolve(strict=True)


def _safe_package_file(package_root: Path, relative_path: str) -> Path:
    candidate = package_root.joinpath(*relative_path.split("/"))
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(package_root)
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(
            f"adapter template is missing or escapes package: {relative_path}"
        ) from error
    current = package_root
    for part in relative_path.split("/"):
        current /= part
        if current.is_symlink():
            raise ValueError(f"adapter template contains a symlink: {relative_path}")
    if not resolved.is_file():
        raise ValueError(f"adapter template is not a file: {relative_path}")
    return resolved
