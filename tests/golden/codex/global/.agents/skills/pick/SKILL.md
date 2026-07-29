---
name: pick
description: Use when selecting one active project backlog item by exact ID or title fragment, loading its neutral session or memory context, and handing it to the current agent's available planning workflow.
---

# Pick a Backlog Item

Read `.agents/sessions/_backlog.md` without modifying it. Source context may
come only from `.agents/sessions/` or `.agents/memory/`.

## Resolve one item

Parse only the `Active` section and resolve the user's argument with this
cascade, stopping at the first stage that yields exactly one match:

1. exact `id` match, case-insensitive;
2. `id` substring match, case-insensitive;
3. title substring match, case-insensitive in any language.

For Zero matches, say that nothing matched and list every Active ID with its
title. For Multiple matches, list only the matching IDs and titles and ask for
an exact ID. Do not guess and do not start planning in either case.

## Load context and plan

For exactly one match:

1. Show a compact confirmation with ID, title, priority, category, What, Why
   it matters, and every Source.
2. Read the cited section around each Source. Read a short memory source in
   full when necessary. Treat the cited line as authoritative; do not replace
   it with a repository-wide keyword search.
3. Ask the current agent to begin its available planning workflow using What,
   Why it matters, and the source context as the planning brief.

Agent-specific plan modes, commands, or skill invocations belong in overlays,
not in this portable skill. Never pick more than one item per invocation and
never move an item to Resolved automatically.
