---
name: code-review
description: Use when critiquing a pending working-tree or staged diff, completed implementation slice, or code change before it is reported complete or integrated.
---

# Review Pending Code Changes

Read [the review contract](references/review-contract.md) completely before
reviewing.

The current agent performs the review by default. Delegate only when the user
explicitly requests delegation and the active agent supports it; any exact
delegation mechanism belongs in an agent overlay. The portable contract remains
the semantic source of truth.

Work read-only. Read the request and plan snapshot when present, then inspect
status, working-tree and staged diffs, `.agents/RULES.md`, applicable project
rules, and `.agents/memory/MEMORY.md` plus relevant indexed notes.

Return findings in the contract's format. Do not patch code, stage changes,
commit, run mutating commands, or manufacture issues for a trivial diff.
