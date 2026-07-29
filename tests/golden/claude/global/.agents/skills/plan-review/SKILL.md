---
name: plan-review
description: Use when critiquing an implementation plan, plan draft, or request-to-plan handoff for correctness, completeness, safety, convention compliance, and scope before implementation begins.
---

# Review an Implementation Plan

Read [the review contract](references/review-contract.md) completely before
reviewing.

The current agent performs the review by default. Delegate only when the user
explicitly requests delegation and the active agent supports it; any exact
delegation mechanism belongs in an agent overlay. The portable contract remains
the semantic source of truth.

Work read-only. Read the plan and original request first, then
`.agents/RULES.md`, the project rule files it names, and
`.agents/memory/MEMORY.md` plus only relevant indexed notes. Inspect referenced
code and configuration with read-only capabilities.

Return findings in the contract's format. Do not rewrite the plan, edit files,
run mutating commands, implement fixes, or manufacture issues for a trivial
plan.
