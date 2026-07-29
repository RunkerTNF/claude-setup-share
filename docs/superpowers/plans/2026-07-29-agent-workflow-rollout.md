# Agent Workflow Rollout Index

This index decomposes the approved
[`2026-07-29-agent-agnostic-workflow-design.md`](../specs/2026-07-29-agent-agnostic-workflow-design.md)
into four independently testable implementation plans.

The working identifiers `agent-workflow`, `agent-workflow-setup`, and
`agent-workflow-migrate` are fixed as internal package, CLI, and skill IDs for
these plans. The public repository title may be changed later without changing
installed paths or serialized schemas.

## Execution Order

1. [`2026-07-29-agent-workflow-foundation.md`](2026-07-29-agent-workflow-foundation.md)
   builds the dependency-free Python package, neutral `.agents` layout,
   transaction engine, rollback, diagnostics, and cross-platform CI.
2. [`2026-07-29-agent-workflow-adapters-and-setup.md`](2026-07-29-agent-workflow-adapters-and-setup.md)
   adds the adapter contract, guaranteed Claude Code and Codex adapters,
   persistent zipapp installation, setup/configure orchestration, and golden
   outputs.
3. [`2026-07-29-agent-workflow-migration.md`](2026-07-29-agent-workflow-migration.md)
   adds safe inventory, redaction, deterministic normalization, LLM
   classification exchange, preview, native replacement, and legacy fixtures.
4. [`2026-07-29-agent-workflow-content-and-release.md`](2026-07-29-agent-workflow-content-and-release.md)
   ports the repository's existing commands and reviewer prompts to portable
   skills, rewrites the public documentation, removes the Claude-only layout,
   and closes the release gates.

## Dependency Contract

- Plan 1 owns core models, serialization, path safety, plans, transactions,
  manifests, and diagnostics.
- Plan 2 consumes Plan 1 without changing its serialized schema incompatibly.
- Plan 3 consumes Plan 1 transactions and Plan 2 adapter inventory/mappings.
- Plan 4 consumes the stable skill materializer and migration pipeline from
  Plans 2 and 3.

Any schema change after a downstream plan starts requires a schema-version
increment and compatibility test.

## Review Gates

Each plan must pass its focused test suite, the full suite, and `git diff
--check` before the next plan begins. Plans 2 through 4 also run the golden
tests produced by earlier plans.

The final stable release additionally requires the manual Claude Code and
Codex smoke checklist from Plan 4.
