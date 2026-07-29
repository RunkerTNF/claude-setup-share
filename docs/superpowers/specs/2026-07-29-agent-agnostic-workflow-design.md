# Agent-Agnostic Workflow Design

**Date:** 2026-07-29
**Status:** Approved design, pending implementation plan
**Working product name:** `agent-workflow`

## Summary

This repository will become a bootstrap distribution for installing and
migrating a reusable agent workflow. It will no longer describe a Claude-only
home directory.

The installed workflow has an agent-agnostic source of truth under
`~/.agents/` globally and `.agents/` inside configured projects. Claude Code
and Codex are the guaranteed adapters in the first stable release. Other
agentic coding tools can be added through a documented adapter contract.

The downloaded repository is not a long-lived configuration repository. A
user points an agent at its `SETUP.md`, completes setup or migration, and can
then delete the downloaded repository. The installed manager, management
skills, rules, memory, sessions, and user skills continue to work
independently.

## Confirmed Constraints

- The canonical workflow is agent-agnostic.
- Claude Code and Codex receive guaranteed first-class adapters.
- Other agents use the same adapter contract and may initially have partial or
  experimental support.
- Canonical sources are one-way: generated native artifacts are not an
  independent source of truth.
- Common rules live in a separate Markdown file and are referenced by native
  agent entrypoints rather than copied into them.
- Manual memory lives outside `.claude/` and `.codex/`.
- Agent Skills are the canonical format for repeatable workflows.
- Legacy commands migrate to skills; native commands are optional aliases.
- Setup and migration work on Windows, macOS, and Linux.
- Python 3.11 or newer is the only required runtime; the manager has no
  third-party Python dependencies.
- A user chooses the storage profile separately for each configured project.
- Migration is dry-run-first, backed up, conflict-aware, and non-destructive.
- Native automatic memories remain optional generated caches. Neutral manual
  memory is authoritative.
- One setup run can detect and configure multiple installed agents.
- The installed workflow contains a persistent manager plus separate setup and
  migration skills.
- Semantic migration is hybrid: Python owns safety and transactions, while the
  current LLM proposes classifications within a validated schema.

## Architecture

### Bootstrap distribution

The source repository contains:

- a short, universal `SETUP.md`;
- a Python manager;
- neutral templates;
- adapter manifests, mappings, and templates;
- source versions of the management and workflow skills;
- migration fixtures;
- automated tests;
- architecture, migration, adapter-authoring, and smoke-test documentation.

The repository never receives a user's installed state, generated adapters,
manual memory, sessions, credentials, or private configuration.

### Installed global core

The global source of truth is:

```text
~/.agents/
├── RULES.md
├── manifest.json
├── memory/
│   ├── MEMORY.md
│   ├── feedback/
│   ├── user/
│   └── reference/
├── skills/
│   ├── agent-workflow-setup/
│   ├── agent-workflow-migrate/
│   └── <user-skills>/
├── overlays/
│   ├── claude/
│   ├── codex/
│   └── <other-agent>/
└── workflow/
    ├── manager/
    ├── adapters/
    └── templates/
```

Backups and transaction journals also live under the installed neutral
workflow root, outside the downloaded bootstrap repository.

### Installed project core

Each configured project has:

```text
<repo>/.agents/
├── RULES.md
├── manifest.json
├── memory/
│   ├── MEMORY.md
│   └── <project-notes>.md
├── sessions/
├── skills/
└── overlays/
    └── <agent>/
```

Project memory is flat because every entry is already project-scoped. Its
frontmatter records whether an entry is project knowledge, a repo-scoped
reference, or another supported type.

### Project storage profiles

The user chooses one profile during project setup or reconfiguration:

- `local`: project workflow state and generated entrypoints remain personal
  and are excluded from version control and configured sync tools.
- `shared`: project rules, memory, sessions, skills, and compatible generated
  entrypoints are intended to be shared through the repository.
- `split`: common project rules and shared skills are shareable; personal
  memory, sessions, local overlays, and local-only entrypoints remain ignored.

The transaction preview lists the exact files affected by the selected profile
before changing `.gitignore`, `.syncprotect`, or any native entrypoint.

## Canonical Content Model

### Rules

Always-on common instructions live only in:

- `~/.agents/RULES.md` for global rules;
- `<repo>/.agents/RULES.md` for project rules.

Agent-specific instructions live in:

- `~/.agents/overlays/<agent>/RULES.md`;
- `<repo>/.agents/overlays/<agent>/RULES.md`.

Native files such as `CLAUDE.md`, `AGENTS.md`, or `AGENTS.override.md` are
entrypoints. They reference the applicable common and agent-specific files
using the best mechanism available in that harness. They do not contain a
duplicated snapshot of the common rules.

### Manual memory

Neutral manual memory is the durable source of truth.

- Global memory uses typed subdirectories and an index.
- Project memory is flat and uses typed frontmatter plus an index.
- Native auto-memory may remain enabled as a local generated cache.
- Auto-memory is not synchronized back into neutral memory.
- During migration, selected auto-memory entries may be proposed as import
  candidates with clear provenance.

Rules that must always apply do not live only in memory. They belong in
`RULES.md`.

### Skills

Every repeatable workflow is authored as an Agent Skill:

```text
skills/<name>/
├── SKILL.md
├── references/
├── assets/
├── scripts/
└── overlays/
    └── <agent>.md
```

The portable core uses only:

- `name` and `description` frontmatter;
- normal Markdown instructions;
- relative references to packaged resources;
- cross-platform Python scripts when deterministic behavior is needed;
- explicit inputs, outputs, stop conditions, and failure behavior.

Vendor-specific invocation syntax, frontmatter, shell interpolation, hooks,
tool names, permissions, and subagent controls are prohibited in the portable
core. They belong in adapter overlays or generated native artifacts.

Legacy slash commands are normalized to skills. An adapter may generate a
native command alias when that improves discoverability, but the alias contains
no independent workflow logic.

Subagent prompts that describe a portable workflow are normalized to skills.
Native-only model selection, permissions, background behavior, or delegation
features remain in an agent overlay or are reported as unmanaged when no safe
mapping exists.

## Persistent Manager

After bootstrap, `~/.agents/workflow/` contains an autonomous copy of the
manager, adapter registry, and templates. The downloaded repository is no
longer required.

Two neutral management skills remain installed:

- `agent-workflow-setup`: global setup, agent addition, project initialization,
  project profile changes, adapter rebuilds, and diagnostics.
- `agent-workflow-migrate`: inventory and migration of legacy agent
  configurations.

The manager exposes separate read and write phases:

```text
scan -> plan -> apply -> verify
```

Only `apply` may write. It requires a confirmed transaction plan.

## Setup and Configuration Flow

### Bootstrap entrypoint

The distribution root contains a short `SETUP.md`. Native instruction files in
the distribution only direct the current agent to read it. No agent-specific
file contains the setup algorithm.

### Initial global setup

1. The current agent reads `SETUP.md` and checks for Python 3.11 or newer.
2. It runs a read-only scan.
3. The manager detects the operating system, home directory, installed agents,
   existing native configuration, and any existing neutral core.
4. The agent shows detected targets and lets the user select them. The current
   agent is preselected.
5. The manager produces a transaction plan covering files, backups, imports,
   conflicts, skips, and required permissions.
6. The user confirms the plan.
7. The manager verifies source hashes, writes a validated backup, stages the
   new state, and commits it with journaled per-file atomic replacements.
8. The manager installs its autonomous copy and management skills, then renders
   the selected adapters.
9. `doctor` validates schemas, hashes, references, discovery paths, and the
   absence of dependencies on the downloaded repository.
10. The final report gives short new-session smoke instructions for each
    selected agent.

### Project setup

Project setup runs from or against a selected project root. It asks for:

- the `local`, `shared`, or `split` profile;
- target agents;
- whether existing project instructions and skills should be imported;
- how to integrate with existing ignore, sync-protection, and native
  instruction files.

Repeated setup is idempotent. Current files are skipped, missing artifacts are
created, and modified generated files become conflicts.

## Migration

Migration runs independently for global scope and for each selected project.
Each scope is one journaled transaction with complete-scope rollback.

### Inventory

The manager scans known locations for the selected adapters. For every
artifact, it records:

- source path, scope, and hash;
- probable artifact type;
- whether it appears user-authored, agent-generated, or manager-generated;
- whether it may contain credentials;
- available conversion paths.

The inventory covers rules, manual memory, session notes, skills, commands,
subagent prompts, settings, permissions, hooks, and MCP configuration.

### Classification and normalization

Deterministic import handles standard skills, structurally compatible memory
and sessions, known settings, discovery paths, and unambiguous commands.

For prose instructions, the current agent returns decisions in a validated
schema with these classifications:

- common rule;
- agent-specific overlay;
- skill;
- manual memory;
- session context;
- unsupported native setting;
- sensitive and skipped;
- conflict requiring a user decision.

Python chooses destination paths, validates the classifications, and owns all
filesystem operations. The LLM cannot write migration output directly.

### Preview

Before applying, the user sees:

- source-to-destination mappings;
- diffs of proposed neutral files;
- native files that would become generated entrypoints;
- unsupported and unmanaged artifacts;
- conflicts requiring decisions;
- redacted sensitive fields;
- the exact backup destination.

### Apply and verify

After confirmation, the manager:

1. reacquires and verifies source hashes;
2. creates and verifies a backup;
3. assembles the result in a staging directory;
4. runs schema and portability validation;
5. commits neutral files and generated adapters through journaled per-file
   atomic replacements;
6. writes a transaction journal;
7. runs `doctor`.

A user-authored native instruction file is replaced by a generated entrypoint
only after its content has been imported successfully and the replacement has
been explicitly confirmed. Unsupported settings remain in place.

If verification fails, the manager rolls back the complete scope transaction.
Later rollback by transaction ID is also supported.

## Adapter Contract

Each adapter package has this shape:

```text
adapters/<agent>/
├── adapter.json
├── templates/
├── mappings/
└── adapter.py
```

`adapter.py` is optional. Simple adapters are declarative.

The adapter manifest declares:

- executable and installation detection;
- version detection and supported version range;
- global and project discovery paths;
- instruction entrypoints;
- skill locations and invocation mechanisms;
- commands, subagents, hooks, permissions, and MCP capabilities;
- sensitive fields that must not be copied;
- validation and live-smoke instructions.

Every adapter follows:

```text
detect -> inventory -> plan -> render -> validate -> smoke instructions
```

Capabilities are reported as supported, partial, unsupported, or unknown for
the detected version. A partial capability is never presented as full parity.

Claude Code and Codex adapters are release-blocking and guaranteed. Other
adapters may be marked experimental until they have equivalent fixture,
golden, and runtime evidence.

Agents that discover `.agents/skills` can use canonical skills directly. Other
adapters materialize native copies or wrappers. Generated artifacts record the
generator version and source hash and are not edited manually.

Raw settings from one agent are never copied into another agent's
configuration. Permissions, hooks, settings, and MCP configuration move only
through explicit semantic mappings.

## Safety and Error Handling

### Filesystem safety

- Paths are normalized with `pathlib`.
- Every target must remain within an expected home or project root.
- Unresolved symlink or junction targets block writes.
- Filesystem root, home root, and project root cannot become recursive
  operation targets.
- Discovered hooks, skills, and scripts are data during migration and are never
  executed by the scanner or importer.
- Setup and migration require no network access.

### Secrets and privacy

- Credentials, tokens, private keys, and auth fields never enter neutral
  memory, generated reports, or LLM classification input.
- Reports and transaction journals redact sensitive values.
- Authentication is re-established through each agent's native workflow when
  needed.

### Transactions and drift

- A scope lock prevents concurrent writes.
- Source hashes are checked again immediately before apply.
- A backup is created and read-verified before the first modification.
- Backups are never deleted automatically.
- Backups are treated as sensitive local data, excluded from LLM
  classification, and created with user-only access where the platform
  supports it.
- Staging plus atomic replacement prevents partially written output.
- Transaction journals record applied, skipped, unmanaged, warning, and
  rollback information.

Generated files are overwritten only when their current hash matches the last
generated hash. Drift produces a conflict with three explicit resolutions:

- import the change into canonical source;
- restore the generated version;
- leave the file unmanaged.

### Error classes

- Blocking: unsafe path, changed source hash, invalid schema, backup failure.
- Conflict: ambiguous classification or manual drift.
- Warning: unknown agent version or partial capability.
- Informational: absent optional target or already-current artifact.

`doctor` validates manifests, hashes, reference cycles, missing resources,
native discovery paths, portable skill content, and references to the deleted
bootstrap repository.

## Testing and Release Gates

### Hosted CI

GitHub Actions runs on:

- `ubuntu-latest`;
- `windows-latest`;
- `macos-latest`.

The matrix covers Python 3.11 and the current stable Python release. CI does
not authenticate to or launch live Claude Code or Codex sessions.

### Unit tests

Unit coverage includes:

- schemas and manifests;
- cross-platform path resolution;
- redaction;
- capability negotiation;
- portable skill linting;
- source and generated hashes;
- drift handling;
- adapter mappings.

### Golden tests

Claude Code and Codex have golden output for:

- global setup;
- all three project profiles;
- common rules plus overlays;
- portable skills plus overlays;
- native entrypoints;
- command-to-skill conversion.

### Migration fixtures

Fixtures include:

- Claude-only state;
- Codex-only state;
- mixed Claude and Codex state;
- the sanitized legacy layout from this repository;
- conflicting skills;
- manually modified generated output;
- unknown settings and hooks;
- credential-bearing configuration;
- spaces, Unicode, and Windows drive-letter paths;
- damaged manifests;
- interrupted transactions.

### Integration properties

CLI integration tests use temporary home and project roots and prove:

- dry-run performs no writes;
- apply is idempotent;
- writes cannot escape allowed roots;
- rollback restores byte-identical input;
- a forced failure does not leave partial state;
- the installed manager works after deleting the bootstrap repository;
- `doctor` detects drift and broken references.

### Manual live smoke

Before a stable release:

1. install into a temporary home and project;
2. start fresh Claude Code and Codex sessions;
3. verify global and project rules plus overlays;
4. verify management-skill discovery and invocation;
5. run setup and migration dry-runs;
6. verify one project profile;
7. remove the bootstrap repository;
8. rerun `doctor`.

The operating system used for manual smoke may be whichever supported machine
is available. Live agent authentication is not required in hosted CI.

A stable release is blocked by failed CI, golden drift without an approved
change, broken idempotency, no-clobber or rollback behavior, or a failed live
smoke in either guaranteed adapter.

## Repository Transformation

The target source layout is:

```text
agent-workflow/
├── README.md
├── SETUP.md
├── pyproject.toml
├── src/agent_workflow/
│   ├── cli.py
│   ├── models/
│   ├── discovery/
│   ├── migration/
│   ├── transactions/
│   └── adapters/
│       ├── claude/
│       └── codex/
├── templates/
│   ├── core/
│   └── project-profiles/
├── skills/
│   ├── agent-workflow-setup/
│   ├── agent-workflow-migrate/
│   ├── wrap/
│   ├── backlog/
│   ├── pick/
│   ├── morning/
│   ├── tasks/
│   ├── my-reviews/
│   ├── feedback/
│   ├── plan-review/
│   └── code-review/
├── resources/
│   └── workitems-rendering.md
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   └── fixtures/legacy/
└── docs/
    ├── architecture.md
    ├── adapter-authoring.md
    ├── migration.md
    └── live-smoke.md
```

Existing content moves as follows:

- `home-claude/CLAUDE.md.example` splits into a neutral rules template and a
  Claude overlay.
- `commands/init-claude.md` becomes the basis of
  `agent-workflow-setup`.
- `wrap`, `backlog`, `pick`, `tasks`, `morning`, `my-reviews`, and `feedback`
  become portable Agent Skills.
- `plan-reviewer.md` and `code-reviewer.md` become `plan-review` and
  `code-review` skills with native delegation overlays where supported.
- `workitems-rendering.md` becomes a shared source resource packaged or
  referenced by the workitem skills.
- `settings.json.example` splits into portable setup defaults and Claude
  adapter mappings.
- `statusline.js` remains an optional Claude-only asset.
- The original top-level `home-claude/` tree is removed. Sanitized legacy
  equivalents remain only under `tests/fixtures/legacy/`.

`README.md` becomes agent-neutral. `SETUP.md` is the universal bootstrap
entrypoint. Separate documentation covers architecture, migration, project
profiles, adapters, safety, troubleshooting, and live smoke.

## Acceptance Criteria

The design is implemented when:

1. A user can download the repository, point Claude Code or Codex at
   `SETUP.md`, select targets, approve a plan, and complete setup.
2. The installed workflow remains functional after the downloaded repository
   is removed.
3. Global and project rules, neutral manual memory, sessions, and skills live
   under `.agents/`.
4. Claude Code and Codex load the same common rules and skills through their
   supported native mechanisms.
5. A project can be configured as local, shared, or split.
6. Claude-only and Codex-only fixtures migrate through dry-run, verified
   backup, preview, journaled apply, doctor, and rollback.
7. Existing credentials and unsupported settings are not copied or destroyed.
8. Generated-file drift is detected and never overwritten silently.
9. The full hosted CI matrix passes on Windows, macOS, and Linux.
10. Manual live smoke passes in both guaranteed adapters.

## Remaining Naming Decision

`agent-workflow`, `agent-workflow-setup`, and `agent-workflow-migrate` are
working names. Final public naming can be selected without changing the
architecture or implementation boundaries above.
