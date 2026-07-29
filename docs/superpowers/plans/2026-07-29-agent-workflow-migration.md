# Agent Workflow Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely migrate an existing Claude-only, Codex-only, or mixed agent setup into the canonical `.agents` workflow while preserving meaning, excluding credentials, previewing every change, and keeping the source recoverable.

**Architecture:** Migration is a staged compiler. Read-only adapter scanners inventory legacy artifacts, a redaction boundary prepares semantic classification requests, deterministic normalizers handle recognized structures, and a validated classification response resolves ambiguous prose. The resulting neutral and native writes are composed into Plan 1's transaction plan; source replacement is a separate, explicitly enabled final phase.

**Tech Stack:** Plans 1 and 2 Python APIs; Python 3.11 standard library at runtime; `dataclasses`, `enum`, `json`, `re`, `tomllib`, `configparser`, and `pathlib`; development-only `pytest` fixtures and golden snapshots.

## Global Constraints

- Plans 1 and 2 completion gates are prerequisites.
- Scan and classification-request generation are read-only.
- Python owns path selection, sensitive-data filtering, conflicts, transaction composition, and rollback.
- An LLM may classify semantic meaning but may not choose arbitrary filesystem destinations.
- No secrets, tokens, credentials, authentication state, shell history, or opaque binary state may enter a classification request.
- Standard Agent Skills are imported deterministically without semantic rewriting.
- Legacy commands become portable skills; native commands are generated wrappers or aliases only.
- Neutral manual memory is authoritative; native auto-memory may be retained only as an explicitly labeled cache.
- Existing source files remain untouched unless `--replace-native` is explicitly requested after a successful import preview.
- Unsupported native settings stay in place and appear in the report.
- Migration never reports success while unresolved conflicts, stale source hashes, failed validation, or incomplete backups remain.
- The same inventory and classification response must produce byte-identical plans on Windows, macOS, and Linux.

---

## File Map

- `src/agent_workflow/migration/model.py`: inventory, artifact, classification, and migration report models.
- `src/agent_workflow/migration/inventory.py`: multi-adapter inventory composition and source hashing.
- `src/agent_workflow/migration/redaction.py`: sensitive-key and sensitive-text filtering.
- `src/agent_workflow/migration/normalize.py`: deterministic importers for known artifact kinds.
- `src/agent_workflow/migration/classification.py`: redacted exchange schema and response validation.
- `src/agent_workflow/migration/mappings.py`: explicit Claude/Codex settings, permission, hook, and MCP mappings.
- `src/agent_workflow/migration/planner.py`: neutral/native migration plan composition.
- `src/agent_workflow/migration/report.py`: JSON and Markdown preview/report renderers.
- `src/agent_workflow/adapters/*/migration.py`: agent-specific discovery and native mapping hooks.
- `skills/agent-workflow-migrate/`: installed portable orchestration skill.
- `tests/fixtures/legacy/`: sanitized Claude-only, Codex-only, mixed, and conflicting setups.
- `tests/migration/`: unit, golden, and end-to-end migration tests.

## Test Helper Contract

Create `tests/migration/helpers.py` in Task 1 and extend it only alongside the
task that first uses each helper. It owns deterministic builders named
`fake_adapter_context`, `populated_mixed_context`, `standard_skill_fixture`,
`claude_command_fixture`, `memory_fixture`, `write_inventory_fixture`,
`write_request_fixture`, `write_response_fixture`, `map_fixture`,
`migration_inputs`, `planned_migration`, `materialize_legacy_fixture`,
`run_fixture_migration`, `golden_text`, `golden_json`, and `tree_snapshot`.
Every helper accepts a pytest temporary root, uses only sanitized fixture data,
and writes nowhere outside that root. Test modules import used helpers
explicitly from this module.

### Task 1: Inventory Models and Adapter Scanners

**Files:**
- Create: `src/agent_workflow/migration/__init__.py`
- Create: `src/agent_workflow/migration/model.py`
- Create: `src/agent_workflow/migration/inventory.py`
- Create: `src/agent_workflow/adapters/claude/migration.py`
- Create: `src/agent_workflow/adapters/codex/migration.py`
- Modify: `src/agent_workflow/adapters/base.py`
- Modify: `src/agent_workflow/adapters/claude/adapter.json`
- Modify: `src/agent_workflow/adapters/codex/adapter.json`
- Create: `tests/migration/test_inventory.py`
- Create: `tests/migration/helpers.py`

**Interfaces:**
- Produces: `ArtifactKind`, `ArtifactScope`, `Sensitivity`, `ArtifactRecord`, `MigrationInventory`
- Extends: `AgentAdapter.inventory_roots(context) -> tuple[InventoryRoot, ...]`
- Produces: `scan_migration_inventory(context, adapters) -> MigrationInventory`
- Consumes: Plan 1 `HostPaths`, `Scope`, and SHA-256 helpers

- [ ] **Step 1: Add failing inventory tests**

```python
# tests/migration/test_inventory.py
from pathlib import Path

from agent_workflow.adapters.registry import AdapterRegistry
from agent_workflow.migration.inventory import scan_migration_inventory
from agent_workflow.migration.model import ArtifactKind, ArtifactScope


def test_scans_claude_and_codex_without_reading_outside_declared_roots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "wrap.md").write_text(
        "Create a session note.", encoding="utf-8"
    )
    (project / "AGENTS.md").parent.mkdir(parents=True)
    (project / "AGENTS.md").write_text("Project rules.", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be scanned", encoding="utf-8")

    inventory = scan_migration_inventory(
        context=fake_adapter_context(home=home, project=project),
        adapters=AdapterRegistry.builtins().require(("claude", "codex")),
    )

    assert {(item.agent_id, item.kind, item.scope) for item in inventory.artifacts} == {
        ("claude", ArtifactKind.COMMAND, ArtifactScope.GLOBAL),
        ("codex", ArtifactKind.RULES, ArtifactScope.PROJECT),
    }
    assert all(item.path != outside for item in inventory.artifacts)
    assert all(len(item.sha256) == 64 for item in inventory.artifacts)


def test_inventory_order_is_stable(tmp_path: Path) -> None:
    context = populated_mixed_context(tmp_path)
    registry = AdapterRegistry.builtins()

    first = scan_migration_inventory(context, registry.require(("codex", "claude")))
    second = scan_migration_inventory(context, registry.require(("claude", "codex")))

    assert first.to_json() == second.to_json()
```

- [ ] **Step 2: Run the tests and confirm the missing migration package**

Run: `pytest tests/migration/test_inventory.py -q`

Expected: FAIL because `agent_workflow.migration` does not exist.

- [ ] **Step 3: Implement the serialized inventory contract**

Define these exact values and fields:

```python
# src/agent_workflow/migration/model.py
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ArtifactKind(StrEnum):
    RULES = "rules"
    MANUAL_MEMORY = "manual_memory"
    AUTO_MEMORY = "auto_memory"
    SESSION = "session"
    SKILL = "skill"
    COMMAND = "command"
    SUBAGENT_PROMPT = "subagent_prompt"
    SETTINGS = "settings"
    PERMISSIONS = "permissions"
    HOOKS = "hooks"
    MCP = "mcp"
    UNKNOWN = "unknown"


class ArtifactScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"


class Sensitivity(StrEnum):
    SAFE = "safe"
    REDACTED = "redacted"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    agent_id: str
    kind: ArtifactKind
    scope: ArtifactScope
    path: Path
    relative_path: str
    sha256: str
    media_type: str
    size_bytes: int
    sensitivity: Sensitivity
    already_neutral: bool


@dataclass(frozen=True)
class MigrationInventory:
    schema_version: int
    roots: tuple[str, ...]
    artifacts: tuple[ArtifactRecord, ...]
    warnings: tuple[str, ...]
```

Serialization must:

- emit paths as forward-slash relative strings;
- sort artifacts by `(scope, agent_id, relative_path, artifact_id)`;
- derive `artifact_id` from agent, scope, normalized relative path, and source hash;
- reject duplicate `artifact_id` values;
- preserve the absolute path only in memory, never in portable JSON output.

- [ ] **Step 4: Add migration roots to the adapter contract**

Add `InventoryRoot(kind, scope, path, recursive, include_globs)` to
`adapters/base.py`. Implement explicit roots:

- Claude global: `~/.claude/CLAUDE.md`, `commands/`, `skills/`, `agents/`,
  `projects/`, `settings.json`, `settings.local.json`;
- Claude project: `CLAUDE.md`, `CLAUDE.local.md`, `.claude/commands/`,
  `.claude/skills/`, `.claude/agents/`, `.claude/settings.json`,
  `.claude/settings.local.json`;
- Codex global: `~/.codex/AGENTS.md`, `~/.agents/skills/`,
  `~/.codex/skills/`, `~/.codex/memory/`, `~/.codex/config.toml`;
- Codex project: `AGENTS.md`, `AGENTS.override.md`, `.agents/skills/`,
  `.codex/skills/`, `.codex/memory/`, `.codex/config.toml`.

Every root is opt-in and bounded. A missing path is normal. A symlink or
junction that resolves outside its declared home or project boundary becomes a
warning and is not traversed.

- [ ] **Step 5: Implement scan composition and rerun**

`scan_migration_inventory` must classify by the most specific declared root,
hash regular files, record directories only as containers for skill discovery,
skip manager-owned generated files already present in the workflow manifest,
mark content already under the selected `.agents` root as
`already_neutral=True`, and never parse content during this task.

Run: `pytest tests/migration/test_inventory.py tests/adapters -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent_workflow/migration src/agent_workflow/adapters tests/migration/test_inventory.py
git commit -m "feat: inventory legacy agent setups"
```

### Task 2: Redaction and Classification Boundary

**Files:**
- Create: `src/agent_workflow/migration/redaction.py`
- Create: `src/agent_workflow/migration/classification.py`
- Create: `tests/migration/test_redaction.py`
- Create: `tests/migration/test_classification.py`
- Create: `tests/fixtures/migration/classification-response.schema.json`

**Interfaces:**
- Produces: `RedactedArtifact`
- Produces: `redact_artifact(record: ArtifactRecord) -> RedactedArtifact`
- Produces: `ClassificationRequest`, `ClassificationDecision`, `ClassificationResponse`
- Produces: `build_classification_request(inventory) -> ClassificationRequest`
- Produces: `load_classification_response(path, request) -> ClassificationResponse`

- [ ] **Step 1: Add failing secret-boundary tests**

```python
# tests/migration/test_redaction.py
import json

from agent_workflow.migration.redaction import redact_json, redact_text


def test_redacts_sensitive_json_keys_recursively() -> None:
    source = {
        "mcpServers": {
            "demo": {
                "command": "server",
                "env": {"API_TOKEN": "secret-value", "MODE": "safe"},
            }
        },
        "permissions": {"allow": ["Read"]},
    }

    redacted = redact_json(source)

    assert redacted["mcpServers"]["demo"]["env"]["API_TOKEN"] == "<redacted>"
    assert redacted["mcpServers"]["demo"]["env"]["MODE"] == "safe"
    assert "secret-value" not in json.dumps(redacted)


def test_blocks_private_key_material() -> None:
    text = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"

    result = redact_text(text)

    assert result.blocked
    assert result.text is None
    assert "private-key" in result.reasons
```

```python
# tests/migration/test_classification.py
from agent_workflow.migration.classification import (
    ClassificationDecision,
    DecisionKind,
    validate_classification_response,
)


def test_response_cannot_choose_a_raw_destination() -> None:
    response = {
        "schema_version": 1,
        "request_id": "request-1",
        "decisions": [{
            "artifact_id": "artifact-1",
            "kind": "skill",
            "name": "wrap",
            "destination": "../../escape",
        }],
    }

    errors = validate_classification_response(response, allowed_artifact_ids={"artifact-1"})

    assert "destination" in errors[0]


def test_decision_kind_is_closed() -> None:
    decision = ClassificationDecision(
        artifact_id="artifact-1",
        kind=DecisionKind.COMMON_RULE,
        name=None,
        rationale="Shared behavior.",
        confidence="high",
    )

    assert decision.kind.value == "common_rule"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/migration/test_redaction.py tests/migration/test_classification.py -q`

Expected: FAIL because the modules are absent.

- [ ] **Step 3: Implement conservative redaction**

Use case-insensitive exact keys and suffixes for:

`token`, `api_key`, `apikey`, `secret`, `password`, `passwd`, `credential`,
`credentials`, `private_key`, `access_key`, `secret_key`, `authorization`,
`cookie`, `session`, and any environment key ending in `_TOKEN`, `_SECRET`,
`_PASSWORD`, `_KEY`, or `_CREDENTIAL`.

Text scanning must block the whole artifact for:

- PEM private-key headers;
- common bearer-token assignments;
- cloud access-key patterns;
- values labeled password, token, secret, or API key with non-placeholder data.

For structured JSON/TOML settings, keep safe keys and replace sensitive values
with the literal `<redacted>`. For prose, replace a matched scalar with
`<redacted>` only when boundaries are unambiguous; otherwise block the artifact.
Store reason codes, never the removed value.

- [ ] **Step 4: Define the closed classification schema**

Use these decision kinds:

```python
class DecisionKind(StrEnum):
    COMMON_RULE = "common_rule"
    AGENT_OVERLAY = "agent_overlay"
    SKILL = "skill"
    MANUAL_MEMORY = "manual_memory"
    SESSION_CONTEXT = "session_context"
    NATIVE_SETTING = "native_setting"
    UNSUPPORTED = "unsupported"
    SENSITIVE_SKIP = "sensitive_skip"
    CONFLICT = "conflict"
```

Each decision contains only:

- `artifact_id`;
- one closed `kind`;
- optional portable `name` matching `[a-z0-9][a-z0-9-]{0,62}`;
- `rationale` of at most 500 characters;
- `confidence` in `high|medium|low`;
- optional `agent_id` selected from the request's known adapters.

The response cannot contain paths, shell commands, file bytes, additional
artifacts, or unknown keys. It must cover every ambiguous artifact exactly
once, refer to the request hash, and leave deterministic artifacts out. Run
the response through the same sensitive-text scanner and reject it if a
credential-like value appears in a name or rationale.

- [ ] **Step 5: Build a redacted request format**

`ClassificationRequest.to_json()` contains:

- schema version and deterministic request ID;
- known target adapter IDs;
- allowed decision kinds;
- artifact ID, original kind, scope, media type, safe relative label, and
  redacted text;
- no absolute paths, usernames, home paths, credentials, or source bytes for
  deterministic artifacts.

Limit each text artifact to 64 KiB after redaction and report truncation.
Reject request creation if any blocked secret reaches serialized output.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/migration/test_redaction.py tests/migration/test_classification.py -q`

Expected: PASS.

```bash
git add src/agent_workflow/migration tests/migration/test_redaction.py tests/migration/test_classification.py tests/fixtures/migration
git commit -m "feat: define safe migration classification boundary"
```

### Task 3: Deterministic Normalizers

**Files:**
- Create: `src/agent_workflow/migration/normalize.py`
- Create: `tests/migration/test_normalize.py`
- Create: `tests/fixtures/legacy/standard-skill/`
- Create: `tests/fixtures/legacy/claude-command/`
- Create: `tests/fixtures/legacy/manual-memory/`
- Create: `tests/fixtures/legacy/session-notes/`

**Interfaces:**
- Produces: `NormalizedArtifact`
- Produces: `normalize_deterministic(record, source_root) -> NormalizedArtifact | None`
- Produces: `convert_command_to_skill(record, text) -> NormalizedArtifact`
- Produces: `merge_memory_index(entries) -> bytes`

- [ ] **Step 1: Add failing normalization tests**

```python
# tests/migration/test_normalize.py
from pathlib import Path

from agent_workflow.migration.model import ArtifactKind
from agent_workflow.migration.normalize import normalize_deterministic


def test_standard_skill_is_copied_byte_for_byte(tmp_path: Path) -> None:
    record, source = standard_skill_fixture(tmp_path, name="wrap")

    normalized = normalize_deterministic(record, source)

    assert normalized is not None
    assert normalized.kind is ArtifactKind.SKILL
    assert normalized.root_id == "neutral"
    assert normalized.relative_destination == "skills/wrap"
    assert normalized.files["SKILL.md"] == (source / "SKILL.md").read_bytes()


def test_claude_command_becomes_a_portable_skill(tmp_path: Path) -> None:
    record, source = claude_command_fixture(
        tmp_path,
        name="pick",
        body="Resolve a backlog item and start it.",
    )

    normalized = normalize_deterministic(record, source)

    assert normalized.root_id == "neutral"
    assert normalized.relative_destination == "skills/pick"
    text = normalized.files["SKILL.md"].decode()
    assert "name: pick" in text
    assert "Resolve a backlog item and start it." in text
    assert ".claude" not in text


def test_manual_memory_keeps_provenance_and_source_hash(tmp_path: Path) -> None:
    record, source = memory_fixture(tmp_path, "preferences.md")

    normalized = normalize_deterministic(record, source)

    assert normalized.root_id == "neutral"
    assert normalized.relative_destination.startswith("memory/")
    assert normalized.provenance.source_sha256 == record.sha256
    assert normalized.provenance.source_agent == record.agent_id
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/migration/test_normalize.py -q`

Expected: FAIL because `normalize.py` is absent.

- [ ] **Step 3: Implement the deterministic routing table**

Use this exact routing:

| Source artifact | Neutral destination | Transformation |
|---|---|---|
| valid Agent Skill directory outside neutral root | `neutral:skills/<name>/` | byte-for-byte copy after portable lint |
| valid Agent Skill already at `neutral:skills/<name>/` | same path | adopt existing hash into manifest; no copy |
| Claude command Markdown | `neutral:skills/<slug>/SKILL.md` | add Agent Skill frontmatter; preserve body |
| Codex or Claude manual memory | `neutral:memory/<unique-slug>.md` | preserve body; add provenance frontmatter only when absent |
| session note | `neutral:sessions/<date>-<unique-slug>.md` | preserve body; normalize filename |
| shared rule file with explicit include markers | `neutral:rules/<slug>.md` | preserve body and provenance |
| native auto-memory | `neutral:cache/<agent>/memory/` | copy only when user selected `--include-native-cache` |
| settings, permissions, hooks, MCP | no neutral file yet | defer to Task 5 |
| unknown prose | no destination | include in classification request |

`NormalizedArtifact` stores `root_id="neutral"` separately from its relative
destination so transaction planning never embeds `.agents` twice.
For an `already_neutral` artifact at its final destination, it stores
`adopt_existing=True`; planning records ownership only after the bytes pass
lint and still match the inventory hash.

Name collisions never overwrite. If hashes match, deduplicate and record both
origins. If hashes differ, suffix the candidate with `-from-<agent>` and emit a
conflict requiring classification or user selection.

- [ ] **Step 4: Implement command-to-skill conversion**

The generated `SKILL.md` must have:

```yaml
---
name: pick
description: Resolve a backlog item and start planning work on it.
---
```

Derive `description` from explicit legacy frontmatter when present; otherwise
use the first non-heading sentence, trimmed to 200 characters. Keep argument
instructions in the body. Replace only exact agent-owned path tokens for which
the adapter supplies a neutral mapping. Do not paraphrase executable
instructions during deterministic conversion.

- [ ] **Step 5: Implement memory and session indexing**

Create stable index entries containing relative path, one-line title,
source-agent ID, source relative label, source SHA-256, and import timestamp.
The index writer sorts by relative path and is idempotent. It does not merge two
prose documents or treat auto-memory as authoritative manual memory.

- [ ] **Step 6: Run focused and portability tests**

Run: `pytest tests/migration/test_normalize.py tests/test_portability.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agent_workflow/migration/normalize.py tests/migration/test_normalize.py tests/fixtures/legacy
git commit -m "feat: normalize portable legacy artifacts"
```

### Task 4: LLM-Assisted Semantic Classification Exchange

**Files:**
- Modify: `src/agent_workflow/migration/classification.py`
- Modify: `src/agent_workflow/cli.py`
- Modify: `src/agent_workflow/package.py`
- Modify: `src/agent_workflow/setup.py`
- Create: `skills/agent-workflow-migrate/SKILL.md`
- Create: `skills/agent-workflow-migrate/references/classification-contract.md`
- Create: `tests/migration/test_classification_cli.py`
- Create: `tests/skills/test_migrate_skill.py`

**Interfaces:**
- Adds CLI: `agent-workflow migrate classify-request --inventory INVENTORY --output REQUEST`
- Adds CLI: `agent-workflow migrate validate-response --request REQUEST --response RESPONSE`
- Consumes: a response file produced by the current agent following the installed migration skill
- Produces: validated decisions only; no direct model-provider API dependency

- [ ] **Step 1: Add failing CLI exchange tests**

```python
# tests/migration/test_classification_cli.py
import json
from pathlib import Path

from agent_workflow.cli import main


def test_classify_request_contains_redacted_ambiguous_artifacts(
    tmp_path: Path,
) -> None:
    inventory = write_inventory_fixture(tmp_path)
    output = tmp_path / "request.json"

    code = main([
        "migrate", "classify-request",
        "--inventory", str(inventory),
        "--output", str(output),
    ])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["artifacts"]
    assert "secret-value" not in output.read_text(encoding="utf-8")


def test_invalid_response_never_reaches_planning(tmp_path: Path) -> None:
    request = write_request_fixture(tmp_path)
    response = write_response_fixture(tmp_path, request_id="wrong-request")

    code = main([
        "migrate", "validate-response",
        "--request", str(request),
        "--response", str(response),
    ])

    assert code == 2
```

- [ ] **Step 2: Run and confirm parser failure**

Run: `pytest tests/migration/test_classification_cli.py -q`

Expected: FAIL because `migrate` subcommands are not registered.

- [ ] **Step 3: Implement file-based exchange commands**

The manager intentionally has no direct OpenAI, Anthropic, or other model API
client. `classify-request` writes the safe request. The currently running agent
reads that file, follows the migration skill, and writes a response conforming
to the closed schema. `validate-response` verifies request ID, request SHA-256,
coverage, enums, names, agent IDs, lengths, and unknown fields before any plan
can consume it.

- [ ] **Step 4: Write the portable migration skill**

The skill must instruct any capable agent to:

1. run read-only inventory;
2. show artifact counts and sensitive skips;
3. run deterministic normalization;
4. generate and inspect the redacted classification request;
5. classify only enumerated artifact IDs using the closed decision kinds;
6. validate the response with Python;
7. generate a preview and summarize conflicts;
8. require explicit user confirmation before apply or native replacement;
9. run doctor after apply and report backup/rollback locations.

It must state that the repository may be deleted after installation and that
the installed zipapp plus `.agents/skills/agent-workflow-migrate/` are the
persistent tools.
Extend the zipapp bundler's fixed skill-resource list with
`agent-workflow-migrate`, and have a global upgrade/setup plan materialize it
from `agent_workflow/_bundled/skills/` beside the setup skill.

- [ ] **Step 5: Validate the skill and exchange**

Run: `pytest tests/migration/test_classification_cli.py tests/skills/test_migrate_skill.py tests/test_portability.py -q`

Expected: PASS and no provider-specific API dependency in package metadata.

- [ ] **Step 6: Commit**

```bash
git add src/agent_workflow/migration/classification.py src/agent_workflow/cli.py src/agent_workflow/package.py src/agent_workflow/setup.py skills/agent-workflow-migrate tests/migration/test_classification_cli.py tests/skills/test_migrate_skill.py
git commit -m "feat: add agent-assisted migration classification"
```

### Task 5: Explicit Native Settings, Permissions, Hooks, and MCP Mappings

**Files:**
- Create: `src/agent_workflow/migration/mappings.py`
- Modify: `src/agent_workflow/adapters/base.py`
- Modify: `src/agent_workflow/adapters/claude/migration.py`
- Modify: `src/agent_workflow/adapters/codex/migration.py`
- Create: `tests/migration/test_mappings.py`
- Create: `tests/fixtures/legacy/settings/`

**Interfaces:**
- Produces: `MappingStatus`, `NativeMapping`, `MappedNativeArtifact`
- Extends: `AgentAdapter.map_native_artifact(record, safe_content, target_context)`
- Produces: `map_native_artifacts(records, source_adapter, target_adapters)`

- [ ] **Step 1: Add failing mapping tests**

```python
# tests/migration/test_mappings.py
def test_claude_permissions_map_only_known_safe_rules() -> None:
    source = {"permissions": {"allow": ["Read", "Glob", "Grep"], "deny": ["Bash(rm:*)"]}}

    result = map_fixture(source, from_agent="claude", to_agent="codex")

    assert result.status.value == "manual"
    assert not result.write_operations
    assert result.unmapped == ("Read", "Glob", "Grep", "Bash(rm:*)")


def test_mcp_credentials_are_never_copied() -> None:
    source = {
        "mcpServers": {
            "demo": {
                "command": "demo-server",
                "args": ["--stdio"],
                "env": {"API_TOKEN": "secret-value"},
            }
        }
    }

    result = map_fixture(source, from_agent="claude", to_agent="codex")

    assert result.status.value == "manual"
    assert "secret-value" not in result.serialized_preview()
    assert result.credential_fields == ("mcpServers.demo.env.API_TOKEN",)


def test_unknown_hook_is_preserved_at_source() -> None:
    result = map_fixture(
        {"hooks": {"CustomFutureEvent": [{"command": "tool"}]}},
        from_agent="claude",
        to_agent="codex",
    )

    assert result.status.value == "unsupported"
    assert not result.write_operations
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/migration/test_mappings.py -q`

Expected: FAIL because mapping APIs do not exist.

- [ ] **Step 3: Implement a data-driven mapping status**

```python
class MappingStatus(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"
    SENSITIVE_SKIP = "sensitive_skip"
```

Each mapping records the source key, target key, status, safe normalized value,
unmapped fields, credential field labels, rationale, and adapter version. A
mapping may generate a write only for `EXACT`, or for `PARTIAL` after the
preview makes every omitted field explicit.

- [ ] **Step 4: Implement conservative guaranteed-adapter mappings**

Support only mappings proven by adapter tests and documented in the adapter
manifest:

- rule entrypoint references and include files;
- canonical skill discovery or generated wrappers;
- MCP server name, executable, and non-sensitive arguments;
- safe environment variable *names* as prompts for manual re-entry, never their
  values;
- hooks only when source and target lifecycle events have the same documented
  semantics.

Do not infer equivalence from similar names. In the initial guaranteed
adapters, Claude permission matchers and Codex sandbox/approval policies are
reported as `MANUAL` and never converted automatically. Model choice, approval
policy, sandbox policy, permission matchers, hook lifecycle, UI preferences,
status line, experimental flags, and unknown settings remain adapter-native
unless a later mapping has documented semantic equivalence and a focused test.

- [ ] **Step 5: Make unsupported state visible**

Reports must group mappings as exact, partial, manual, unsupported, and
sensitive-skip. They must say which original source files remain required.
`--replace-native` is blocked while the selected source file contains an
unsupported or manual field.

- [ ] **Step 6: Run focused tests and commit**

Run: `pytest tests/migration/test_mappings.py tests/adapters -q`

Expected: PASS.

```bash
git add src/agent_workflow/migration/mappings.py src/agent_workflow/adapters tests/migration/test_mappings.py tests/fixtures/legacy/settings
git commit -m "feat: map supported native agent settings"
```

### Task 6: Preview, Apply, Native Replacement, and Rollback

**Files:**
- Create: `src/agent_workflow/migration/planner.py`
- Create: `src/agent_workflow/migration/apply.py`
- Create: `src/agent_workflow/migration/report.py`
- Modify: `src/agent_workflow/cli.py`
- Modify: `src/agent_workflow/doctor.py`
- Create: `tests/migration/test_planner.py`
- Create: `tests/migration/test_apply.py`
- Create: `tests/integration/test_migration_cli.py`

**Interfaces:**
- Produces: `MigrationOptions`, `MigrationPlanResult`
- Produces: `build_migration_plan(inventory, normalized, decisions, mappings, options) -> MigrationPlanResult`
- Produces: `apply_migration(result: MigrationPlanResult) -> MigrationApplyResult`
- Adds CLI: `agent-workflow migrate scan|normalize|plan|apply|report`
- Consumes: Plan 1 `TransactionPlan`, `WriteOperation`, `DeleteOperation`,
  `SourceChangedError`, `apply_plan`, and `rollback_transaction`

- [ ] **Step 1: Add failing no-clobber and stale-source tests**

```python
# tests/migration/test_planner.py
def test_plan_separates_import_writes_from_source_replacement(tmp_path) -> None:
    inputs = migration_inputs(tmp_path, replace_native=False)

    result = build_migration_plan(**inputs)

    assert result.import_plan.operations
    assert not result.source_replacement_plan.operations
    assert result.report.source_files_preserved


def test_replace_native_is_blocked_by_unsupported_fields(tmp_path) -> None:
    inputs = migration_inputs(
        tmp_path,
        replace_native=True,
        mapping_status="unsupported",
    )

    result = build_migration_plan(**inputs)

    assert result.blocking_conflicts
    assert result.source_replacement_plan is None


def test_apply_rejects_changed_source_hash(tmp_path) -> None:
    result = planned_migration(tmp_path)
    result.source_files[0].write_text("changed after preview", encoding="utf-8")

    with pytest.raises(SourceChangedError):
        apply_migration(result)
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest tests/migration/test_planner.py tests/migration/test_apply.py -q`

Expected: FAIL because migration planning is absent.

- [ ] **Step 3: Compose two explicit transaction plans**

`MigrationPlanResult` contains:

- immutable inventory and classification hashes;
- `import_plan` for neutral content and selected target adapters;
- optional `source_replacement_plan` for legacy native paths;
- conflicts, warnings, sensitive skips, unsupported fields, and deduplications;
- expected doctor checks;
- a Markdown and JSON preview derived from the same model.

The import plan is always applied and verified first. Native replacement may
start only after a new source-hash check, successful doctor result, verified
backup, explicit `--replace-native`, and confirmation scoped to the listed
source paths.

- [ ] **Step 4: Define replacement behavior**

For each fully migrated native source:

- back it up inside the Plan 1 transaction backup;
- replace an entrypoint with a generated reference only when the target adapter
  needs it;
- otherwise represent removal as a Plan 1 `DeleteOperation` with the previewed
  source SHA-256 and `root_id="scope"`, and record restoration bytes in the
  journal;
- never remove an agent-owned directory wholesale;
- never delete or rewrite an adopted `already_neutral` source;
- never remove credentials, unsupported settings, or unrelated files;
- mark the replacement in the neutral manifest with original and replacement
  hashes.

On any failure, roll back the entire replacement scope. A successful import
with a failed replacement remains a valid neutral install, but the CLI exits
non-zero and reports that legacy sources were restored.

- [ ] **Step 5: Add CLI orchestration**

Supported sequence:

```text
agent-workflow migrate scan --targets claude codex --output inventory.json
agent-workflow migrate normalize --inventory inventory.json --output normalized.json
agent-workflow migrate classify-request --inventory inventory.json --output request.json
agent-workflow migrate validate-response --request request.json --response response.json
agent-workflow migrate plan --inventory inventory.json --normalized normalized.json --response response.json --output migration-plan.json
agent-workflow migrate apply --plan migration-plan.json
agent-workflow doctor
```

`migrate plan` may omit `--response` when inventory contains no ambiguous
artifacts. `migrate apply` prompts unless `--yes` is supplied; `--yes` is valid
only with an already materialized plan file and matching hashes.

- [ ] **Step 6: Test rollback and idempotence**

Run: `pytest tests/migration/test_planner.py tests/migration/test_apply.py tests/integration/test_migration_cli.py -q`

Expected: PASS, including injected failure after every planned write and
byte-for-byte restoration.

- [ ] **Step 7: Commit**

```bash
git add src/agent_workflow/migration src/agent_workflow/cli.py src/agent_workflow/doctor.py tests/migration tests/integration/test_migration_cli.py
git commit -m "feat: plan and apply reversible migrations"
```

### Task 7: Legacy Fixtures and End-to-End Migration Gate

**Files:**
- Create: `tests/fixtures/legacy/claude-only/`
- Create: `tests/fixtures/legacy/codex-only/`
- Create: `tests/fixtures/legacy/mixed/`
- Create: `tests/fixtures/legacy/conflicts/`
- Create: `tests/fixtures/legacy/current-repository/`
- Create: `tests/golden/migration/`
- Create: `tests/integration/test_migration_golden.py`
- Create: `docs/migration.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Validates: sanitized fixture generated from the repository's pre-unification `home-claude/`
- Validates: deterministic plan/report/tree across operating systems
- Documents: recovery and manual handling for skipped native state

- [ ] **Step 1: Build sanitized fixtures with explicit provenance**

The current-repository fixture must copy the structure and non-secret content
of:

- `home-claude/CLAUDE.md.example`;
- `home-claude/commands/*.md`;
- `home-claude/agents/*.md`;
- `home-claude/workitems-rendering.md`;
- a sanitized `settings.json.example`;
- `statusline.js` as an unsupported Claude-native asset.

Add `SOURCE.md` with the original repository-relative paths and fixture
sanitization rules. Tests must fail if credential-like values enter any
fixture.

- [ ] **Step 2: Add the end-to-end golden test**

```python
# tests/integration/test_migration_golden.py
@pytest.mark.parametrize(
    "fixture_name",
    ["claude-only", "codex-only", "mixed", "conflicts", "current-repository"],
)
def test_migration_fixture_matches_golden_tree(
    fixture_name: str,
    tmp_path: Path,
) -> None:
    host = materialize_legacy_fixture(fixture_name, tmp_path)
    result = run_fixture_migration(host)

    assert result.preview == golden_text(fixture_name, "preview.md")
    assert tree_snapshot(host.install_root) == golden_json(fixture_name, "tree.json")
    assert run_doctor(host.install_root) == ()
```

- [ ] **Step 3: Generate goldens only through the tested manager**

Use a test helper with explicit `--update-goldens`; do not hand-edit snapshots.
Review the resulting preview for:

- canonical common rules and overlays;
- one skill per migrated command;
- manual memory provenance;
- native auto-memory only in cache;
- unsupported status-line and settings state preserved;
- no secrets or machine-specific absolute paths;
- stable target ordering.

- [ ] **Step 4: Write migration documentation**

`docs/migration.md` must cover:

- global versus project scope;
- installed-agent detection and target selection;
- deterministic versus LLM-assisted artifacts;
- exactly what leaves the machine for semantic classification;
- preview, backup, apply, replacement, rollback, and doctor;
- command/skill conversion;
- manual memory versus native auto-memory;
- supported, partial, manual, unsupported, and sensitive-skip mapping states;
- how to retry after source drift;
- how to keep the old native setup indefinitely.

- [ ] **Step 5: Add the fixture suite to all CI operating systems**

Run locally:

`pytest tests/migration tests/integration/test_migration_golden.py -q`

Expected: PASS.

Run full:

`pytest -q`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/legacy tests/golden/migration tests/integration/test_migration_golden.py docs/migration.md .github/workflows/ci.yml
git commit -m "test: cover legacy setup migrations"
```

## Plan 3 Completion Gate

- Every supported legacy root is inventoried read-only and deterministically.
- Classification requests contain no credentials, absolute paths, or blocked sensitive artifacts.
- An LLM can select only a closed semantic decision; Python selects destinations.
- Standard skills, commands, memory, and sessions normalize predictably.
- Native settings mappings distinguish exact, partial, manual, unsupported, and sensitive-skip states.
- Import and native replacement are separate journaled transactions.
- Stale sources, unresolved conflicts, failed backups, and unsupported replacement block writes.
- Claude-only, Codex-only, mixed, conflicting, and current-repository fixtures pass on Windows, macOS, and Linux.
- Full `pytest -q` and `git diff --check` pass before Plan 4 starts.
