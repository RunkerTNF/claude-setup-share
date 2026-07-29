from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

from agent_workflow import __version__
from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.registry import builtin_registry
from agent_workflow.doctor import run_doctor
from agent_workflow.layout import plan_neutral_init
from agent_workflow.migration.apply import apply_migration
from agent_workflow.migration.classification import (
    ClassificationDecision,
    ClassificationResponse,
    DecisionKind,
    build_classification_request,
    validate_classification_response,
)
from agent_workflow.migration.inventory import (
    scan_migration_inventory,
)
from agent_workflow.migration.mappings import map_native_artifacts
from agent_workflow.migration.normalize import (
    normalize_deterministic,
    resolve_normalized_collisions,
)
from agent_workflow.migration.planner import (
    MigrationOptions,
    build_migration_plan,
)
from agent_workflow.model import Scope
from agent_workflow.paths import HostPaths
from agent_workflow.transactions import apply_plan


FIXTURE_ROOT = Path("tests/fixtures/legacy")
GOLDEN_ROOT = Path("tests/golden/migration")
FIXTURE_NAMES = (
    "claude-only",
    "codex-only",
    "mixed",
    "conflicts",
    "current-repository",
)
_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:home|Users|tmp)/)"
)
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|auth[_-]?token|password|private[_-]?key)"
    r"\s*[:=]\s*(?![\"']?(?:<[^>]+>|redacted|example))"
)
_EPHEMERAL_PARTS = (
    ("workflow", "backups"),
    ("workflow", "journals"),
    ("workflow", "staging"),
    ("workflow", "locks"),
)


@dataclass(frozen=True)
class FixtureMigrationResult:
    install_root: Path
    preview: str
    tree: dict[str, dict[str, object]]
    applied: bool


def run_fixture_migration(
    fixture_name: str,
    tmp_path: Path,
) -> FixtureMigrationResult:
    if fixture_name not in FIXTURE_NAMES:
        raise ValueError(f"unknown migration fixture: {fixture_name}")
    fixture = FIXTURE_ROOT / fixture_name
    if not (fixture / "SOURCE.md").is_file():
        raise ValueError(
            f"migration fixture lacks provenance: {fixture_name}"
        )
    home = tmp_path / "home"
    home.mkdir()
    _copy_fixture(fixture, home)

    apply_plan(
        plan_neutral_init(
            HostPaths(home=home, cwd=tmp_path, project_root=None),
            scope=Scope.GLOBAL,
            profile=None,
            targets=(),
        )
    )
    registry = builtin_registry()
    adapters = registry.require(("claude", "codex"))
    context = AdapterContext(
        home=home,
        project_root=None,
        neutral_root=home / ".agents",
        scope=Scope.GLOBAL,
        profile=None,
        generator_version=__version__,
    )
    inventory = scan_migration_inventory(context, adapters)
    normalized = resolve_normalized_collisions(
        tuple(
            normalize_deterministic(record, home)
            for record in inventory.artifacts
        )
    )
    request = build_classification_request(inventory)
    response = _classification_response(request)
    assert validate_classification_response(
        json.loads(response.to_json()),
        request=request,
    ) == ()

    mappings = []
    for source_id in sorted(
        {record.agent_id for record in inventory.artifacts}
    ):
        source = registry.require((source_id,))[0]
        mappings.extend(
            map_native_artifacts(
                (
                    record
                    for record in inventory.artifacts
                    if record.agent_id == source_id
                ),
                source,
                adapters,
            )
        )
    plan = build_migration_plan(
        inventory=inventory,
        normalized=normalized,
        decisions=response if request.artifacts else None,
        mappings=tuple(mappings),
        options=MigrationOptions(
            home=home,
            project_root=None,
            scope=Scope.GLOBAL,
            profile=None,
            targets=("claude", "codex"),
            replace_native=False,
            imported_at="2026-07-29T00:00:00Z",
        ),
    )
    applied = not plan.blocking_conflicts
    if applied:
        apply_migration(plan)
    install_root = home / ".agents"
    return FixtureMigrationResult(
        install_root=install_root,
        preview=plan.report.to_markdown(),
        tree=tree_snapshot(install_root),
        applied=applied,
    )


def fixture_is_sanitized(fixture_name: str) -> bool:
    fixture = FIXTURE_ROOT / fixture_name
    if not fixture.is_dir():
        return False
    for path in fixture.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _PRIVATE_PATH.search(text) or _CREDENTIAL_VALUE.search(text):
            return False
    return True


def tree_snapshot(root: Path) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = tuple(part.casefold() for part in relative.parts)
        if relative.name == ".workflow.lock" or any(
            parts[: len(prefix)] == prefix
            for prefix in _EPHEMERAL_PARTS
        ):
            continue
        content = _portable_snapshot_content(relative, path.read_bytes())
        entry: dict[str, object] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        try:
            entry["text"] = content.decode("utf-8")
        except UnicodeDecodeError:
            entry["binary"] = True
        output[relative.as_posix()] = entry
    return output


def _portable_snapshot_content(
    relative: Path,
    content: bytes,
) -> bytes:
    if relative.as_posix() != "manifest.json":
        return content
    payload = json.loads(content.decode("utf-8"))
    if payload.get("bootstrap_root") is not None:
        payload["bootstrap_root"] = "<bootstrap-root>"
    return (
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def golden_text(fixture_name: str, filename: str) -> str:
    return (
        GOLDEN_ROOT / fixture_name / filename
    ).read_text(encoding="utf-8")


def golden_json(
    fixture_name: str,
    filename: str,
) -> dict[str, dict[str, object]]:
    return json.loads(golden_text(fixture_name, filename))


def update_golden(
    fixture_name: str,
    result: FixtureMigrationResult,
) -> None:
    if fixture_name not in FIXTURE_NAMES:
        raise ValueError("cannot update an unknown migration golden")
    destination = GOLDEN_ROOT / fixture_name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "preview.md").write_text(
        result.preview,
        encoding="utf-8",
        newline="\n",
    )
    (destination / "tree.json").write_text(
        json.dumps(
            result.tree,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _classification_response(request) -> ClassificationResponse:
    decisions = []
    for artifact in request.artifacts:
        if artifact.original_kind.value == "rules":
            kind = DecisionKind.COMMON_RULE
            name = (
                "claude-shared-rules"
                if "CLAUDE" in artifact.relative_label
                else "codex-shared-rules"
            )
        else:
            kind = DecisionKind.UNSUPPORTED
            name = None
        decisions.append(
            ClassificationDecision(
                artifact_id=artifact.artifact_id,
                kind=kind,
                name=name,
                rationale=(
                    "Portable shared rules."
                    if kind is DecisionKind.COMMON_RULE
                    else "No proven portable semantic mapping."
                ),
                confidence="high",
            )
        )
    return ClassificationResponse(
        schema_version=1,
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        decisions=tuple(decisions),
    )


def _copy_fixture(source: Path, home: Path) -> None:
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if child.name == "SOURCE.md":
            continue
        target = home / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        elif child.is_file():
            shutil.copy2(child, target)
