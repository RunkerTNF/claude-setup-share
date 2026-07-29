# Agent Workflow Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free Python manager that can inspect a host, plan and apply a neutral `.agents` layout, detect drift, verify the result, and roll back a journaled transaction.

**Architecture:** A small `src/agent_workflow` package separates immutable serialized models, filesystem boundary checks, neutral layout planning, a journaled transaction engine, and diagnostics. The CLI exposes `scan`, `plan init`, `apply`, `doctor`, and `rollback`; later plans add adapters and migration without bypassing these interfaces.

**Tech Stack:** Python 3.11+ standard library at runtime; `pytest` as a development-only dependency; `argparse`, `dataclasses`, `enum`, `pathlib`, `hashlib`, `json`, `base64`, `tempfile`, and `os.replace`.

## Global Constraints

- Python 3.11 or newer is the only required runtime.
- The installed manager has no third-party Python dependencies.
- Windows, macOS, and Linux are supported.
- Canonical global state lives under `~/.agents/`; canonical project state lives under `<repo>/.agents/`.
- Dry-run performs no writes.
- Writes must remain inside explicitly allowed home or project roots.
- Source hash mismatch, unsafe path, invalid schema, or backup failure is blocking.
- Generated-file drift is never overwritten silently.
- Transactions use verified backups, per-file atomic replacement, a journal, and complete-scope rollback.
- No implementation task may introduce agent-specific Claude or Codex behavior; that belongs to Plan 2.

---

## File Map

- `pyproject.toml`: build metadata, Python floor, console script, and dev-only test dependency.
- `src/agent_workflow/__init__.py`: package version.
- `src/agent_workflow/__main__.py`: `python -m agent_workflow` entrypoint.
- `src/agent_workflow/cli.py`: parser and command dispatch only.
- `src/agent_workflow/errors.py`: typed user-facing failures and exit codes.
- `src/agent_workflow/model.py`: shared enums and immutable value objects.
- `src/agent_workflow/manifest.py`: workflow manifest schema and JSON I/O.
- `src/agent_workflow/plan.py`: write operation and transaction plan schema.
- `src/agent_workflow/paths.py`: host roots, project discovery, containment, and symlink checks.
- `src/agent_workflow/hashing.py`: SHA-256 helpers.
- `src/agent_workflow/scan.py`: read-only host snapshot.
- `src/agent_workflow/resources.py`: validated source-or-zipapp resource loading.
- `src/agent_workflow/layout.py`: neutral global/project layout planner.
- `src/agent_workflow/transactions/`: lock, backup, journal, apply, and rollback.
- `src/agent_workflow/doctor.py`: manifest, hash, reference, and layout diagnostics.
- `src/agent_workflow/portability.py`: portable Agent Skill validation.
- `templates/core/`: initial neutral rules and memory index templates.
- `tests/`: unit and integration coverage.
- `.github/workflows/ci.yml`: Windows/macOS/Linux matrix.

### Task 1: Package and CLI Contract

**Files:**
- Create: `pyproject.toml`
- Create: `src/agent_workflow/__init__.py`
- Create: `src/agent_workflow/__main__.py`
- Create: `src/agent_workflow/cli.py`
- Create: `src/agent_workflow/errors.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces: `agent_workflow.cli.build_parser() -> argparse.ArgumentParser`
- Produces: `agent_workflow.cli.main(argv: Sequence[str] | None = None) -> int`
- Produces: `AgentWorkflowError(message: str, exit_code: int = 2)`
- Produces: `UnsafePathError`, `SchemaValidationError`,
  `SourceChangedError`, `BackupError`, and `TransactionBusyError`

- [ ] **Step 1: Add packaging metadata and the failing CLI tests**

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-workflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.3"]

[project.scripts]
agent-workflow = "agent_workflow.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```python
# tests/test_cli.py
from agent_workflow.cli import build_parser, main


def test_parser_exposes_foundation_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "scan" in help_text
    assert "plan" in help_text
    assert "apply" in help_text
    assert "doctor" in help_text
    assert "rollback" in help_text


def test_main_returns_zero_for_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "agent-workflow 0.1.0"
```

- [ ] **Step 2: Run the tests and verify the missing-package failure**

Run: `python -m pytest tests/test_cli.py -v`

Expected: collection fails because `agent_workflow` does not exist.

- [ ] **Step 3: Implement the minimal package and parser**

```python
# src/agent_workflow/__init__.py
__version__ = "0.1.0"
```

```python
# src/agent_workflow/errors.py
class AgentWorkflowError(Exception):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class UnsafePathError(AgentWorkflowError):
    pass


class SchemaValidationError(AgentWorkflowError):
    pass


class SourceChangedError(AgentWorkflowError):
    pass


class BackupError(AgentWorkflowError):
    pass


class TransactionBusyError(AgentWorkflowError):
    pass
```

```python
# src/agent_workflow/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from . import __version__
from .errors import AgentWorkflowError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workflow")
    parser.add_argument("--version", action="version", version=f"agent-workflow {__version__}")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("scan")
    plan = subcommands.add_parser("plan")
    plan.add_subparsers(dest="plan_command").add_parser("init")
    subcommands.add_parser("apply")
    subcommands.add_parser("doctor")
    subcommands.add_parser("rollback")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            parser.print_help()
        return 0
    except AgentWorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code
```

```python
# src/agent_workflow/__main__.py
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_cli.py -v`

Expected: both tests pass.

- [ ] **Step 5: Commit the package skeleton**

```bash
git add pyproject.toml src/agent_workflow tests/test_cli.py
git commit -m "build: scaffold agent workflow CLI"
```

### Task 2: Stable Models and JSON Schemas

**Files:**
- Create: `src/agent_workflow/model.py`
- Create: `src/agent_workflow/manifest.py`
- Create: `src/agent_workflow/plan.py`
- Create: `tests/test_manifest.py`
- Create: `tests/test_plan.py`

**Interfaces:**
- Produces: `Scope`, `ProjectProfile`, `Severity`, `Ownership`
- Produces: `WorkflowManifest.to_json() -> str`
- Produces: `WorkflowManifest.from_json(raw: str) -> WorkflowManifest`
- Produces: `WriteOperation.from_bytes(root_id, path, content, expected_sha256, ownership) -> WriteOperation`
- Produces: `WriteOperation.content_bytes() -> bytes`
- Produces: `DeleteOperation(root_id, path, expected_sha256, ownership)`
- Produces: `TransactionPlan.to_json() -> str`
- Produces: `TransactionPlan.from_json(raw: str) -> TransactionPlan`

- [ ] **Step 1: Write round-trip and validation tests**

```python
# tests/test_manifest.py
from agent_workflow.manifest import WorkflowManifest
from agent_workflow.model import ProjectProfile, Scope


def test_manifest_round_trip_is_stable() -> None:
    manifest = WorkflowManifest(
        schema_version=1,
        generator_version="0.1.0",
        scope=Scope.PROJECT,
        profile=ProjectProfile.SPLIT,
        targets=("codex", "claude"),
        generated_files={"neutral:RULES.md": "a" * 64},
    )
    assert WorkflowManifest.from_json(manifest.to_json()) == manifest


def test_global_manifest_rejects_project_profile() -> None:
    manifest = WorkflowManifest(
        schema_version=1,
        generator_version="0.1.0",
        scope=Scope.GLOBAL,
        profile=ProjectProfile.LOCAL,
        targets=(),
        generated_files={},
    )
    try:
        manifest.validate()
    except ValueError as error:
        assert "global manifest cannot have a project profile" in str(error)
    else:
        raise AssertionError("validation should fail")
```

```python
# tests/test_plan.py
from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation


def test_binary_write_round_trip() -> None:
    operation = WriteOperation.from_bytes(
        root_id="neutral",
        path="workflow/agent-workflow.pyz",
        content=b"\x00zip",
        expected_sha256=None,
        ownership=Ownership.GENERATED,
    )
    plan = TransactionPlan.new(
        scope_root="/tmp/home/.agents",
        target_roots={"neutral": "/tmp/home/.agents", "scope": "/tmp/home"},
        allowed_roots=("/tmp/home",),
        operations=(operation,),
    )
    restored = TransactionPlan.from_json(plan.to_json())
    assert restored.operations[0].content_bytes() == b"\x00zip"


def test_delete_round_trip_is_tagged() -> None:
    operation = DeleteOperation(
        root_id="scope",
        path="legacy/CLAUDE.md",
        expected_sha256="a" * 64,
        ownership=Ownership.GENERATED,
    )
    plan = TransactionPlan.new(
        scope_root="/tmp/project/.agents",
        target_roots={"neutral": "/tmp/project/.agents", "scope": "/tmp/project"},
        allowed_roots=("/tmp/project",),
        operations=(operation,),
    )

    restored = TransactionPlan.from_json(plan.to_json())

    assert isinstance(restored.operations[0], DeleteOperation)
    assert restored.operations[0].path == "legacy/CLAUDE.md"
```

- [ ] **Step 2: Run the tests and verify imports fail**

Run: `python -m pytest tests/test_manifest.py tests/test_plan.py -v`

Expected: FAIL because the model modules do not exist.

- [ ] **Step 3: Implement the immutable model layer**

```python
# src/agent_workflow/model.py
from enum import StrEnum


class Scope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"


class ProjectProfile(StrEnum):
    LOCAL = "local"
    SHARED = "shared"
    SPLIT = "split"


class Severity(StrEnum):
    BLOCKING = "blocking"
    CONFLICT = "conflict"
    WARNING = "warning"
    INFO = "info"


class Ownership(StrEnum):
    CANONICAL = "canonical"
    GENERATED = "generated"
    UNMANAGED = "unmanaged"
```

```python
# src/agent_workflow/manifest.py
from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from .model import ProjectProfile, Scope


@dataclass(frozen=True)
class WorkflowManifest:
    schema_version: int
    generator_version: str
    scope: Scope
    profile: ProjectProfile | None
    targets: tuple[str, ...]
    generated_files: dict[str, str]

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"unsupported schema version: {self.schema_version}")
        if self.scope is Scope.GLOBAL and self.profile is not None:
            raise ValueError("global manifest cannot have a project profile")
        if self.scope is Scope.PROJECT and self.profile is None:
            raise ValueError("project manifest requires a project profile")

    def to_json(self) -> str:
        self.validate()
        payload = asdict(self)
        payload["scope"] = self.scope.value
        payload["profile"] = self.profile.value if self.profile else None
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "WorkflowManifest":
        payload = json.loads(raw)
        result = cls(
            schema_version=payload["schema_version"],
            generator_version=payload["generator_version"],
            scope=Scope(payload["scope"]),
            profile=ProjectProfile(payload["profile"]) if payload["profile"] else None,
            targets=tuple(payload["targets"]),
            generated_files=dict(payload["generated_files"]),
        )
        result.validate()
        return result
```

Manifest `generated_files` keys use `<root_id>:<relative-path>` with the same
`neutral` and `scope` IDs as transaction operations. Validation rejects an
unknown root ID, absolute path, parent traversal, duplicate normalized key, or
non-hex SHA-256.

Implement `src/agent_workflow/plan.py` with `base64.b64encode` and
`base64.b64decode`, immutable dataclasses, UUID plan IDs, UTC ISO timestamps,
sorted JSON output, and strict `schema_version == 1` validation. Use these exact
public fields:

```python
@dataclass(frozen=True)
class WriteOperation:
    root_id: str
    path: str
    content_b64: str
    expected_sha256: str | None
    ownership: Ownership


@dataclass(frozen=True)
class DeleteOperation:
    root_id: str
    path: str
    expected_sha256: str
    ownership: Ownership


FileOperation = WriteOperation | DeleteOperation


@dataclass(frozen=True)
class TransactionPlan:
    schema_version: int
    plan_id: str
    created_at: str
    scope_root: str
    target_roots: dict[str, str]
    allowed_roots: tuple[str, ...]
    operations: tuple[FileOperation, ...]
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
```

Serialize each operation with a required discriminator:
`{"kind": "write", ...}` or `{"kind": "delete", ...}`. Reject unknown kinds,
unknown keys, unknown `root_id` values, absolute operation paths, parent
traversal, delete operations without an expected source hash, and duplicate
resolved target paths. `target_roots` must contain exactly `neutral` and
`scope`; every resolved target root must itself be contained by one of
`allowed_roots`.

- [ ] **Step 4: Run focused and package tests**

Run: `python -m pytest tests/test_manifest.py tests/test_plan.py tests/test_cli.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the schemas**

```bash
git add src/agent_workflow/model.py src/agent_workflow/manifest.py src/agent_workflow/plan.py tests/test_manifest.py tests/test_plan.py
git commit -m "feat: define workflow manifests and plans"
```

### Task 3: Safe Paths, Hashing, and Read-Only Scan

**Files:**
- Create: `src/agent_workflow/hashing.py`
- Create: `src/agent_workflow/paths.py`
- Create: `src/agent_workflow/scan.py`
- Create: `tests/test_paths.py`
- Create: `tests/test_scan.py`

**Interfaces:**
- Produces: `sha256_bytes(data: bytes) -> str`
- Produces: `sha256_file(path: Path) -> str | None`
- Produces: `HostPaths.discover(home: Path, cwd: Path) -> HostPaths`
- Produces: `resolve_write_target(root_id: str, relative_path: str, target_roots: Mapping[str, Path], allowed_roots: Sequence[Path]) -> Path`
- Produces: `scan_host(paths: HostPaths) -> HostSnapshot`

- [ ] **Step 1: Write containment, symlink, and scan tests**

```python
# tests/test_paths.py
from pathlib import Path
import pytest

from agent_workflow.paths import HostPaths, resolve_write_target


def test_discover_finds_git_project_without_running_git(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    paths = HostPaths.discover(home=tmp_path / "home", cwd=nested)
    assert paths.project_root == root.resolve()


def test_target_outside_allowed_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside allowed roots"):
        resolve_write_target(
            "scope",
            "file",
            {
                "neutral": tmp_path / "home" / ".agents",
                "scope": tmp_path / "other",
            },
            [tmp_path / "home"],
        )


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    link = home / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="symlink"):
        resolve_write_target(
            "scope",
            "link/file",
            {"neutral": home / ".agents", "scope": home},
            [home],
        )
```

```python
# tests/test_scan.py
from pathlib import Path

from agent_workflow.paths import HostPaths
from agent_workflow.scan import scan_host


def test_scan_is_read_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    home.mkdir()
    cwd.mkdir()
    before = sorted(tmp_path.rglob("*"))
    snapshot = scan_host(HostPaths.discover(home=home, cwd=cwd))
    assert snapshot.global_agents_exists is False
    assert sorted(tmp_path.rglob("*")) == before
```

- [ ] **Step 2: Run the tests and verify failures**

Run: `python -m pytest tests/test_paths.py tests/test_scan.py -v`

Expected: FAIL because path and scan helpers do not exist.

- [ ] **Step 3: Implement path and scan primitives**

Use `Path.resolve(strict=False)` for roots, walk parents to find `.git`, and
reject targets equal to an allowed root. Before accepting a target, inspect
each existing path component with `Path.is_symlink()` and ensure its resolved
target remains within an allowed root.

```python
# src/agent_workflow/scan.py
from dataclasses import dataclass
import platform
import sys

from .paths import HostPaths


@dataclass(frozen=True)
class HostSnapshot:
    os_name: str
    python_version: str
    home: str
    cwd: str
    project_root: str | None
    global_agents_exists: bool
    project_agents_exists: bool


def scan_host(paths: HostPaths) -> HostSnapshot:
    return HostSnapshot(
        os_name=platform.system().lower(),
        python_version=".".join(map(str, sys.version_info[:3])),
        home=str(paths.home),
        cwd=str(paths.cwd),
        project_root=str(paths.project_root) if paths.project_root else None,
        global_agents_exists=(paths.home / ".agents").exists(),
        project_agents_exists=bool(
            paths.project_root and (paths.project_root / ".agents").exists()
        ),
    )
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_paths.py tests/test_scan.py -v`

Expected: all tests pass on the current operating system; the symlink test may
skip only when the OS denies symlink creation.

- [ ] **Step 5: Commit safe discovery**

```bash
git add src/agent_workflow/hashing.py src/agent_workflow/paths.py src/agent_workflow/scan.py tests/test_paths.py tests/test_scan.py
git commit -m "feat: add safe host discovery"
```

### Task 4: Neutral Layout Planner

**Files:**
- Create: `src/agent_workflow/layout.py`
- Create: `src/agent_workflow/resources.py`
- Create: `templates/core/global-rules.md`
- Create: `templates/core/project-rules.md`
- Create: `templates/core/global-memory-index.md`
- Create: `templates/core/project-memory-index.md`
- Create: `tests/test_layout.py`

**Interfaces:**
- Consumes: `HostPaths`, `WorkflowManifest`, `TransactionPlan`, `WriteOperation`
- Produces: `load_bundled_resource(relative_path: str) -> bytes`
- Produces: `plan_neutral_init(paths, scope, profile, targets) -> TransactionPlan`

- [ ] **Step 1: Write global and project layout tests**

```python
# tests/test_layout.py
from pathlib import Path

from agent_workflow.layout import plan_neutral_init
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.paths import HostPaths


def operation_paths(plan) -> set[str]:
    return {operation.path.replace("\\", "/") for operation in plan.operations}


def test_global_plan_contains_neutral_core_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    plan = plan_neutral_init(
        HostPaths.discover(home=home, cwd=repo),
        scope=Scope.GLOBAL,
        profile=None,
        targets=(),
    )
    assert operation_paths(plan) == {
        "RULES.md",
        "manifest.json",
        "memory/MEMORY.md",
    }


def test_project_plan_includes_sessions_and_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (repo / ".git").mkdir()
    plan = plan_neutral_init(
        HostPaths.discover(home=home, cwd=repo),
        scope=Scope.PROJECT,
        profile=ProjectProfile.SPLIT,
        targets=("codex",),
    )
    assert "sessions/.gitkeep" in operation_paths(plan)
    manifest_write = next(op for op in plan.operations if op.path == "manifest.json")
    assert b'"profile": "split"' in manifest_write.content_bytes()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_layout.py -v`

Expected: FAIL because `plan_neutral_init` does not exist.

- [ ] **Step 3: Implement template loading and plan generation**

Implement `load_bundled_resource` with two explicit modes: first read
`agent_workflow/_bundled/<relative_path>` through `importlib.resources` when
running from the installed zipapp; otherwise read the validated
repository-relative `<checkout>/<relative_path>` when running from source.
Reject absolute paths and parent traversal in both modes.

`plan_neutral_init` must:

1. choose `~/.agents` or `<project>/.agents` as `scope_root`;
2. reject a project plan when no project root exists;
3. create a schema-version-1 manifest;
4. create write operations with the current on-disk hash as
   `expected_sha256`;
5. return conflicts instead of overwriting non-empty pre-existing canonical
   files that are not already described by a compatible manifest.

Implement the exact public signature
`plan_neutral_init(paths: HostPaths, scope: Scope, profile: ProjectProfile |
None, targets: tuple[str, ...]) -> TransactionPlan`. It resolves the scope
root, loads the three global or four project template outputs, computes an
expected hash for each existing target, builds the manifest bytes last, sorts
operations by normalized relative path, and returns `TransactionPlan.new` with
the home or project root as the sole allowed root and with `target_roots`
mapping `neutral` to its `.agents` child and `scope` to the home or project
root. Neutral layout writes use `root_id="neutral"`.

Plan 2's reproducible packager will copy top-level `templates/` into the
internal `_bundled/templates/` resource tree; Plan 1 tests exercise the source
fallback.

- [ ] **Step 4: Run layout and model tests**

Run: `python -m pytest tests/test_layout.py tests/test_manifest.py tests/test_plan.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the neutral planner**

```bash
git add src/agent_workflow/layout.py src/agent_workflow/resources.py templates/core tests/test_layout.py
git commit -m "feat: plan neutral agent workflow layout"
```

### Task 5: Journaled Apply, Backup, and Rollback

**Files:**
- Create: `src/agent_workflow/transactions/__init__.py`
- Create: `src/agent_workflow/transactions/lock.py`
- Create: `src/agent_workflow/transactions/backup.py`
- Create: `src/agent_workflow/transactions/journal.py`
- Create: `src/agent_workflow/transactions/engine.py`
- Create: `tests/test_transactions.py`

**Interfaces:**
- Consumes: `TransactionPlan`
- Produces: `apply_plan(plan: TransactionPlan) -> TransactionJournal`
- Produces: `rollback_transaction(journal_path: Path) -> TransactionJournal`
- Produces: `TransactionJournal.to_json() -> str`

- [ ] **Step 1: Write apply, no-clobber, and rollback tests**

```python
# tests/test_transactions.py
from pathlib import Path
import pytest

from agent_workflow.errors import SourceChangedError
from agent_workflow.model import Ownership
from agent_workflow.plan import DeleteOperation, TransactionPlan, WriteOperation
from agent_workflow.transactions.engine import apply_plan, rollback_transaction


def make_plan(root: Path, expected: str | None) -> TransactionPlan:
    operation = WriteOperation.from_bytes(
        root_id="neutral",
        path="RULES.md",
        content=b"# Rules\n",
        expected_sha256=expected,
        ownership=Ownership.CANONICAL,
    )
    return TransactionPlan.new(
        scope_root=str(root),
        target_roots={"neutral": str(root), "scope": str(root.parent)},
        allowed_roots=(str(root.parent),),
        operations=(operation,),
    )


def make_delete_plan(root: Path, expected: str) -> TransactionPlan:
    operation = DeleteOperation(
        root_id="neutral",
        path="legacy/CLAUDE.md",
        expected_sha256=expected,
        ownership=Ownership.GENERATED,
    )
    return TransactionPlan.new(
        scope_root=str(root),
        target_roots={"neutral": str(root), "scope": str(root.parent)},
        allowed_roots=(str(root.parent),),
        operations=(operation,),
    )


def test_apply_then_rollback_restores_bytes(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"old\n")
    from agent_workflow.hashing import sha256_file

    journal = apply_plan(make_plan(root, sha256_file(rules)))
    assert rules.read_bytes() == b"# Rules\n"
    rollback_transaction(Path(journal.journal_path))
    assert rules.read_bytes() == b"old\n"


def test_hash_mismatch_blocks_before_write(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    rules = root / "RULES.md"
    rules.write_bytes(b"changed\n")
    with pytest.raises(SourceChangedError, match="hash mismatch"):
        apply_plan(make_plan(root, "0" * 64))
    assert rules.read_bytes() == b"changed\n"


def test_delete_then_rollback_restores_bytes(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    legacy = root / "legacy" / "CLAUDE.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy\n")
    from agent_workflow.hashing import sha256_file

    journal = apply_plan(make_delete_plan(root, sha256_file(legacy)))
    assert not legacy.exists()

    rollback_transaction(Path(journal.journal_path))

    assert legacy.read_bytes() == b"legacy\n"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_transactions.py -v`

Expected: FAIL because the transaction package does not exist.

- [ ] **Step 3: Implement the transaction engine**

Use these rules:

- acquire `<scope_root>/.workflow.lock` with exclusive create;
- resolve every operation from its `root_id` and relative `path` through
  `target_roots`, then re-check containment against `allowed_roots`;
- verify every target and expected hash before creating the first replacement;
- write backups under `<scope_root>/workflow/backups/<transaction-id>/`;
- store raw original bytes plus a JSON inventory containing relative path,
  existence, and SHA-256;
- request user-only backup directory/file modes where the platform supports
  them, warn when that protection cannot be applied, and never delete backups
  automatically;
- stage write-operation bytes under
  `<scope_root>/workflow/staging/<transaction-id>/`; delete operations have no
  staged payload;
- write a journal with status `prepared`, change it to `committing`, replace
  write targets with `os.replace`, delete exact-hash targets, then mark
  `committed`;
- on any exception after `committing`, restore all originals from backup and
  mark `rolled_back`;
- release the lock in `finally`;
- refuse rollback when a current target hash differs from the committed hash.

Define the journal with these public fields:

```python
@dataclass(frozen=True)
class JournalEntry:
    root_id: str
    path: str
    operation_kind: str
    existed: bool
    before_sha256: str | None
    after_sha256: str | None

@dataclass(frozen=True)
class TransactionJournal:
    schema_version: int
    transaction_id: str
    scope_root: str
    target_roots: dict[str, str]
    allowed_roots: tuple[str, ...]
    status: str
    entries: tuple[JournalEntry, ...]
    backup_root: str
    journal_path: str
```

- [ ] **Step 4: Run transaction and full foundation tests**

Run: `python -m pytest tests/test_transactions.py -v`

Expected: apply and rollback tests pass.

Run: `python -m pytest -v`

Expected: all tests pass.

- [ ] **Step 5: Commit transaction safety**

```bash
git add src/agent_workflow/transactions tests/test_transactions.py
git commit -m "feat: apply and roll back workflow plans"
```

### Task 6: Doctor and Portable Skill Lint

**Files:**
- Create: `src/agent_workflow/doctor.py`
- Create: `src/agent_workflow/portability.py`
- Create: `tests/test_doctor.py`
- Create: `tests/test_portability.py`

**Interfaces:**
- Produces: `Diagnostic(severity, code, path, message)`
- Produces: `run_doctor(scope_root: Path) -> tuple[Diagnostic, ...]`
- Produces: `lint_skill(skill_dir: Path) -> tuple[Diagnostic, ...]`

- [ ] **Step 1: Write diagnostic and portability tests**

```python
# tests/test_portability.py
from pathlib import Path

from agent_workflow.portability import lint_skill


def test_portable_skill_accepts_standard_core(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code changes.\n---\n\nRead references/checklist.md.\n",
        encoding="utf-8",
    )
    assert lint_skill(skill) == ()


def test_vendor_syntax_is_rejected_from_core(tmp_path: Path) -> None:
    skill = tmp_path / "review"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code.\nallowed-tools: Bash\n---\n\nUse ${CLAUDE_SKILL_DIR}.\n",
        encoding="utf-8",
    )
    codes = {item.code for item in lint_skill(skill)}
    assert codes == {"portable.frontmatter", "portable.vendor-token"}
```

```python
# tests/test_doctor.py
from pathlib import Path

from agent_workflow.doctor import run_doctor


def test_doctor_reports_generated_hash_drift(tmp_path: Path) -> None:
    root = tmp_path / ".agents"
    root.mkdir()
    (root / "manifest.json").write_text(
        '{"schema_version":1,"generator_version":"0.1.0","scope":"global",'
        '"profile":null,"targets":[],"generated_files":{"entry.md":"deadbeef"}}\n',
        encoding="utf-8",
    )
    (root / "entry.md").write_text("changed\n", encoding="utf-8")
    assert any(item.code == "generated.drift" for item in run_doctor(root))
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_doctor.py tests/test_portability.py -v`

Expected: FAIL because diagnostic modules do not exist.

- [ ] **Step 3: Implement diagnostics**

Parse only the YAML frontmatter subset needed for `name` and `description`
without a YAML dependency: locate the opening and closing `---` lines and
accept scalar `key: value` pairs. Emit blocking diagnostics for missing
`SKILL.md`, missing name/description, invalid kebab-case name, name-directory
mismatch, missing referenced relative files, or vendor tokens in the portable
core.

`run_doctor` must validate the manifest, compare generated hashes, ensure
manifest paths stay below `scope_root`, lint every direct child under
`skills/`, detect missing `RULES.md` and `memory/MEMORY.md`, and report any
text reference to the bootstrap repository path stored in the manifest.

- [ ] **Step 4: Run diagnostic and full tests**

Run: `python -m pytest tests/test_doctor.py tests/test_portability.py -v`

Expected: all focused tests pass.

Run: `python -m pytest -v`

Expected: all tests pass.

- [ ] **Step 5: Commit diagnostics**

```bash
git add src/agent_workflow/doctor.py src/agent_workflow/portability.py tests/test_doctor.py tests/test_portability.py
git commit -m "feat: validate neutral workflow state"
```

### Task 7: Wire Commands and Cross-Platform CI

**Files:**
- Modify: `src/agent_workflow/cli.py`
- Create: `tests/integration/test_cli_workflow.py`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` with temporary sections “Development” and “Foundation CLI”

**Interfaces:**
- Consumes: all Plan 1 public interfaces.
- Produces CLI:
  - `agent-workflow scan [--home PATH] [--cwd PATH] --json`
  - `agent-workflow plan init --scope global|project [--profile local|shared|split] [--target NAME ...] --output PLAN`
  - `agent-workflow apply PLAN`
  - `agent-workflow doctor --scope-root PATH --json`
  - `agent-workflow rollback JOURNAL`

- [ ] **Step 1: Write an end-to-end fake-home test**

```python
# tests/integration/test_cli_workflow.py
from pathlib import Path

from agent_workflow.cli import main


def test_plan_apply_doctor_and_rollback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    plan_file = tmp_path / "plan.json"
    home.mkdir()
    repo.mkdir()

    assert main([
        "plan", "init", "--scope", "global",
        "--home", str(home), "--cwd", str(repo),
        "--output", str(plan_file),
    ]) == 0
    assert not (home / ".agents").exists()

    assert main(["apply", str(plan_file)]) == 0
    assert (home / ".agents" / "RULES.md").exists()

    assert main(["doctor", "--scope-root", str(home / ".agents")]) == 0
    journals = list((home / ".agents" / "workflow" / "journals").glob("*.json"))
    assert len(journals) == 1

    assert main(["rollback", str(journals[0])]) == 0
    assert not (home / ".agents" / "RULES.md").exists()
```

- [ ] **Step 2: Run the integration test and verify command failure**

Run: `python -m pytest tests/integration/test_cli_workflow.py -v`

Expected: FAIL because CLI arguments and dispatch are not wired.

- [ ] **Step 3: Wire command handlers and JSON output**

Keep `cli.py` as dispatch only. Put each handler in the module that owns the
operation and have it return serializable dataclasses or an exit code. Print
machine-readable JSON to stdout when `--json` is present and concise
human-readable summaries otherwise. Map blocking errors to exit code `2`,
conflicts to `3`, and doctor warnings-only to `0`.

Add this CI matrix:

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python: ["3.11", "3.x"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install -e .[dev]
      - run: python -m pytest -v
```

- [ ] **Step 4: Run all verification**

Run: `python -m pytest -v`

Expected: all tests pass.

Run: `python -m agent_workflow --help`

Expected: all five foundation commands and their help text are present.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit the complete foundation slice**

```bash
git add src/agent_workflow/cli.py tests/integration .github/workflows/ci.yml README.md
git commit -m "feat: complete neutral workflow foundation"
```

## Plan 1 Completion Gate

Run:

```bash
python -m pytest -v
python -m agent_workflow --version
python -m agent_workflow --help
git status --short
```

Expected:

- all tests pass;
- version is `0.1.0`;
- help lists `scan`, `plan`, `apply`, `doctor`, and `rollback`;
- no uncommitted implementation files remain.

Do not begin Plan 2 until the hosted Windows, macOS, and Linux CI matrix passes.
