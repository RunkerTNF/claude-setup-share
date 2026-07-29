---
name: backlog
description: Use when scanning neutral session notes and project memory for deferred work, refreshing the ranked project backlog, or showing active follow-ups, bugs, cleanup, docs, prompt tuning, and ideas.
---

# Refresh the Project Backlog

Maintain `.agents/sessions/_backlog.md` from only these canonical sources:

- `.agents/sessions/*.md`, excluding the backlog itself;
- `.agents/memory/**/*.md`.

Do not scan source code, git history, native agent state, or encoded working
directory memory caches.

## Backlog file model

Keep these top-level sections in this order:

1. `Active`: ranked items maintained by this skill.
2. `Resolved`: items maintained by the user; preserve this section byte for
   byte and use its IDs for deduplication.
3. `Processed sources`: source path plus the last observed `mtime` and content
   `hash`.

Each Active item contains a `[H]`, `[M]`, or `[L]` priority, title, Category,
Source with an exact file and line, What, Why it matters, and a stable `id`.
Never create an item without a real Source.

## Accepted backlog tags

The closed tag set is `[backlog]`, `[backlog:bug]`, `[backlog:cleanup]`,
`[backlog:docs]`, `[backlog:followup]`, `[backlog:idea]`,
`[backlog:prompt-tuning]`, and `[no-backlog]`.

`[backlog]` means `followup`. A known explicit category is ground truth. Treat
an unknown category as `followup` and report a warning. `[no-backlog]` excludes
the line.

## Incremental scan

1. Read the existing backlog, including every Active and Resolved stable `id`
   and the Processed sources map. On first run, start with empty sections.
2. Enumerate both canonical source trees and obtain each file's `mtime` and
   SHA-256 `hash` in as few read-only operations as the current agent
   supports.
3. Rescan a file when it is new, its mtime changed, or its hash changed.
   Rescan all sources if copied files have indistinguishable mtimes and hashes
   are unavailable.
4. Extract tagged candidates first. For untagged legacy notes, also recognize
   explicit TODO/FIXME or deferred-work language and every bullet in an
   untagged `Open threads` section.
5. Merge duplicate hits from the same source line, preferring the explicit
   tag category.

## Merge and rank

Generate a short kebab-case stable `id`, but reuse an existing ID whenever the
meaning matches. A Resolved ID must never return to Active. Merge an existing
Active ID by updating sources and evidence, not by duplicating it.

Rank the complete Active set:

- `[H]`: explicit urgency, a blocking bug, or broad shared impact;
- `[M]`: concrete follow-up with material value or repeated recent evidence;
- `[L]`: uncertain, narrow, speculative, documentation, tuning, or idea work
  without stronger user signal.

Use category, blast radius, recency, repetition, and uncertainty as tie
breakers. Explain the decisive signal in `Why it matters`. Within each bucket,
sort by `id` to avoid churn.

Rewrite only Active and Processed sources, update the last-updated date from
reliable session context, and preserve Resolved. Then show the full Active
list in regular markdown grouped by `[H]`, `[M]`, and `[L]`, with compact
category, ID, and source metadata.
