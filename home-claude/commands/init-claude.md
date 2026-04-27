---
description: Scaffold Claude Code setup in the current project. Creates .claude/ skeleton, draft CLAUDE.md, and (for sync-projects repos) .syncprotect/.syncignore. Idempotent — skips files that already exist.
---

The user invoked `/init-claude`. Bootstrap Claude Code setup in the current project. This is idempotent: for each target file, create it only if missing; skip existing files.

## Step 1 — Determine context (read-only)

1. Run `pwd`. Call the result `CWD`.
2. Compute `project_name` = basename of `CWD`.
3. Determine `is_sync_project`:
   - true if `CWD` starts with `C:\Users\Runker\sync-projects\` (Windows form) OR `/c/Users/Runker/sync-projects/` (Git Bash form).
   - false otherwise.
4. Check existence of each target via `test -f` / `test -d`:
   - `CLAUDE.md` at repo root
   - `.claude/settings.json`
   - `.claude/memory/MEMORY.md`
   - `.claude/sessions/.gitkeep` (file) and/or `.claude/sessions/` (directory)
   - `.syncprotect` at repo root — only relevant if `is_sync_project`
   - `.syncignore` at repo root — only relevant if `is_sync_project`
5. If **all** target files for this project type already exist (including `.syncprotect`/`.syncignore` when `is_sync_project`): jump straight to the "Nothing-to-do" case in Step 4 and STOP.

## Step 2 — Explore the code (only if CLAUDE.md is missing)

Skip this entire step if `CLAUDE.md` already exists at repo root.

### 2.1 Meta-files in repo root

For each of the following that exists, read and extract the facts listed. Use `Read` / `Grep`; don't guess.

- `pyproject.toml`: `[project].name`, `.version`, `.description`, `.requires-python`; entries under `[tool.taskipy.tasks]`; `[tool.setuptools].packages` or `[tool.poetry].packages`; presence of `[tool.black]`, `[tool.ruff]`, `[tool.isort]`.
- `package.json`: `name`, `version`, `description`, `engines`, `scripts`, `main`, `workspaces`.
- `go.mod`: module name (from `module` line), Go version (from `go` line).
- `Cargo.toml`: `[package].name`, `.version`, `.description`, `.edition`.
- `requirements.txt`: note existence; list top-level dependency names (cap at 10).
- `Makefile`: grep targets with `grep -nE "^[a-zA-Z_][a-zA-Z0-9_-]*:" Makefile | head -20`.
- `README.md` / `README.rst` / `README` / `README.txt`: read first 30 lines; look for a one-sentence project description.

### 2.2 Main package detection

Find the main package directory with this cascade (first match wins):

1. If `pyproject.toml` has explicit `packages` under `[tool.setuptools]` or `[tool.poetry]` — use the first entry.
2. Else: directory at first level named `<project_name_normalized>` (lowercase, hyphens → underscores).
3. Else: first existing of `src/`, `app/`, `cmd/`, `lib/`.
4. Else: mark "main package not detected" and skip 2.3.

### 2.3 Main package contents

If found in 2.2:

- `ls <main_pkg>` first level — collect module/directory names.
- Grep for entry-point patterns:
  - `grep -rn "app\s*=\s*FastAPI(\|app\s*=\s*Flask(\|app\.listen(\|def main(\|func main()" <main_pkg>` — collect file:line references.
- Grep for env vars:
  - `grep -rhoE "os\.getenv\(['\"][A-Z_][A-Z0-9_]*|process\.env\.[A-Z_][A-Z0-9_]*|std::env::var\(['\"][A-Z_][A-Z0-9_]*" <main_pkg>` — extract variable names, dedupe.

### 2.4 Supporting directories

Record existence only (don't read contents): `alembic/`, `migrations/`, `helm/`, `k8s/`, `docker/`, `Dockerfile`, `tests/`, `test/`.

## Step 3 — Create missing files (skip-existing)

For each target below, check existence first. Skip if present (add to "skipped" list). If missing, create with the content below using the `Write` tool (or `touch` for empty files).

### 3.1 `.claude/` directory scaffolding

First ensure `.claude/memory/` and `.claude/sessions/` directories exist: `mkdir -p .claude/memory .claude/sessions`.

### 3.2 `.claude/settings.json`

Content:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Write(.claude/sessions/**)",
      "Edit(.claude/sessions/**)",
      "Write(.claude/memory/**)",
      "Edit(.claude/memory/**)"
    ]
  }
}
```

### 3.3 `.claude/memory/MEMORY.md`

Content:

```markdown
# Project memory index

_Memories live in this folder. Add a pointer below for each memory file._

## project

(empty — add entries as `- [Title](file.md) — one-line hook` when you save memory files)

## reference

(empty — add entries as `- [Title](file.md) — one-line hook` when you save memory files)
```

### 3.4 `.claude/sessions/.gitkeep`

Empty file: `touch .claude/sessions/.gitkeep`.

### 3.5 `CLAUDE.md`

Generate from the template below. Fill in `{placeholders}` from Step 2 findings. Leave the `### TODO — open architecture areas` bullets verbatim (user will fill them).

**Template (copy into the file, substituting placeholders):**

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`{project_name}` — {one_line_description}. {runtime_line}.

## Project memory lives in this repo

Project and reference memory for this repo is kept at `.claude/memory/` (committed to git, shared with the team), **not** in the user-level memory path. At the start of every session, read `.claude/memory/MEMORY.md` and follow its pointers to pick up accumulated context. When saving new `project` or `reference` memories for this repo, write them to `.claude/memory/` and add an entry to `.claude/memory/MEMORY.md`. Continue to use the user-level memory path only for `feedback` and `user` type memories, which are personal and should not be shared.

{ENV_CONSTRAINTS_SECTION}

{COMMANDS_SECTION}

## Runtime entrypoints

{ENTRYPOINTS_SECTION}

## Architecture

### Structure

{STRUCTURE_SECTION}

### External integrations

{ENV_VARS_SECTION}

### TODO — open architecture areas

Fill these in as you understand the system. Don't silently invent answers — if relevant to a user request, ask.

- **High-level data flow:** inputs → processing → outputs. What's the request/event lifecycle?
- **Entity relationships:** how do the main data types relate? Where's the source of truth for each?
- **Public vs internal interfaces:** which APIs / methods are for external consumers, which are implementation details?
- **Consistency / concurrency guarantees:** any at-least-once, at-most-once, idempotency, locking semantics worth documenting?

## Conventions

{CONVENTIONS_SECTION}

## Review workflow

Follow the default review workflow from `~/.claude/CLAUDE.md` (snapshot plan to `.claude/sessions/_last_plan.md` before `ExitPlanMode`, invoke `plan-reviewer`; invoke `code-reviewer` before reporting done; skip both for trivial edits). Override here only if this project needs different behavior.
```

**Placeholder rules:**

- `{project_name}` — from meta-files or CWD basename.
- `{one_line_description}` — from `[project].description` / `package.json::description` / README first paragraph. If none: `TODO: one-line description of what this project does`.
- `{runtime_line}` — e.g. "Python ≥3.12, managed with uv", "Node 20, npm", "Go 1.22 module". If not detected: `TODO: runtime/language`.
- `{ENV_CONSTRAINTS_SECTION}`:
  - If `is_sync_project`:
    ```
    ## Environment constraints — read first

    - **This machine is Windows and has no corporate VPN access.** Don't run `uv sync` / `pip install` / `npm install`, don't run the service, don't call corporate-network services. When the user asks to "run", "test", or "try", confirm first rather than attempting it.
    - Shell is Git Bash on Windows — use Unix syntax and forward slashes; don't assume POSIX tools like a real `find`.
    ```
  - Else:
    ```
    ## Environment constraints — read first

    TODO: describe local environment constraints — what can/can't be run on this machine, any VPN/network requirements, shell specifics. Remove this section if none apply.
    ```
- `{COMMANDS_SECTION}`:
  - If `is_sync_project`:
    - Header: `## Commands (reference only — do NOT run on this machine)`
    - Intro line: `These are canonical commands used on a VPN-connected dev machine. Listed for reference; don't execute them here.`
    - Body: bullet per detected script/task: `- \`<command>\` — <one-line inferred purpose>`.
  - Else:
    - Header: `## Commands`
    - Body: same bullets, no warning line.
  - If nothing detected: body is `TODO: list the project's main scripts/tasks once they exist.`
- `{ENTRYPOINTS_SECTION}`:
  - If entry points found in 2.3: bullet list, each like `- [path/to/file.py](path/to/file.py) — <inferred purpose>`.
  - Else: `TODO: runtime entry points (main/app modules, CLI entry, etc.)`.
- `{STRUCTURE_SECTION}`:
  - If main package detected: `{main_pkg}/:` then a bullet list of first-level modules/dirs, each on its own line.
  - Else: `TODO: describe project structure once main package is identified.`
- `{ENV_VARS_SECTION}`:
  - If env vars found: group by prefix (everything up to first `_`). One bullet per group: `- **{PREFIX}_\***: {comma-separated var names}`.
  - Else: `TODO: list external integrations (databases, message queues, object storage, third-party APIs) with their env vars.`
- `{CONVENTIONS_SECTION}`:
  - Python version bullet if detected.
  - Node version bullet if detected.
  - Go version bullet if detected.
  - Rust edition bullet if detected.
  - Formatter bullet if detected (black/ruff/prettier/rustfmt/gofmt).
  - If `is_sync_project`: `- Russian comments and log messages may be present — preserve existing language when editing; don't translate.`
  - If `alembic/` or `migrations/` exists: `- {Alembic|DB} migrations live in \`{path}/\`.`
  - If empty: `TODO: project conventions (formatter, language, style).`

### 3.6 `.syncprotect` (only if `is_sync_project` is true)

Content:

```
.claude
CLAUDE.md
docs/
.sync-state
```

### 3.7 `.syncignore` (only if `is_sync_project` is true)

Content:

```
.claude
docs
CLAUDE.md
```

## Step 4 — Report to the user

Plain markdown, no outer code fence, under 400 words. Use this structure:

### Created files

Full absolute paths, one per line. If nothing was created and this isn't the "nothing-to-do" case, state "None (all targets already existed)."

### Skipped (already existed)

Full paths, one per line. Omit this section entirely if nothing was skipped.

### What was inferred from code

One-sentence summary. Example: "Detected Python ≥3.12 project (pyproject.toml), main package `trace_service/` with 5 modules, 3 entry points, 14 env vars across DATABASE/KAFKA/S3/REDIS/SALUTE_EYE namespaces."

Omit this section entirely if Step 2 was skipped (i.e., `CLAUDE.md` already existed).

### Open TODOs in CLAUDE.md

List each TODO placeholder you left (use labels from the template). Example:

- High-level data flow
- Entity relationships
- Public vs internal interfaces
- Consistency / concurrency guarantees
- Environment constraints (non-sync-projects repo)

Omit this section entirely if `CLAUDE.md` was skipped.

### Re-run safe

One line: `Re-running \`/init-claude\` will skip these and add anything missing.`

### Nothing-to-do case

If Step 1 determined every target already exists, skip the entire structured report and output only this single line:

> All targets already exist — nothing to create. Check `MEMORY.md` and `CLAUDE.md` for current state.

## Constraints

- Do NOT `git add` / `git commit` — Claude-config files are local-only (see global `~/.claude/CLAUDE.md`).
- Do NOT edit existing files. Skip-existing only. Never overwrite.
- Do NOT explore beyond what Step 2 prescribes — no `git log`, no deep file reads, no reading migrations/helm values.
- Do NOT generate `.claude/memory/*.md` project/reference memory files — memory grows incrementally across sessions.
- Keep the final report terse.
