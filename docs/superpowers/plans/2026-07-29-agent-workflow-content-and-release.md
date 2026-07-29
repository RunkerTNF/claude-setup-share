# Agent Workflow Content and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port this repository's useful Claude-only workflow into portable Agent Skills and neutral templates, make the bootstrap understandable to humans and agents, remove runtime dependence on the cloned repository, and satisfy the stable-release gates for Claude Code and Codex.

**Architecture:** The public repository becomes a bootstrap distribution with a tiny human/agent entrypoint, packaged Python manager, canonical portable skills, adapter assets, fixtures, and documentation. Existing commands and reviewer prompts are translated into standalone skills that use `.agents` paths and capability-based instructions; Claude- and Codex-specific invocation details live only in overlays and generated native entrypoints.

**Tech Stack:** Plans 1–3 manager and adapter APIs; portable Agent Skills in Markdown; Python 3.11 standard-library bootstrap; `pytest` content/golden tests; GitHub Actions Windows/macOS/Linux matrix; manual fresh-session Claude Code and Codex release smoke.

## Global Constraints

- Plans 1–3 completion gates are prerequisites.
- The cloned repository is disposable after setup or migration succeeds.
- Installed runtime content must live under selected global/project `.agents` roots and generated agent-native entrypoints.
- Common rules, memory, sessions, and skill bodies cannot use `.claude` or `.codex` as canonical storage.
- Agent-specific invocation or harness behavior belongs in `.agents/overlays/<agent>/` or adapter templates.
- Existing useful behavior is preserved unless the approved design intentionally replaces it.
- Machine-specific paths, corporate infrastructure, personal identities, tokens, and credentials cannot ship as defaults.
- Examples may explain customization but cannot silently install the author's personal workflow.
- Every shipped skill passes portable skill lint and has an executable content test.
- Guaranteed support requires both Claude Code and Codex setup/migration goldens plus manual live smoke instructions.

---

## File Map

- `SETUP.md`: short bootstrap prompt and direct CLI fallback.
- `README.md`: product model, supported agents, profiles, setup, migration, safety, and customization.
- `docs/architecture.md`: canonical core, generated adapters, ownership, transactions, and lifecycle.
- `docs/adapter-authoring.md`: adapter-author contract and non-guaranteed-agent path.
- `docs/project-profiles.md`: local/shared/split ownership and ignore behavior.
- `docs/safety.md`: trust boundary, redaction, transactions, and rollback.
- `docs/troubleshooting.md`: detection, drift, permissions, recovery, and diagnostics.
- `docs/customization.md`: rules, memory, skills, overlays, profiles, and native settings.
- `docs/release.md`: CI and live-smoke release procedure.
- `templates/core/`: neutral rule, memory, session, and project templates.
- `templates/examples/`: sanitized optional two-machine workflow example.
- `skills/`: portable setup, migration, session, backlog, workitem, and review skills.
- `src/agent_workflow/adapters/*/templates/`: generated Claude Code and Codex entrypoints.
- `tests/content/`: repository-content invariants and legacy-token checks.
- `tests/skills/`: portable workflow behavior tests.
- `tests/integration/`: bootstrap-from-clone and installed-without-clone tests.

## Test Helper Contract

Plan 2 creates `tests/helpers.py`. Extend it in the task that first needs each
of these deterministic helpers: `materialize_bootstrap_repo`, `run_bootstrap`,
`run_installed_manager`, `load_skill`, `skill_text`, `overlay_text`,
`assert_no_personal_paths`, `check_markdown_links`,
`build_release_zipapp`, and `isolated_host`. Task 1 also creates
`tests/conftest.py` with a `repo_root: Path` fixture. Helpers may read the
checkout and write only below pytest temporary roots; installed-runtime tests
must clear source-checkout entries from `PYTHONPATH`.

### Task 1: Harden the Bootstrap and Management Skills

**Files:**
- Modify: `SETUP.md`
- Modify: `skills/agent-workflow-setup/SKILL.md`
- Modify: `skills/agent-workflow-migrate/SKILL.md`
- Create: `skills/agent-workflow-setup/references/setup-flow.md`
- Create: `skills/agent-workflow-migrate/references/recovery.md`
- Modify: `scripts/bootstrap.py`
- Create: `tests/integration/test_bootstrap.py`
- Create: `tests/skills/test_management_skills.py`
- Modify: `tests/helpers.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Human entrypoint: `python scripts/bootstrap.py`
- Agent entrypoint: read `SETUP.md`, then invoke the repository-local setup skill
- Persistent commands: installed `agent-workflow.pyz` and the two management skills

- [ ] **Step 1: Add failing disposable-repository tests**

```python
# tests/integration/test_bootstrap.py
from pathlib import Path
import shutil


def test_installed_manager_survives_source_repo_removal(tmp_path: Path) -> None:
    clone = materialize_bootstrap_repo(tmp_path / "clone")
    home = tmp_path / "home"
    run_bootstrap(clone, home=home, targets=("claude", "codex"))

    shutil.rmtree(clone)

    result = run_installed_manager(home, "doctor", "--scope", "global")
    assert result.returncode == 0
    assert (home / ".agents" / "workflow" / "agent-workflow.pyz").is_file()
    assert (home / ".agents" / "skills" / "agent-workflow-setup" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "agent-workflow-migrate" / "SKILL.md").is_file()


def test_bootstrap_defaults_to_preview(tmp_path: Path) -> None:
    clone = materialize_bootstrap_repo(tmp_path / "clone")
    home = tmp_path / "home"

    result = run_bootstrap(clone, home=home)

    assert result.returncode == 0
    assert "No changes applied" in result.stdout
    assert not (home / ".agents").exists()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/integration/test_bootstrap.py -q`

Expected: FAIL until the bootstrap and both management skills satisfy the final
self-contained contract and install the migration skill.

- [ ] **Step 3: Write the one-page bootstrap contract**

`SETUP.md` must tell a human or agent:

1. prerequisites: Python 3.11+, a clone/download of the repository, and at
   least one supported or discoverable agent;
2. safe first action: `python scripts/bootstrap.py` for detection and preview;
3. how the user selects global/project scope, local/shared/split profile, and
   target agents;
4. that existing setups become migration candidates rather than overwrite
   targets;
5. that credentials are never copied;
6. exactly when confirmation is required;
7. how to verify with doctor;
8. that the clone can be deleted after success;
9. where the installed manager, manifest, backups, and portable skills live.

The agent-facing prompt must not assume slash-command syntax or a named
subagent API.

- [ ] **Step 4: Implement a stdlib-only bootstrap**

`scripts/bootstrap.py` locates the repository root from `__file__`, imports the
local `src/agent_workflow` package without installing it, and dispatches to:

```text
agent-workflow setup detect
agent-workflow setup preview
agent-workflow setup apply
```

Default invocation performs detection and preview only. `--apply` enables the
normal Plan 1 confirmation flow. Forward only documented setup flags and reject
unknown arguments. Do not download Python packages or modify the source clone.

- [ ] **Step 5: Make management skills self-contained**

Both skills must resolve the installed manager in this order:

1. `agent-workflow` on `PATH`;
2. `~/.agents/workflow/agent-workflow.pyz`.

They may point to their own installed `references/`, but not to the bootstrap
clone. They must use capability language such as “run the command” and “read
the preview,” with optional overlay notes for exact Claude/Codex invocation.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/integration/test_bootstrap.py tests/skills/test_management_skills.py -q`

Expected: PASS.

```bash
git add SETUP.md scripts/bootstrap.py skills/agent-workflow-setup skills/agent-workflow-migrate tests/helpers.py tests/conftest.py tests/integration/test_bootstrap.py tests/skills/test_management_skills.py
git commit -m "feat: make bootstrap installation self-contained"
```

### Task 2: Port Session, Backlog, and Project Setup Workflows

**Files:**
- Create: `skills/wrap/SKILL.md`
- Create: `skills/backlog/SKILL.md`
- Create: `skills/pick/SKILL.md`
- Modify: `skills/agent-workflow-setup/SKILL.md`
- Create: `skills/agent-workflow-setup/references/project-inference.md`
- Modify: `templates/core/project-rules.md`
- Modify: `templates/core/project-memory-index.md`
- Create: `tests/skills/test_session_skills.py`
- Create: `tests/skills/test_setup_project_inference.py`

**Interfaces:**
- Canonical session root: `<scope>/.agents/sessions/`
- Canonical project memory root: `<repo>/.agents/memory/`
- Canonical project rules: `<repo>/.agents/RULES.md`
- Produces portable skills: `wrap`, `backlog`, and `pick`
- Extends: `agent-workflow-setup` with the legacy project-inference behavior

- [ ] **Step 1: Add failing canonical-path content tests**

```python
# tests/skills/test_session_skills.py
from pathlib import Path


def test_session_skills_use_only_neutral_canonical_paths(repo_root: Path) -> None:
    for name in ("wrap", "backlog", "pick"):
        text = (repo_root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert ".agents/sessions" in text
        assert ".agents/memory" in text
        assert ".claude/" not in text
        assert ".codex/" not in text


def test_wrap_and_backlog_contracts_remain_compatible(repo_root: Path) -> None:
    wrap = load_skill(repo_root, "wrap")
    backlog = load_skill(repo_root, "backlog")

    assert wrap.emitted_tags == backlog.accepted_tags
    assert "_backlog.md" in backlog.body
```

- [ ] **Step 2: Run and confirm missing skills**

Run: `pytest tests/skills/test_session_skills.py tests/skills/test_setup_project_inference.py -q`

Expected: FAIL because the portable skills do not exist.

- [ ] **Step 3: Port `wrap` without changing its information model**

Start from `home-claude/commands/wrap.md`. Preserve:

- `YYYY-MM-DD-<slug>.md` naming;
- Summary, What changed, Decisions, Challenges/dead ends, Observed behavior,
  and Open threads;
- stable backlog tags and IDs;
- the rule against parking one-shot administrative chores as open work.

Change canonical paths to `.agents/sessions/`. Put agent-specific ways to
discover session context in adapter overlays, not the common skill.

- [ ] **Step 4: Port `backlog` and `pick` as a matched pair**

Start from `home-claude/commands/backlog.md` and `pick.md`. Preserve the
Active/Resolved/Processed sources file model, H/M/L priority, stable IDs,
source links, incremental mtime/hash processing, ambiguity handling, and
planning handoff.

Use only:

- `.agents/sessions/*.md`;
- `.agents/memory/**/*.md`;
- `.agents/sessions/_backlog.md`.

Remove Claude's encoded-CWD auto-memory lookup. `pick` must ask the current
agent to begin its available planning workflow; exact plan-mode or skill
invocation is an overlay concern.

- [ ] **Step 5: Fold `init-claude` behavior into `agent-workflow-setup`**

Start from `home-claude/commands/init-claude.md`, but keep
`agent-workflow-setup` as the single setup skill and delegate all filesystem
planning and writes to:

```text
agent-workflow setup preview --scope project --project <repo> --profile <profile>
agent-workflow setup apply --plan <plan>
```

Keep read-only project inference as an optional second phase that proposes
content for `project.md`. Never create agent-native files directly. Re-running
must be idempotent, and local/shared/split remains an explicit user choice.

- [ ] **Step 6: Validate portable skills and commit**

Run: `pytest tests/skills/test_session_skills.py tests/skills/test_setup_project_inference.py tests/test_portability.py -q`

Expected: PASS.

```bash
git add skills/wrap skills/backlog skills/pick skills/agent-workflow-setup templates/core/project-rules.md templates/core/project-memory-index.md tests/skills/test_session_skills.py tests/skills/test_setup_project_inference.py
git commit -m "feat: port project workflow skills"
```

### Task 3: Port Workitem Digest Skills and Shared Rendering Rules

**Files:**
- Create: `skills/morning/SKILL.md`
- Create: `skills/tasks/SKILL.md`
- Create: `skills/my-reviews/SKILL.md`
- Create: `skills/feedback/SKILL.md`
- Create: `skills/morning/references/workitems-rendering.md`
- Create: `skills/tasks/references/workitems-rendering.md`
- Create: `skills/my-reviews/references/workitems-rendering.md`
- Create: `skills/feedback/references/workitems-rendering.md`
- Create: `resources/workitems-rendering.md`
- Create: `scripts/sync_skill_reference.py`
- Create: `tests/skills/test_workitem_skills.py`
- Create: `tests/content/test_synced_references.py`

**Interfaces:**
- Produces portable skills: `morning`, `tasks`, `my-reviews`, `feedback`
- Canonical source in this repository: `resources/workitems-rendering.md`
- Installed self-contained copy: each skill's `references/workitems-rendering.md`

- [ ] **Step 1: Add failing self-contained-reference tests**

```python
# tests/skills/test_workitem_skills.py
from pathlib import Path


def test_each_workitem_skill_has_a_local_reference(repo_root: Path) -> None:
    for name in ("morning", "tasks", "my-reviews", "feedback"):
        skill_dir = repo_root / "skills" / name
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        reference = skill_dir / "references" / "workitems-rendering.md"

        assert reference.is_file()
        assert "references/workitems-rendering.md" in body
        assert "~/.claude" not in body
        assert reference.read_bytes() == (
            repo_root / "resources" / "workitems-rendering.md"
        ).read_bytes()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/skills/test_workitem_skills.py tests/content/test_synced_references.py -q`

Expected: FAIL because portable workitem skills are absent.

- [ ] **Step 3: Port shared rendering content**

Move the semantic content from `home-claude/workitems-rendering.md` to
`resources/workitems-rendering.md`. Preserve digest levels, status mapping,
edge states, Jira normalization, MR diff drill-in, review observations, and
reply drafting. Replace Claude tool names with capability-based instructions:
read local synced files, search content, and render Markdown.

- [ ] **Step 4: Port the four skills**

Start from the matching files in `home-claude/commands/`. Preserve argument
resolution (`cwd` or `all`), local workitem data contracts, successful-resolve
flow, and follow-up drill-ins. Each skill reads its bundled reference using a
path relative to its own `SKILL.md`; it cannot assume a shared home path.

The common skill may state required capabilities but must not name a connector,
MCP server, slash command, or Claude-specific `Read` syntax as mandatory.

- [ ] **Step 5: Add deterministic reference synchronization**

`scripts/sync_skill_reference.py --check` compares all four bundled copies to
`resources/workitems-rendering.md` and exits non-zero on drift.
`scripts/sync_skill_reference.py --write` copies bytes to the four fixed
destinations. It accepts no arbitrary destination path.

- [ ] **Step 6: Run and commit**

Run: `python scripts/sync_skill_reference.py --write`

Run: `pytest tests/skills/test_workitem_skills.py tests/content/test_synced_references.py tests/test_portability.py -q`

Expected: PASS.

```bash
git add skills/morning skills/tasks skills/my-reviews skills/feedback resources/workitems-rendering.md scripts/sync_skill_reference.py tests/skills/test_workitem_skills.py tests/content/test_synced_references.py
git commit -m "feat: port workitem digest skills"
```

### Task 4: Port Plan and Code Reviewers to Portable Skills

**Files:**
- Create: `skills/plan-review/SKILL.md`
- Create: `skills/code-review/SKILL.md`
- Create: `skills/plan-review/references/review-contract.md`
- Create: `skills/code-review/references/review-contract.md`
- Modify: `templates/core/global-rules.md`
- Create: `templates/overlays/claude/review-workflow.md`
- Create: `templates/overlays/codex/review-workflow.md`
- Create: `tests/skills/test_review_skills.py`
- Modify: `tests/golden/claude/`
- Modify: `tests/golden/codex/`

**Interfaces:**
- Produces portable skills: `plan-review`, `code-review`
- Common contract: current agent performs review unless delegation was explicitly requested and supported
- Adapter overlays: exact Claude Code and Codex invocation guidance

- [ ] **Step 1: Add failing reviewer portability tests**

```python
# tests/skills/test_review_skills.py
def test_common_reviewer_skills_do_not_require_named_subagents(repo_root) -> None:
    for name in ("plan-review", "code-review"):
        text = skill_text(repo_root, name)
        assert 'Agent(subagent_type=' not in text
        assert "CLAUDE.md" not in text
        assert ".claude/memory" not in text
        assert ".agents/memory" in text


def test_agent_specific_delegation_lives_in_overlays(repo_root) -> None:
    common = skill_text(repo_root, "plan-review") + skill_text(repo_root, "code-review")
    claude = overlay_text(repo_root, "claude", "review-workflow.md")
    codex = overlay_text(repo_root, "codex", "review-workflow.md")

    assert "subagent_type" not in common
    assert "subagent_type" in claude
    assert "generic worker" in codex.lower()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/skills/test_review_skills.py -q`

Expected: FAIL because the portable review skills do not exist.

- [ ] **Step 3: Port the shared review semantics**

Start from `home-claude/agents/plan-reviewer.md` and `code-reviewer.md`.
Preserve:

- required reading of request/plan or diff;
- project rules and relevant memory lookup;
- plan adherence, convention, safety, tests, and scope checks;
- triviality rule;
- Blocking, Suggestions, Verdict output structure;
- read-only default.

Replace `CLAUDE.md` and `.claude/memory/` with the neutral rule entrypoint and
`.agents/memory/`. The skill must work in the current agent with no delegation.

- [ ] **Step 4: Add thin agent overlays**

Claude overlay: named reviewer subagents are optional generated conveniences;
use them only when the user asks for delegation or project rules require it.

Codex overlay: use a generic worker role only when the user explicitly asks for
subagent review; otherwise invoke the skill in the current agent. Both overlays
must point back to the portable skill as the semantic source of truth.

- [ ] **Step 5: Update setup goldens and commit**

Run: `pytest tests/skills/test_review_skills.py tests/integration/test_setup_golden.py -q`

Expected: PASS and generated Claude/Codex entrypoints reference the neutral
review rules.

```bash
git add skills/plan-review skills/code-review templates/core/global-rules.md templates/overlays tests/skills/test_review_skills.py tests/golden/claude tests/golden/codex
git commit -m "feat: port review workflow to portable skills"
```

### Task 5: Split Personal Examples from Shipped Defaults and Remove `home-claude`

**Files:**
- Modify: `templates/core/global-rules.md`
- Modify: `templates/core/project-rules.md`
- Modify: `templates/core/global-memory-index.md`
- Modify: `templates/core/project-memory-index.md`
- Create: `templates/examples/two-machine-workflow.md`
- Create: `templates/examples/syncprotect`
- Create: `src/agent_workflow/adapters/claude/templates/settings.example.json`
- Create: `src/agent_workflow/adapters/claude/assets/statusline.js`
- Modify: `src/agent_workflow/package.py`
- Modify: `src/agent_workflow/setup.py`
- Modify: `tests/test_package.py`
- Modify: `tests/test_setup.py`
- Modify: `tests/fixtures/legacy/current-repository/`
- Create: `tests/content/test_no_legacy_runtime.py`
- Delete: `home-claude/CLAUDE.md.example`
- Delete: `home-claude/settings.json.example`
- Delete: `home-claude/statusline.js`
- Delete: `home-claude/workitems-rendering.md`
- Delete: `home-claude/agents/code-reviewer.md`
- Delete: `home-claude/agents/plan-reviewer.md`
- Delete: `home-claude/commands/backlog.md`
- Delete: `home-claude/commands/feedback.md`
- Delete: `home-claude/commands/init-claude.md`
- Delete: `home-claude/commands/morning.md`
- Delete: `home-claude/commands/my-reviews.md`
- Delete: `home-claude/commands/pick.md`
- Delete: `home-claude/commands/tasks.md`
- Delete: `home-claude/commands/wrap.md`

**Interfaces:**
- Shipped neutral defaults contain no personal machine topology.
- Optional example preserves the useful two-machine pattern without installing it.
- Claude-native status line remains an optional adapter asset, not canonical workflow state.

- [ ] **Step 1: Add failing legacy-runtime tests**

```python
# tests/content/test_no_legacy_runtime.py
from pathlib import Path


def test_home_claude_is_not_a_runtime_source(repo_root: Path) -> None:
    assert not (repo_root / "home-claude").exists()


def test_neutral_templates_have_no_agent_canonical_paths(repo_root: Path) -> None:
    forbidden = (".claude/memory", ".claude/sessions", ".codex/memory")
    for path in (repo_root / "templates" / "core").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), path


def test_personal_absolute_paths_do_not_ship(repo_root: Path) -> None:
    shipped_roots = ("skills", "templates/core", "src/agent_workflow")
    for root in shipped_roots:
        assert_no_personal_paths(repo_root / root)
```

- [ ] **Step 2: Run and confirm current Claude-only tree fails**

Run: `pytest tests/content/test_no_legacy_runtime.py -q`

Expected: FAIL while `home-claude/` exists.

- [ ] **Step 3: Extract neutral and optional example content**

From `home-claude/CLAUDE.md.example`, move universal memory hygiene, scope
discipline, safe git behavior, and review policy into neutral rule templates.
Move the personal Windows two-machine/code-transfer workflow into
`templates/examples/two-machine-workflow.md`, parameterized with placeholders
such as `<sync-root>` and `<corporate-machine>`. Do not install examples by
default.

- [ ] **Step 4: Preserve Claude-native optional assets**

Move the sanitized shape of `settings.json.example` into the Claude adapter.
Keep `statusline.js` as an optional asset selected by an explicit setup flag.
Remove personal absolute paths, replace credential-bearing fields with
documented placeholders, and ensure neither file is loaded by Codex or neutral
core setup.

- [ ] **Step 5: Freeze the old tree as a migration fixture, then delete it**

Before deleting `home-claude/`, verify Plan 3's
`tests/fixtures/legacy/current-repository/` contains a sanitized copy and that
its `SOURCE.md` records every source file. Run the current-repository migration
golden and compare the ported skill inventory to the expected set:

`agent-workflow-setup`, `agent-workflow-migrate`, `wrap`, `backlog`, `pick`,
`morning`, `tasks`, `my-reviews`, `feedback`, `plan-review`, and
`code-review`.

Extend the zipapp's fixed bundled-skill resource list and global setup planner
with that exact set. Management skills are mandatory; the other shipped skills
are installed by default and may be omitted only through an explicit
`--exclude-skill NAME` recorded in the preview and manifest. Project setup
does not duplicate globally installed skills unless a project-scoped skill was
selected or migrated.

Then remove the listed source files and the empty `home-claude/` directories.

- [ ] **Step 6: Run content, migration, and golden tests**

Run: `pytest tests/test_package.py tests/test_setup.py tests/content/test_no_legacy_runtime.py tests/integration/test_migration_golden.py tests/integration/test_setup_golden.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates src/agent_workflow/package.py src/agent_workflow/setup.py src/agent_workflow/adapters/claude tests/test_package.py tests/test_setup.py tests/fixtures/legacy/current-repository tests/content/test_no_legacy_runtime.py
git rm -r home-claude
git commit -m "refactor: replace Claude-only runtime content"
```

### Task 6: Rewrite Public Documentation and Adapter Authoring Guide

**Files:**
- Modify: `README.md`
- Replace: `INSTALL.md`
- Create: `docs/architecture.md`
- Create: `docs/adapter-authoring.md`
- Create: `docs/customization.md`
- Create: `docs/project-profiles.md`
- Create: `docs/safety.md`
- Create: `docs/troubleshooting.md`
- Modify: `docs/migration.md`
- Create: `tests/content/test_docs.py`

**Interfaces:**
- `README.md`: product overview and shortest path
- `SETUP.md`: executable bootstrap instructions
- `INSTALL.md`: detailed installation and project-profile walkthrough
- `docs/adapter-authoring.md`: third-party adapter contract and support-level rules

- [ ] **Step 1: Add failing documentation-link tests**

```python
# tests/content/test_docs.py
def test_documentation_has_no_broken_local_links(repo_root) -> None:
    errors = check_markdown_links(repo_root, roots=("README.md", "INSTALL.md", "SETUP.md", "docs"))
    assert errors == []


def test_readme_names_guaranteed_and_extensible_support(repo_root) -> None:
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    assert "Claude Code" in text
    assert "Codex" in text
    assert "adapter" in text.lower()
    assert "Pi" in text
    assert "Cursor" in text
    assert "guaranteed" in text.lower() or "гарантирован" in text.lower()


def test_docs_explain_clone_is_disposable(repo_root) -> None:
    for name in ("README.md", "INSTALL.md", "SETUP.md"):
        text = (repo_root / name).read_text(encoding="utf-8")
        assert "delete" in text.lower() or "удал" in text.lower()
```

- [ ] **Step 2: Run and confirm old docs fail**

Run: `pytest tests/content/test_docs.py -q`

Expected: FAIL because current docs describe a Claude-only copied-home layout.

- [ ] **Step 3: Rewrite `README.md` around the approved model**

Use this order:

1. what the repository solves;
2. universal `.agents` core and generated native adapters;
3. guaranteed Claude Code and Codex support;
4. standards-based path for Pi, Cursor, Gemini CLI, OpenCode, Cline, and future
   agents without claiming guaranteed parity;
5. fresh setup versus legacy migration;
6. global and per-project scopes;
7. local/shared/split profiles;
8. rules, manual memory, sessions, skills, overlays, and native settings;
9. transaction safety, credentials, preview, rollback, doctor;
10. short quick start pointing to `SETUP.md`;
11. extension and support policy.

Mark optional personal examples as examples, not defaults.

- [ ] **Step 4: Rewrite installation and supporting docs**

`INSTALL.md` gives exact human-led and agent-led flows for:

- fresh global setup;
- configuring a project with each profile;
- migrating Claude-only, Codex-only, or mixed state;
- adding another agent later;
- updating/reconfiguring an installed setup;
- uninstall/restore via manifest and transaction journal.

`docs/architecture.md` is the durable ownership and data-flow reference.
`docs/adapter-authoring.md` lists manifest fields, detection, capability
states, entrypoint generation, inventory roots, sensitivity keys, mappings,
golden fixtures, and the bar for “guaranteed.” `docs/customization.md` explains
how to edit canonical sources and regenerate native files.
`docs/project-profiles.md` gives the exact tracked/ignored/generated ownership
table for local, shared, and split. `docs/safety.md` documents the trust
boundary, redaction, transactions, no-clobber, backups, and rollback.
`docs/troubleshooting.md` covers missing-agent detection, stale hashes,
unsupported mappings, failed doctor checks, and recovery.

- [ ] **Step 5: Run docs tests and commit**

Run: `pytest tests/content/test_docs.py -q`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

```bash
git add README.md INSTALL.md SETUP.md docs tests/content/test_docs.py
git commit -m "docs: document agent-agnostic setup workflow"
```

### Task 7: Close Automated and Manual Release Gates

**Files:**
- Create: `docs/release.md`
- Create: `scripts/release_check.py`
- Create: `tests/integration/test_installed_release.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `src/agent_workflow/adapters/claude/adapter.json`
- Modify: `src/agent_workflow/adapters/codex/adapter.json`

**Interfaces:**
- Local/CI gate: `python scripts/release_check.py`
- Manual gate: fresh Claude Code and Codex sessions using the packaged artifact
- Release artifact: reproducible `agent-workflow.pyz` plus source archive

- [ ] **Step 1: Add a failing installed-artifact release test**

```python
# tests/integration/test_installed_release.py
@pytest.mark.parametrize("target", ["claude", "codex"])
@pytest.mark.parametrize("profile", ["local", "shared", "split"])
def test_release_artifact_sets_up_and_migrates_without_source_tree(
    target: str,
    profile: str,
    tmp_path: Path,
) -> None:
    artifact = build_release_zipapp(tmp_path)
    isolated = isolated_host(tmp_path, artifact)

    setup = isolated.run_setup(target=target, profile=profile)
    migration = isolated.run_fixture_migration(target=target)

    assert setup.returncode == 0
    assert migration.returncode == 0
    assert isolated.doctor() == ()
    assert not isolated.python_path_contains_source_checkout()
```

- [ ] **Step 2: Run and confirm missing release checker**

Run: `pytest tests/integration/test_installed_release.py -q`

Expected: FAIL until the packaged release path is wired.

- [ ] **Step 3: Implement the release checker**

`scripts/release_check.py` runs, in order:

1. portable skill lint;
2. documentation link and forbidden-token checks;
3. unit tests;
4. setup and migration goldens;
5. transaction fault-injection tests;
6. installed-artifact tests;
7. reproducible zipapp build twice and SHA-256 comparison;
8. `git diff --check`.

It stops at the first failure, prints the exact command, and returns its exit
code. It uses the current Python interpreter and no shell-specific syntax.

- [ ] **Step 4: Finalize hosted CI**

GitHub Actions must run the release checker on:

- `windows-latest`;
- `macos-latest`;
- `ubuntu-latest`;
- Python 3.11 and the newest supported stable Python.

Upload the zipapp and SHA-256 file from one deterministic packaging job.
Automated CI does not claim a live agent launch.

- [ ] **Step 5: Write and execute the manual live smoke checklist**

For each guaranteed agent, on a clean temporary home and project:

1. start a fresh agent session pointed at `SETUP.md`;
2. confirm it detects installed agents and asks for target/scope/profile;
3. preview fresh global setup, then apply;
4. delete or move the bootstrap clone;
5. start a new session and invoke the installed setup skill;
6. configure one project in `split` profile;
7. migrate a sanitized legacy setup through preview and apply;
8. verify common rules are referenced, portable skills are discoverable, and
   manual memory is read from `.agents`;
9. run doctor;
10. introduce generated-file drift and verify overwrite is refused;
11. roll back the last transaction and hash-compare restored files.

Record date, agent version, OS, result, and issue link in `docs/release.md`.
After each pass, add the exact reported CLI version to that adapter manifest's
sorted `supported_versions` list and rerun the automated release checker. A
stable tag is blocked until both Claude Code and Codex rows pass and both exact
versions are present.

- [ ] **Step 6: Run the full release gate**

Run: `python scripts/release_check.py`

Expected: PASS with a printed zipapp SHA-256 and no modified golden files.

Run: `git status --short`

Expected: only the Task 7 files listed above are modified or untracked.

- [ ] **Step 7: Commit**

```bash
git add docs/release.md scripts/release_check.py tests/integration/test_installed_release.py .github/workflows/ci.yml pyproject.toml src/agent_workflow/adapters/claude/adapter.json src/agent_workflow/adapters/codex/adapter.json
git commit -m "chore: add cross-agent release gate"
```

- [ ] **Step 8: Verify the committed release state**

Run: `git status --short`

Expected: empty.

## Plan 4 Completion Gate

- Every useful legacy command and reviewer prompt is represented by a portable Agent Skill.
- Common skill bodies and templates use `.agents` as canonical storage.
- Claude Code and Codex differences exist only in adapter assets and overlays.
- The setup and migration skills work after the bootstrap clone is removed.
- Personal two-machine details are optional sanitized examples, not installed defaults.
- `home-claude/` is removed only after its sanitized migration fixture and portable replacements pass.
- README, setup, install, architecture, migration, customization, adapter, and release docs agree.
- Hosted Windows/macOS/Linux CI passes the full release checker.
- Manual fresh-session Claude Code and Codex smoke rows are both recorded as passing before a stable release.
