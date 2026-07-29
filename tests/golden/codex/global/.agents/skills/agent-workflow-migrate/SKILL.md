---
name: agent-workflow-migrate
description: Use when converting an existing single-agent or mixed-agent setup into the portable agent workflow.
---

# Agent Workflow Migration

Use the installed workflow manager to migrate legacy rules, skills, commands,
memory, sessions, and native settings without silently changing or deleting
their sources.

Resolve the persistent manager in this order:

1. Use `agent-workflow` on `PATH` when available.
2. Otherwise run `~/.agents/workflow/agent-workflow.pyz` with Python 3.11 or
   newer.

Read [the classification contract](references/classification-contract.md)
completely before creating a semantic classification response. Read
[recovery](references/recovery.md) before applying a migration.

Follow this sequence:

1. Run a read-only inventory for the user-selected global or project scope.
2. Show artifact counts, inventory warnings, and sensitive skips.
3. Run deterministic normalization for portable artifacts.
4. Generate and inspect the redacted classification request. Stop if it
   contains credentials, private absolute paths, or artifacts not listed by
   the inventory.
5. Classify only the enumerated artifact IDs with the closed decision kinds in
   the contract. Python, not the agent, selects final destinations.
6. Run `migrate validate-response` and stop on any validation error.
7. Generate a preview and summarize every conflict, unsupported field,
   preserved source, and proposed native replacement.
8. Obtain explicit user confirmation before apply or native replacement.
   Confirmation must cover the exact previewed paths.
9. Run doctor after apply, then report the transaction journal plus every
   backup and rollback location.

The repository checkout may be deleted after a successful global installation.
The installed zipapp and `.agents/skills/agent-workflow-migrate/` are the
persistent tools. Never add a direct model-provider dependency: the current
agent reads the request and writes the response file.
