# Migrating an existing agent setup

The migration workflow imports reusable state from Claude Code, Codex, or a
mixed setup into the neutral `.agents/` layout. It is conservative by design:
the manager previews every write, treats source files as immutable inputs, and
keeps the old native setup unless replacement is requested explicitly.

For ownership and data flow, see [architecture](architecture.md). The
credential, no-clobber, transaction, and external-adapter trust boundary is
defined in [safety](safety.md). Adapter authors should also read
[the adapter contract](adapter-authoring.md).

Use the installed `agent-workflow-migrate` skill when an agent is performing
the migration. The skill and the manager archive remain in `.agents/` after
the bootstrap repository is removed.

## Choose scope and targets

Migrate global and project state in separate runs:

- `--scope global` scans the selected adapters under the user's home
  directory and writes to the global `.agents/`.
- `--scope project` scans one discovered Git project, writes to that project's
  `.agents/`, and requires `--profile local`, `shared`, or `split`.
- `--targets` is an explicit list of adapters to scan and map. Use
  `claude codex` for the guaranteed adapters even if only one currently owns
  legacy files.

Run `agent-workflow scan --agents` first to see registered adapters and local
detection results. Detection is advice, not consent: the user still selects
the migration targets and project profile.

The examples below use `agent-workflow` as shorthand for:

```text
python PATH_TO_AGENT_WORKFLOW_PYZ
```

When running directly from this checkout during bootstrap, use:

```text
python -m agent_workflow
```

with the checkout's `src` directory on `PYTHONPATH`.

## Preview-first sequence

Keep the generated JSON files together until the migration is complete. For a
global migration:

```text
agent-workflow migrate scan --scope global --targets claude codex --output inventory.json
agent-workflow migrate normalize --inventory inventory.json --output normalized.json
agent-workflow migrate classify-request --inventory inventory.json --output request.json
```

For a project migration, add the same project location to every command that
reads source state:

```text
agent-workflow migrate scan --scope project --profile split --targets claude codex --cwd PROJECT --output inventory.json
agent-workflow migrate normalize --inventory inventory.json --home HOME --cwd PROJECT --output normalized.json
agent-workflow migrate classify-request --inventory inventory.json --home HOME --cwd PROJECT --output request.json
```

Inspect `inventory.json`, warnings, and the classification request. If
`request.json` contains artifacts, have the current agent follow
`agent-workflow-migrate` and its classification contract to create
`response.json`, then validate it:

```text
agent-workflow migrate validate-response --request request.json --response response.json
```

Create a materialized plan. Include `--response response.json` only when the
request contains ambiguous artifacts:

```text
agent-workflow migrate plan --scope global --targets claude codex --inventory inventory.json --normalized normalized.json --response response.json --imported-at TIMESTAMP --output migration-plan.json
agent-workflow migrate report --plan migration-plan.json --output migration-preview.md
```

For project scope, use the same `--scope project --profile PROFILE --home HOME
--cwd PROJECT` values used during scanning. Review `migration-preview.md`
before applying anything. A blocking conflict means the plan is dry-run only.

Apply prompts for confirmation:

```text
agent-workflow migrate apply --plan migration-plan.json
```

`--yes` is intended only for automation that has already reviewed that exact
materialized plan. Apply re-hashes every source first. It writes imports
through a journaled transaction, runs doctor, and reports backup and rollback
locations.

Finally, verify the selected neutral root explicitly:

```text
agent-workflow doctor --scope-root PATH_TO_DOT_AGENTS
```

## Deterministic and agent-assisted work

Python handles artifacts with a structural, unambiguous conversion:

- a valid Agent Skill stays a skill;
- a legacy command becomes one portable skill with the command's stable name;
- manual memory keeps its body and gains provenance when needed;
- session notes keep their content and receive a collision-safe name;
- opted-in native auto-memory is isolated under an agent-specific cache;
- known native settings are parsed and mapped field by field.

Prose rules, subagent prompts, and unknown files require semantic
classification. The agent may choose only a closed decision kind for each
enumerated artifact ID. It cannot choose filesystem destinations, authorize
writes, or add artifacts. Python validates the response and derives every
destination.

Different inputs that claim the same portable destination are never silently
merged. Identical inputs may be deduplicated with provenance; different
content produces a blocking conflict and stable alternative names for review.

## Privacy boundary

The manager performs no network request. Nothing leaves the machine
automatically.

If classification is performed by a hosted agent, only the contents of the
user-reviewed `request.json` are exposed to that agent. The request contains:

- request and artifact digests;
- registered adapter IDs and allowed decision kinds;
- artifact kind, scope, media type, and a relative label;
- at most 64 KiB of UTF-8 text per ambiguous artifact;
- sensitivity, redaction reasons, and truncation flags.

Credential-like values and private absolute paths are redacted before the
request is written. Unreadable or blocked artifacts are omitted. Do not submit
the raw inventory, settings files, native cache, backups, journal, or plan to a
model provider. Stop if manual inspection finds data that should not leave the
machine.

## Commands, skills, memory, and native state

Legacy command conversion is mechanical: frontmatter supplies the
description, the filename supplies a kebab-case skill name, and known
agent-owned skill paths are rewritten to `.agents/skills`. The resulting
`SKILL.md` must pass the portable skill linter. Existing standard skills are
copied byte-for-byte only when the whole directory is portable.

Manual memory is durable user-authored knowledge and migrates to
`.agents/memory/` with source agent, scope, relative label, and source hash.
The manager writes the deterministic `.agents/memory/IMPORTED.md` provenance
index, and the canonical memory index points agents to it. Imported common
rules remain separate under `.agents/rules/`; canonical `RULES.md` requires
agents to load those files in stable order.
Native automatic memory is not equivalent. It stays excluded by default; with
`--include-native-cache`, selected entries go only to
`.agents/cache/AGENT/memory/` and never become authoritative manual memory.

Native mapping states mean:

| State | Meaning |
|---|---|
| `exact` | The adapter has a documented lossless target field. |
| `partial` | A safe subset maps; every omitted field is listed. |
| `manual` | The user must recreate or approve semantics in the target agent. |
| `unsupported` | No guaranteed equivalent exists; the source stays intact. |
| `sensitive_skip` | A credential-bearing value is omitted and must be entered manually. |

Claude and Codex permission models are not treated as equivalent. Hooks remain
unsupported without proven lifecycle parity. MCP server name, command, and
non-sensitive arguments can map exactly; credential values never migrate.

## Replacement and keeping the old setup

The default plan imports neutral content and preserves every source. This is a
valid long-term mode: omit `--replace-native`, keep using the old native
configuration, and adopt neutral files gradually.

To request cleanup, rebuild the plan with `--replace-native`. This is a
separate decision from confirming apply. Fully migrated legacy commands,
skills, memory, and sessions are removed through exact-hash delete operations.
For the guaranteed built-in adapters, a fully migrated native instruction file
is atomically replaced by the generated entrypoint instead of being deleted.
The neutral manifest records the generated entrypoint, while
`workflow/migration-replacements.json` records both original and replacement
hashes. Unsupported settings, credentials, unknown artifacts, and
unreconciled instruction files remain in place. The preview lists every
preserved source.

External adapters can participate in import and mapping, but automatic native
replacement requires installed built-in planning support. Keep the old native
files and finish their adapter-specific entrypoints manually when that support
is unavailable.

An external adapter's capability claims do not make it guaranteed. Mapping
coverage, sanitized fixtures, doctor validation, and versioned live smoke are
required by the [adapter support policy](adapter-authoring.md).

## Backup, rollback, and recovery

Import and native replacement are separate transactions. Replacement starts
only after import doctor succeeds and source hashes still match. If
post-replacement doctor fails, replacement is rolled back while the valid
neutral import remains.

The apply result prints transaction journals, backup directories, and rollback
locations. Restore any completed transaction with:

```text
agent-workflow rollback JOURNAL_PATH
```

Then run doctor again. Never edit a journal or backup in place.

If any source changes after scan or preview, apply stops with source drift and
writes nothing from the stale plan. Keep the edited source, discard the old
inventory, normalization, request, response, and plan, then rerun the complete
sequence. Do not repair hashes by hand.
