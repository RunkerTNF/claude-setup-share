---
name: wrap
description: Use when ending or pausing a work session and recording what changed, decisions, observed behavior, dead ends, and genuinely open work for a later agent session.
---

# Wrap a Session

Write the note under `.agents/sessions/` in the selected project or global
scope. Use `.agents/memory/` for durable knowledge promoted from the note.

## Workflow

1. Take today's date from reliable session context; do not guess it.
2. Choose a short kebab-case slug that describes the work actually done.
3. Write `.agents/sessions/YYYY-MM-DD-<slug>.md`. If that topic already has a
   note today, append a clearly separated continuation instead of overwriting
   it.
4. Summarize from the conversation and work already performed. Use targeted
   file checks only when a path needs confirmation; do not rediscover the
   repository.
5. Add backlog tags to genuine deferred work according to the contract below.
6. Promote decisions that will matter in later sessions to a project note
   under `.agents/memory/` and link it from
   `.agents/memory/MEMORY.md`.
7. Report the note path and any memory entries added or updated. Do not paste
   the whole note into chat.

## Information model

Use these headings in order and omit only empty optional sections:

- `Summary`: one to three sentences describing the session.
- `What changed`: concrete outcomes and why they were needed; do not restate
  mechanical diff details.
- `Decisions`: the choice, alternatives considered, and why the choice won.
- `Challenges / dead ends`: meaningful failed approaches and their cause.
- `Observed behavior`: optional empirical findings from something actually
  run or inspected, not hypotheses.
- `Open threads`: unfinished work, unanswered questions, and future
  follow-ups.

Do not put completed actions, duplicate backlog items, meta-explanations, or
one-shot administrative chores in `Open threads`. Perform a small
administrative action now or record it directly in
`.agents/sessions/_backlog.md`.

## Emitted backlog tags

The closed tag set is `[backlog]`, `[backlog:bug]`, `[backlog:cleanup]`,
`[backlog:docs]`, `[backlog:followup]`, `[backlog:idea]`,
`[backlog:prompt-tuning]`, and `[no-backlog]`.

In `Open threads`, append `[backlog:followup]` when no marker exists, or choose
the more specific category when obvious. Use `[no-backlog]` to explicitly
exclude a bullet. In `Decisions` and `Challenges / dead ends`, add a backlog
tag only when the bullet itself contains a concrete deferred action.

Stable backlog IDs are assigned by the backlog skill, not by wrap.
