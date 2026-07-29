# Agent Workflow Adapters and Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the neutral foundation into a self-contained setup system with a stable adapter contract, guaranteed Claude Code and Codex adapters, selectable project profiles, persistent installation, and deterministic golden output.

**Architecture:** Declarative adapter manifests describe detection, capabilities, discovery paths, and sensitive keys; focused Python renderers handle native entrypoints and validation. Setup composes Plan 1's neutral layout and transaction primitives with adapter writes, packages the manager as a standard-library zipapp, and installs a portable setup skill into canonical `.agents/skills`.

**Tech Stack:** Plan 1 Python package and schemas; Python standard-library `Protocol`, `subprocess`, `shutil`, `importlib.resources`, `zipapp`, and `tomllib`; development-only `pytest` golden tests.

## Global Constraints

- Plan 1 completion and green hosted CI are prerequisites.
- Claude Code and Codex are guaranteed adapters and release-blocking.
- Common rules are referenced, never copied into native entrypoints.
- Canonical skills remain under `.agents/skills`.
- Agent-specific content lives in `.agents/overlays/<agent>/`.
- Native generated files record generator version and source hash.
- Existing native files are conflicts unless they already match the manager manifest; setup never silently replaces them.
- Setup detects multiple agents and applies only user-selected targets.
- The installed manager must work after the bootstrap repository is deleted.
- The persistent manager and management skills install globally under
  `~/.agents/workflow/` and `~/.agents/skills/`; project setup consumes them
  and does not create a project-local manager copy.
- Symlinks and junctions are not required for normal setup.
- Project profiles are selected per project: `local`, `shared`, or `split`.
- Agent-specific settings conversion is deferred to Plan 3; this plan renders only fresh setup state.
- Additional adapters are loaded only from built-ins, the managed
  `~/.agents/workflow/adapters/` directory, or an explicit `--adapter-dir`;
  an adapter containing Python code is shown as executable trusted input
  before installation.

---

## File Map

- `src/agent_workflow/adapters/base.py`: adapter context, detection, capability, and protocol.
- `src/agent_workflow/adapters/manifest.py`: declarative `adapter.json` validation.
- `src/agent_workflow/adapters/registry.py`: built-in adapter loading and target selection.
- `src/agent_workflow/adapters/codex/`: Codex manifest, renderer, and templates.
- `src/agent_workflow/adapters/claude/`: Claude manifest, renderer, and templates.
- `src/agent_workflow/skills.py`: canonical skill discovery and native wrapper rendering.
- `src/agent_workflow/profiles.py`: exact local/shared/split path policy and managed ignore blocks.
- `src/agent_workflow/package.py`: reproducible zipapp assembly.
- `src/agent_workflow/setup.py`: scan and setup-plan composition.
- `skills/agent-workflow-setup/`: portable installed management skill.
- `tests/golden/`: exact generated trees for both guaranteed adapters.
- `docs/live-smoke.md`: fresh-session verification commands.

### Task 1: Adapter Protocol, Manifest, and Registry

**Files:**
- Create: `src/agent_workflow/adapters/__init__.py`
- Create: `src/agent_workflow/adapters/base.py`
- Create: `src/agent_workflow/adapters/declarative.py`
- Create: `src/agent_workflow/adapters/manifest.py`
- Create: `src/agent_workflow/adapters/registry.py`
- Create: `tests/fixtures/adapters/declarative/fixture-agent/adapter.json`
- Create: `tests/fixtures/adapters/declarative/fixture-agent/templates/project.md`
- Create: `tests/adapters/test_registry.py`

**Interfaces:**
- Consumes: `HostPaths`, `Diagnostic`, `WriteOperation`, `Scope`, `ProjectProfile`
- Produces: `AdapterContext`
- Produces: `AdapterDetection`
- Produces: `AdapterCapability`
- Produces: `AgentAdapter` protocol
- Produces: `DeclarativeAdapter`
- Produces: `AdapterRegistry.from_directories(paths, trusted_python_ids=()) -> AdapterRegistry`
- Produces: `AdapterRegistry.detect_all(context) -> tuple[AdapterDetection, ...]`
- Produces: `AdapterRegistry.require(ids) -> tuple[AgentAdapter, ...]`

- [ ] **Step 1: Write manifest and registry tests**

```python
# tests/adapters/test_registry.py
from pathlib import Path
import pytest

from agent_workflow.adapters.base import AdapterCapability, CapabilityStatus
from agent_workflow.adapters.manifest import AdapterManifest
from agent_workflow.adapters.registry import AdapterRegistry


def test_manifest_requires_unique_id_and_version_command() -> None:
    manifest = AdapterManifest.from_dict({
        "schema_version": 1,
        "id": "codex",
        "display_name": "Codex",
        "executables": ["codex"],
        "version_args": ["--version"],
        "supported_versions": [],
        "global": {
            "discovery_paths": [".codex/AGENTS.md"],
            "instruction_entrypoints": [],
            "skill_locations": [{"path": ".agents/skills", "mode": "direct"}],
        },
        "project": {
            "discovery_paths": ["AGENTS.md", "AGENTS.override.md"],
            "instruction_entrypoints": [],
            "skill_locations": [{"path": ".agents/skills", "mode": "direct"}],
        },
        "capabilities": {"skills": "supported"},
        "sensitive_keys": ["api_key"],
        "validation": [],
        "smoke": [],
    })
    assert manifest.id == "codex"
    assert manifest.capabilities["skills"] is CapabilityStatus.SUPPORTED


def test_registry_rejects_duplicate_adapter_ids(tmp_path: Path) -> None:
    adapter = object()
    with pytest.raises(ValueError, match="duplicate adapter id"):
        AdapterRegistry.from_pairs((("same", adapter), ("same", adapter)))


def test_unknown_target_is_explicit() -> None:
    registry = AdapterRegistry.from_pairs(())
    with pytest.raises(ValueError, match="unknown adapter: pi"):
        registry.require(("pi",))


def test_declarative_adapter_loads_without_python_module() -> None:
    registry = AdapterRegistry.from_directories((
        Path("tests/fixtures/adapters/declarative"),
    ))

    adapter = registry.require(("fixture-agent",))[0]

    assert adapter.id == "fixture-agent"
    assert type(adapter).__name__ == "DeclarativeAdapter"
```

- [ ] **Step 2: Run tests and verify missing adapter modules**

Run: `python -m pytest tests/adapters/test_registry.py -v`

Expected: FAIL during import.

- [ ] **Step 3: Implement the public adapter types**

```python
# src/agent_workflow/adapters/base.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from agent_workflow.doctor import Diagnostic
from agent_workflow.model import ProjectProfile, Scope
from agent_workflow.plan import WriteOperation


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AdapterCapability:
    name: str
    status: CapabilityStatus
    note: str = ""


@dataclass(frozen=True)
class AdapterDetection:
    adapter_id: str
    installed: bool
    executable: str | None
    version: str | None
    warning: str | None = None


@dataclass(frozen=True)
class AdapterContext:
    home: Path
    project_root: Path | None
    neutral_root: Path
    scope: Scope
    profile: ProjectProfile | None
    generator_version: str


class AgentAdapter(Protocol):
    id: str

    def detect(self, context: AdapterContext) -> AdapterDetection:
        raise NotImplementedError

    def plan_entrypoints(
        self, context: AdapterContext
    ) -> tuple[WriteOperation, ...]:
        raise NotImplementedError

    def validate(self, context: AdapterContext) -> tuple[Diagnostic, ...]:
        raise NotImplementedError
```

Implement `AdapterManifest.from_dict` with strict schema version `1`,
kebab-case IDs, non-empty executable lists, `CapabilityStatus` conversion, and
these closed top-level keys:

- `schema_version`, `id`, `display_name`, `executables`, `version_args`,
  `supported_versions`;
- `global`, `project`, each containing `discovery_paths`,
  `instruction_entrypoints`, and `skill_locations`;
- `capabilities`, `sensitive_keys`, `validation`, and `smoke`.

An instruction entrypoint declares a relative target, packaged template, and
profile list. A skill location declares `direct` or `wrapper`. All manifest
paths must be relative and contained by the adapter package or selected scope.
`supported_versions` is a sorted list of exact CLI version strings that passed
the recorded live smoke; an empty list produces an unknown-version warning
rather than a false compatibility claim.

Implement `DeclarativeAdapter` for detection, fixed-template entrypoints,
direct/wrapper skill locations, validation paths, and smoke text. Implement
`AdapterRegistry.from_pairs`, `from_directories`, `require`, and `detect_all`
with deterministic ID ordering. `from_directories` scans only immediate child
packages. It uses `DeclarativeAdapter` when `adapter.py` is absent. It imports
Python only when the manifest ID appears in `trusted_python_ids`; otherwise
the package is reported as requiring trust and cannot be selected. A trusted
package with `adapter.py` must export
`create_adapter(manifest, package_root)`. Duplicate IDs across directories are
blocking and the registry never imports files found by legacy migration scans.

- [ ] **Step 4: Run adapter tests and the Plan 1 suite**

Run: `python -m pytest tests/adapters/test_registry.py -v`

Expected: all adapter tests pass.

Run: `python -m pytest -v`

Expected: Plan 1 tests remain green.

- [ ] **Step 5: Commit the adapter contract**

```bash
git add src/agent_workflow/adapters tests/adapters/test_registry.py tests/fixtures/adapters
git commit -m "feat: define agent adapter contract"
```

### Task 2: Codex Adapter

**Files:**
- Create: `src/agent_workflow/adapters/codex/__init__.py`
- Create: `src/agent_workflow/adapters/codex/adapter.json`
- Create: `src/agent_workflow/adapters/codex/adapter.py`
- Create: `src/agent_workflow/adapters/codex/templates/global-agents.md`
- Create: `src/agent_workflow/adapters/codex/templates/project-agents.md`
- Create: `src/agent_workflow/adapters/codex/templates/project-agents-override.md`
- Create: `tests/adapters/test_codex.py`

**Interfaces:**
- Consumes: `AdapterContext`, `AdapterManifest`, Plan 1 hashing and write models.
- Produces: `CodexAdapter.detect`
- Produces: `CodexAdapter.plan_entrypoints`
- Produces: `CodexAdapter.validate`

- [ ] **Step 1: Write detection and rendering tests**

```python
# tests/adapters/test_codex.py
from pathlib import Path

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.codex.adapter import CodexAdapter
from agent_workflow.model import ProjectProfile, Scope


def context(tmp_path: Path, scope: Scope, profile=None) -> AdapterContext:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    home.mkdir()
    project.mkdir()
    return AdapterContext(
        home=home,
        project_root=project,
        neutral_root=(home / ".agents") if scope is Scope.GLOBAL else (project / ".agents"),
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def test_global_codex_entrypoint_references_neutral_rules(tmp_path: Path) -> None:
    operations = CodexAdapter().plan_entrypoints(context(tmp_path, Scope.GLOBAL))
    assert len(operations) == 1
    assert operations[0].root_id == "scope"
    assert operations[0].path.replace("\\", "/") == ".codex/AGENTS.md"
    body = operations[0].content_bytes().decode()
    assert "~/.agents/RULES.md" in body
    assert "~/.agents/overlays/codex/RULES.md" in body
    assert "# source-sha256:" in body


def test_local_project_uses_override_and_preserves_root_agents_reference(tmp_path: Path) -> None:
    operations = CodexAdapter().plan_entrypoints(
        context(tmp_path, Scope.PROJECT, ProjectProfile.LOCAL)
    )
    assert operations[0].root_id == "scope"
    assert operations[0].path == "AGENTS.override.md"
    body = operations[0].content_bytes().decode()
    assert "Read `AGENTS.md` when it exists" in body
    assert ".agents/RULES.md" in body
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/adapters/test_codex.py -v`

Expected: FAIL because `CodexAdapter` does not exist.

- [ ] **Step 3: Implement Codex detection and templates**

Use this manifest capability baseline:

```json
{
  "schema_version": 1,
  "id": "codex",
  "display_name": "Codex",
  "executables": ["codex"],
  "version_args": ["--version"],
  "capabilities": {
    "rules": "supported",
    "skills": "supported",
    "commands": "partial",
    "subagents": "partial",
    "hooks": "supported",
    "permissions": "supported",
    "mcp": "supported"
  },
  "sensitive_keys": ["api_key", "bearer_token", "http_headers"]
}
```

Start `supported_versions` as an empty list, which makes detected versions
explicitly `UNKNOWN` until the release smoke records an exact passing version
in Plan 4. Declare global discovery
`.codex/AGENTS.md`, project discovery `AGENTS.md` and
`AGENTS.override.md`, direct global/project `.agents/skills` locations, the
three template-backed entrypoints listed in this task, validation of generated
entrypoint references, and the Codex steps later written to
`docs/live-smoke.md`.

Detection uses `shutil.which` and a five-second `subprocess.run` of
`codex --version`; timeout or non-zero exit yields `installed=true` with an
unknown-version warning.

The global template must instruct Codex, before its first response or action,
to read the common rules, read the Codex overlay when present, and then read
the applicable memory index. The project templates do the same for relative
`.agents` paths. Add a generated header with manager version and SHA-256 of the
referenced canonical rule inputs.

Every native entrypoint operation uses `root_id="scope"`; adapter renderers
never express a native path with `..` or an absolute path.

For `shared` and `split`, render `AGENTS.md`. For `local`, render
`AGENTS.override.md` and require reading an existing `AGENTS.md` before the
neutral local rules.

- [ ] **Step 4: Run Codex and full tests**

Run: `python -m pytest tests/adapters/test_codex.py -v`

Expected: all Codex tests pass.

Run: `python -m pytest -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Codex support**

```bash
git add src/agent_workflow/adapters/codex tests/adapters/test_codex.py
git commit -m "feat: add Codex setup adapter"
```

### Task 3: Claude Code Adapter

**Files:**
- Create: `src/agent_workflow/adapters/claude/__init__.py`
- Create: `src/agent_workflow/adapters/claude/adapter.json`
- Create: `src/agent_workflow/adapters/claude/adapter.py`
- Create: `src/agent_workflow/adapters/claude/templates/global-claude.md`
- Create: `src/agent_workflow/adapters/claude/templates/project-claude.md`
- Create: `src/agent_workflow/adapters/claude/templates/project-claude-local.md`
- Create: `tests/adapters/test_claude.py`

**Interfaces:**
- Consumes: the same stable adapter context as Codex.
- Produces: `ClaudeAdapter.detect`
- Produces: `ClaudeAdapter.plan_entrypoints`
- Produces: `ClaudeAdapter.validate`

- [ ] **Step 1: Write Claude import and profile tests**

```python
# tests/adapters/test_claude.py
from pathlib import Path

from agent_workflow.adapters.base import AdapterContext
from agent_workflow.adapters.claude.adapter import ClaudeAdapter
from agent_workflow.model import ProjectProfile, Scope


def make_context(tmp_path: Path, scope: Scope, profile=None) -> AdapterContext:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    return AdapterContext(
        home=home,
        project_root=repo,
        neutral_root=(home / ".agents") if scope is Scope.GLOBAL else (repo / ".agents"),
        scope=scope,
        profile=profile,
        generator_version="0.1.0",
    )


def test_global_claude_uses_native_imports(tmp_path: Path) -> None:
    operation = ClaudeAdapter().plan_entrypoints(
        make_context(tmp_path, Scope.GLOBAL)
    )[0]
    assert operation.root_id == "scope"
    assert operation.path.replace("\\", "/") == ".claude/CLAUDE.md"
    body = operation.content_bytes().decode()
    assert "@~/.agents/RULES.md" in body
    assert "@~/.agents/overlays/claude/RULES.md" in body


def test_local_project_uses_claude_local(tmp_path: Path) -> None:
    operation = ClaudeAdapter().plan_entrypoints(
        make_context(tmp_path, Scope.PROJECT, ProjectProfile.LOCAL)
    )[0]
    assert operation.root_id == "scope"
    assert operation.path == "CLAUDE.local.md"
    assert "@.agents/RULES.md" in operation.content_bytes().decode()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/adapters/test_claude.py -v`

Expected: FAIL because `ClaudeAdapter` does not exist.

- [ ] **Step 3: Implement Claude detection and imports**

Use a manifest parallel to Codex with executable `claude`, version args
`--version`, native global skill path `.claude/skills`, native project skill
path `.claude/skills`, and these capability statuses:

```json
{
  "rules": "supported",
  "skills": "supported",
  "commands": "supported",
  "subagents": "supported",
  "hooks": "supported",
  "permissions": "supported",
  "mcp": "supported"
}
```

Start `supported_versions` as an empty list with the same release-smoke rule as
Codex. Declare global discovery
`.claude/CLAUDE.md`, project discovery `CLAUDE.md` and `CLAUDE.local.md`,
wrapper skill locations, the three template-backed entrypoints listed in this
task, validation of imports and wrappers, and the Claude steps later written
to `docs/live-smoke.md`.

Render `~/.claude/CLAUDE.md` globally, `CLAUDE.md` for shared/split projects,
and `CLAUDE.local.md` for local projects. Use Claude's `@path` import syntax
for common rules, Claude overlays, and memory indexes. Omit an optional import
when its source file does not exist at plan time; do not create empty overlay
files merely to satisfy an import.
Every native entrypoint operation uses `root_id="scope"`.

- [ ] **Step 4: Run Claude, adapter, and full tests**

Run: `python -m pytest tests/adapters/test_claude.py tests/adapters/test_codex.py -v`

Expected: all guaranteed-adapter tests pass.

Run: `python -m pytest -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Claude support**

```bash
git add src/agent_workflow/adapters/claude tests/adapters/test_claude.py
git commit -m "feat: add Claude Code setup adapter"
```

### Task 4: Portable Skill Discovery and Native Wrappers

**Files:**
- Create: `src/agent_workflow/skills.py`
- Create: `tests/test_skills.py`
- Create: `tests/fixtures/skills/portable-review/SKILL.md`
- Create: `tests/fixtures/skills/portable-review/references/checklist.md`
- Modify: `src/agent_workflow/adapters/claude/adapter.py`
- Modify: `src/agent_workflow/adapters/codex/adapter.py`

**Interfaces:**
- Produces: `PortableSkill(name, description, root, source_sha256)`
- Produces: `discover_portable_skills(root: Path) -> tuple[PortableSkill, ...]`
- Produces: `render_native_skill_wrapper(skill, agent_id, canonical_path) -> bytes`
- Produces: `plan_skill_install(adapter, context, skills) -> tuple[WriteOperation, ...]`

- [ ] **Step 1: Write direct-consumer and wrapper tests**

```python
# tests/test_skills.py
from pathlib import Path

from agent_workflow.skills import (
    discover_portable_skills,
    render_native_skill_wrapper,
)


def test_discovery_reads_name_description_and_resources() -> None:
    root = Path("tests/fixtures/skills")
    skills = discover_portable_skills(root)
    assert [(item.name, item.description) for item in skills] == [
        ("portable-review", "Review pending code changes.")
    ]


def test_claude_wrapper_keeps_workflow_in_canonical_source() -> None:
    skill = discover_portable_skills(Path("tests/fixtures/skills"))[0]
    body = render_native_skill_wrapper(
        skill,
        agent_id="claude",
        canonical_path=Path("/home/user/.agents/skills/portable-review"),
    ).decode()
    assert "description: Review pending code changes." in body
    assert "Read the canonical `SKILL.md` completely" in body
    assert "/home/user/.agents/skills/portable-review/SKILL.md" in body
    assert "Review pending code changes." not in body.split("---", 2)[-1]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_skills.py -v`

Expected: FAIL because skill discovery and wrappers do not exist.

- [ ] **Step 3: Implement skill discovery and materialization**

Reuse Plan 1's portable frontmatter parser. Compute `source_sha256` over a
stable sequence of every regular file's relative POSIX path, NUL separator,
and raw bytes. Reject symlinked resources.

Codex is a direct consumer: it receives no copied skill operations. Its
generated rules entrypoint tells it to read `overlays/codex.md` inside a skill
when that file exists.

Claude receives a wrapper directory at its native global or project skill
root. The wrapper copies only portable discovery metadata and instructs Claude
to read the canonical `SKILL.md`, then `overlays/claude.md` when present, and
resolve all supporting resources relative to the canonical skill root.

Native wrapper paths are concrete generated paths; source templates and
portable skills must not contain a user-specific absolute path.
Canonical skill writes use `root_id="neutral"`. Claude wrapper writes use
`root_id="scope"`. Codex direct discovery creates no extra skill write.

- [ ] **Step 4: Run skill and adapter tests**

Run: `python -m pytest tests/test_skills.py tests/adapters -v`

Expected: all tests pass.

Run: `python -m pytest -v`

Expected: full suite passes.

- [ ] **Step 5: Commit skill materialization**

```bash
git add src/agent_workflow/skills.py src/agent_workflow/adapters tests/test_skills.py tests/fixtures/skills
git commit -m "feat: materialize portable skills for native agents"
```

### Task 5: Project Profiles and Managed Ignore Blocks

**Files:**
- Create: `src/agent_workflow/profiles.py`
- Create: `tests/test_profiles.py`
- Modify: `src/agent_workflow/layout.py`

**Interfaces:**
- Produces: `ProfilePolicy`
- Produces: `policy_for(profile: ProjectProfile) -> ProfilePolicy`
- Produces: `render_managed_ignore(existing: str, policy: ProfilePolicy) -> str`
- Produces: `plan_profile_files(project_root: Path, profile: ProjectProfile, manage_syncprotect: bool) -> tuple[WriteOperation, ...]`

- [ ] **Step 1: Write exact profile-policy tests**

```python
# tests/test_profiles.py
from agent_workflow.model import ProjectProfile
from agent_workflow.profiles import policy_for, render_managed_ignore


def test_local_profile_ignores_all_project_workflow_state() -> None:
    policy = policy_for(ProjectProfile.LOCAL)
    assert policy.gitignore_entries == (
        ".agents/",
        "AGENTS.override.md",
        "CLAUDE.local.md",
    )


def test_split_profile_keeps_shared_rules_and_skills() -> None:
    policy = policy_for(ProjectProfile.SPLIT)
    assert policy.gitignore_entries == (
        ".agents/memory/",
        ".agents/sessions/",
        ".agents/overlays/",
        "AGENTS.override.md",
        "CLAUDE.local.md",
    )


def test_managed_block_replaces_only_its_previous_content() -> None:
    existing = "dist/\n# BEGIN agent-workflow\nold/\n# END agent-workflow\n"
    rendered = render_managed_ignore(existing, policy_for(ProjectProfile.LOCAL))
    assert rendered.startswith("dist/\n")
    assert rendered.count("# BEGIN agent-workflow") == 1
    assert "old/" not in rendered
    assert ".agents/" in rendered
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_profiles.py -v`

Expected: FAIL because profile policies do not exist.

- [ ] **Step 3: Implement explicit profile policies**

Define:

```python
@dataclass(frozen=True)
class ProfilePolicy:
    profile: ProjectProfile
    gitignore_entries: tuple[str, ...]
    share_rules: bool
    share_memory: bool
    share_sessions: bool
    share_skills: bool
```

`shared` has no generated ignore entries and sets every share flag to `True`.
`local` sets every share flag to `False`. `split` shares rules and skills only.

Modify `.gitignore` through a single managed block. Modify `.syncprotect` with
the same entries only when that file already exists or the caller explicitly
sets `manage_syncprotect=True`. Every modification is a full-file
`WriteOperation` with `root_id="scope"` and the old hash as
`expected_sha256`.

- [ ] **Step 4: Run profile and layout tests**

Run: `python -m pytest tests/test_profiles.py tests/test_layout.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit project profiles**

```bash
git add src/agent_workflow/profiles.py src/agent_workflow/layout.py tests/test_profiles.py
git commit -m "feat: configure project storage profiles"
```

### Task 6: Persistent Zipapp and Setup Orchestration

**Files:**
- Create: `src/agent_workflow/package.py`
- Create: `src/agent_workflow/setup.py`
- Create: `SETUP.md`
- Create: `scripts/bootstrap.py`
- Create: `skills/agent-workflow-setup/SKILL.md`
- Create: `skills/agent-workflow-setup/references/flow.md`
- Create: `tests/test_package.py`
- Create: `tests/test_setup.py`
- Modify: `src/agent_workflow/cli.py`
- Modify: `src/agent_workflow/doctor.py`
- Modify: `tests/test_doctor.py`

**Interfaces:**
- Produces: `build_manager_zipapp(source_root: Path) -> bytes`
- Produces: `SetupRequest`
- Produces: `detect_setup_targets(context: AdapterContext, registry: AdapterRegistry) -> tuple[AdapterDetection, ...]`
- Produces: `build_setup_plan(request: SetupRequest) -> TransactionPlan`
- Extends: `run_doctor` with manifest-selected adapter validation
- Extends CLI with `scan --agents` and `plan setup`.

- [ ] **Step 1: Write zipapp independence and composed-plan tests**

```python
# tests/test_package.py
from pathlib import Path
import subprocess
import sys

from agent_workflow.package import build_manager_zipapp


def test_built_zipapp_runs_without_source_tree(tmp_path: Path) -> None:
    archive = tmp_path / "agent-workflow.pyz"
    archive.write_bytes(build_manager_zipapp(Path.cwd()))
    completed = subprocess.run(
        [sys.executable, str(archive), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "agent-workflow 0.1.0"
```

```python
# tests/test_setup.py
from pathlib import Path

from agent_workflow.model import Scope
from agent_workflow.setup import SetupRequest, build_setup_plan


def test_global_setup_composes_core_manager_skill_and_targets(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = Path.cwd()
    home.mkdir()
    request = SetupRequest(
        home=home,
        project_root=None,
        source_root=source,
        scope=Scope.GLOBAL,
        profile=None,
        targets=("claude", "codex"),
        manage_syncprotect=False,
        adapter_sources=(),
        trusted_adapter_ids=(),
    )
    plan = build_setup_plan(request)
    paths = {operation.path.replace("\\", "/") for operation in plan.operations}
    assert "workflow/agent-workflow.pyz" in paths
    assert "skills/agent-workflow-setup/SKILL.md" in paths
    assert any(path.endswith(".claude/CLAUDE.md") for path in paths)
    assert any(path.endswith(".codex/AGENTS.md") for path in paths)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_package.py tests/test_setup.py -v`

Expected: FAIL because zipapp and setup orchestration do not exist.

- [ ] **Step 3: Implement reproducible packaging and setup composition**

Build the zipapp from a temporary staging tree containing
`src/agent_workflow`, top-level `templates/` copied to
`agent_workflow/_bundled/templates/`, adapter packages, and
`skills/agent-workflow-setup/` copied under the internal resource path
`agent_workflow/_bundled/skills/`. Normalize archive timestamps to
`1980-01-01`, sort entries, and use
`agent_workflow.__main__:main` semantics through a generated `__main__.py`.
Two builds from the same source must return identical bytes.

Define:

```python
@dataclass(frozen=True)
class SetupRequest:
    home: Path
    project_root: Path | None
    source_root: Path
    scope: Scope
    profile: ProjectProfile | None
    targets: tuple[str, ...]
    manage_syncprotect: bool
    adapter_sources: tuple[Path, ...]
    trusted_adapter_ids: tuple[str, ...]
```

For global scope, `build_setup_plan` composes neutral layout operations, the
zipapp write at `workflow/agent-workflow.pyz`, the canonical setup-skill source
tree from the bundled zipapp resource, selected adapter entrypoints, and
native skill wrappers. For project
scope, it composes the neutral project layout, profile operations, selected
entrypoints, and wrappers, and first verifies that the global manager and setup
skill are installed. It returns conflicts when a native target exists without
a matching generated hash in the current manifest.

For each explicit adapter source, validate its manifest first, show whether it
is declarative-only or contains trusted Python, and copy the selected package
to `neutral:workflow/adapters/<id>/` through normal write operations. Global
and later project detection combines built-ins with those managed packages.
The CLI accepts repeatable `--adapter-dir PATH`; it never scans arbitrary
plugin or download directories and setup performs no network access.
`--trust-adapter-code ID` is accepted only for an ID present in an explicit
adapter source and is echoed in the preview; without it, a code-bearing
adapter stays unselected and unexecuted.

The setup skill must instruct any host agent to:

1. run `scan --agents --json`;
2. show detected targets, explicitly supplied adapter packages, and ask the
   user to select;
3. run `plan setup` and present the plan;
4. obtain confirmation before `apply`;
5. run `doctor`;
6. report new-session smoke steps.

Extend `doctor` to load the workflow manifest's selected targets, resolve them
through the registry, and append each adapter's native entrypoint, reference,
skill-discovery, and generated-hash diagnostics. An unavailable selected
adapter is a warning; a missing or drifted generated entrypoint is a conflict.

Add the initial universal bootstrap entrypoint in the same task.
`scripts/bootstrap.py` locates the checkout from `__file__`, imports the local
`src/agent_workflow` package without installing it, first rejects Python older
than 3.11 with an actionable message, and defaults to agent detection plus
setup preview. `--apply` enters the normal confirmed
transaction flow. `SETUP.md` gives both the human command
`python scripts/bootstrap.py` and agent-facing instructions to run detection,
show target/scope/profile choices, preview, confirm, apply, and doctor. Neither
file assumes Claude slash commands or Codex-only syntax.

- [ ] **Step 4: Run package, setup, and full tests**

Run: `python -m pytest tests/test_package.py tests/test_setup.py -v`

Expected: both focused suites pass, including byte-reproducible zipapps.

Run: `python -m pytest -v`

Expected: full suite passes.

- [ ] **Step 5: Commit persistent setup**

```bash
git add SETUP.md scripts/bootstrap.py src/agent_workflow/package.py src/agent_workflow/setup.py src/agent_workflow/cli.py src/agent_workflow/doctor.py skills/agent-workflow-setup tests/test_package.py tests/test_setup.py tests/test_doctor.py
git commit -m "feat: install persistent multi-agent workflow"
```

### Task 7: Golden Trees and Live Smoke Documentation

**Files:**
- Create: `tests/golden/claude/global/`
- Create: `tests/golden/claude/project-local/`
- Create: `tests/golden/claude/project-shared/`
- Create: `tests/golden/claude/project-split/`
- Create: `tests/golden/codex/global/`
- Create: `tests/golden/codex/project-local/`
- Create: `tests/golden/codex/project-shared/`
- Create: `tests/golden/codex/project-split/`
- Create: `tests/helpers.py`
- Create: `tests/integration/test_setup_golden.py`
- Create: `docs/live-smoke.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: setup CLI and all guaranteed-adapter renderers.
- Produces: exact release-blocking golden output and manual smoke contract.

- [ ] **Step 1: Write the golden-tree comparison test**

```python
# tests/integration/test_setup_golden.py
from pathlib import Path
import pytest

from tests.helpers import apply_setup_fixture, assert_tree_matches


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("profile", ["local", "shared", "split"])
def test_project_setup_matches_golden(
    tmp_path: Path, agent: str, profile: str
) -> None:
    actual = apply_setup_fixture(tmp_path, agent=agent, profile=profile)
    expected = Path("tests/golden") / agent / f"project-{profile}"
    assert_tree_matches(actual, expected)
```

Create `tests/helpers.py` with deterministic placeholder substitution for only
`{{HOME}}` and `{{PROJECT}}`; every other byte must match.

- [ ] **Step 2: Run the test and capture the missing-golden failure**

Run: `python -m pytest tests/integration/test_setup_golden.py -v`

Expected: FAIL listing every absent expected tree.

- [ ] **Step 3: Add reviewed golden files and smoke checklist**

Generate each tree into a temporary directory, inspect it manually, replace
the temporary roots with `{{HOME}}` and `{{PROJECT}}`, and add the result under
`tests/golden`. Do not add an automatic “accept all goldens” command.

`docs/live-smoke.md` must contain separate Claude Code and Codex checks:

- create a temporary home and project;
- perform setup from `SETUP.md`;
- open a fresh agent session;
- inspect loaded rules and available skills using that agent's native UI;
- invoke `agent-workflow-setup` in dry-run;
- delete the bootstrap checkout;
- run the installed zipapp's `doctor`;
- record agent version, OS, profile, and outcome.

- [ ] **Step 4: Run all release checks for Plan 2**

Run: `python -m pytest tests/adapters tests/test_skills.py tests/test_profiles.py tests/test_package.py tests/test_setup.py tests/integration/test_setup_golden.py -v`

Expected: all Plan 2 tests pass.

Run: `python -m pytest -v`

Expected: complete suite passes.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit golden setup support**

```bash
git add tests/golden tests/integration/test_setup_golden.py tests/helpers.py docs/live-smoke.md README.md
git commit -m "test: lock Claude and Codex setup output"
```

## Plan 2 Completion Gate

Run:

```bash
python -m pytest -v
python -m agent_workflow scan --agents --json
python -m agent_workflow plan setup --help
git status --short
```

Expected:

- both guaranteed adapters are detected or reported absent without error;
- all global and project profile goldens pass;
- a built zipapp runs after its source checkout is moved away;
- setup conflicts on pre-existing unmanaged native entrypoints;
- the worktree is clean.

Do not begin Plan 3 until the guaranteed adapter goldens pass on all hosted CI
operating systems.
