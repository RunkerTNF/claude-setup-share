---
description: Pick an item from the project backlog by id or title fragment and start planning work on it in plan mode
---

The user wants to start work on a specific backlog item. Usage: `/pick <id-or-title-fragment>`. Your job is to resolve the argument to exactly one item in `.claude/sessions/_backlog.md`, brief yourself on the context, and enter plan mode to start the standard planning workflow on it.

## Workflow

1. **Read `.claude/sessions/_backlog.md`.** Parse the `## Active` section into a list of items. For each item, extract: priority (`[H]`/`[M]`/`[L]`), title, `Category`, `Source` links, `What`, `Why it matters`, `id`. Ignore `## Resolved` — the user wouldn't `/pick` something they've already resolved.

2. **Resolve the argument** to a single item using this cascade (stop at the first step that produces exactly one match):
   1. Exact `id` match (case-insensitive).
   2. `id` substring match (case-insensitive).
   3. Title substring match (case-insensitive, Russian and Latin both fine).

3. **Handle ambiguity honestly:**
   - **Zero matches:** Tell the user «ничего не нашёл по `<arg>`», then list all Active ids with titles (one per line, `id — title`) so they can retry. Stop — do not enter plan mode.
   - **Multiple matches:** Tell the user «совпало несколько», list the matched items (`id — title`), and ask them to be more specific by passing the exact id. Stop — do not enter plan mode.
   - **Exactly one match:** proceed to step 4.

4. **Brief yourself on the item.** Print the resolved item in chat as regular markdown (not in a code fence) so the user can confirm you picked the right one:

   > Picked: **`<id>`**
   >
   > **<title>**  —  `[<priority>]` · <category>
   >
   > **What:** <what>
   > **Why it matters:** <why>
   > **Source:** <source links, comma-separated if multiple>

5. **Pull context from the source file(s).** Open each source file referenced in the item and read the surrounding section (the `## Open threads` / `## Challenges` / `## Decisions` bullet plus one or two neighbouring bullets for context). If the source is a memory file, read the whole file — memory files are short. You're loading context for planning; do NOT edit anything in this step.

6. **Enter plan mode** by calling the `EnterPlanMode` tool. From that point, follow the standard plan workflow (Phase 1 exploration → Phase 2 design → Phase 3 review → Phase 4 final plan → Phase 5 ExitPlanMode). The initial task for the plan is the picked item's `What` + `Why it matters`, with the source links as starting points for exploration.

## Rules

1. **Never pick more than one item per invocation.** If the argument is ambiguous, ask the user to be specific — don't guess.
2. **Do not mutate the backlog file.** `/pick` is read-only on `_backlog.md`. Moving an item to `Resolved` is the user's job, and happens after the work is done, not at pick time.
3. **Do not enter plan mode on ambiguity.** Plan mode is for committed planning on a single, resolved item. If you're not sure which item the user meant, stop and ask.
4. **Respect the source link.** The backlog entry's `Source` points to a specific line in a specific file — that's the authoritative starting point for exploration, not a keyword search across the repo.
5. **Keep the chat brief before plan mode.** One "Picked: …" confirmation block and then straight into plan mode. Don't re-explain what the item is, don't list alternatives — the user already knows, they typed the id.
