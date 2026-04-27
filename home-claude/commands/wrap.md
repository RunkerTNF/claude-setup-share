---
description: Write an end-of-session note to .claude/sessions/ summarizing what was done, decisions, challenges, and open threads
---

The user is wrapping up this session. Write a session note to `.claude/sessions/YYYY-MM-DD-<slug>.md` where:

- `YYYY-MM-DD` is today's date (from the `currentDate` context in the system prompt — do not guess).
- `<slug>` is a short kebab-case description of the main topic of the session (e.g. `memory-reorganization`, `factory-refactor`, `navigator-v3-debug`). Pick it from what actually happened, not the first user message.

If a file for today with the same slug already exists, append a new section to it rather than overwriting — multiple sessions per day on different topics should get separate files, but resuming the same topic should extend the existing note.

## Template

Use exactly this structure. Omit a section only if it would be empty — do not write "N/A" placeholders.

```markdown
# <slug rewritten as a human title>

**Date:** YYYY-MM-DD

## Summary
1–3 sentences: what was this session about. One sentence is the default; multi-strand sessions can take two or three clauses if each carries real info (e.g. a measured latency, a discovered constraint).

## What changed
- Bulleted list of concrete changes (files touched, features added, bugs fixed). Link files with markdown relative paths, e.g. [src/server.py](src/server.py). Focus on *why* each change was made, since *what* is already in git.
- Do not list mechanical edits that the diff makes obvious on its own: new imports, `__init__.py` re-exports, trivial Literal additions. If the only thing you'd say is "added import X" or "exported Y" — drop the bullet.

## Decisions
- Architectural or design decisions made during the session. For each: the decision, the alternatives considered, and *why* this option won. This is the most important section — it's the content that doesn't live anywhere else.
- "Decisions not to do X" only count if either (a) the alternative was actively considered and rejected with reasoning, or (b) writing it down prevents a likely future "helpful" edit. Otherwise drop.

## Challenges / dead ends
- Things that didn't work and why. Approaches tried and abandoned. Bugs that took real time to diagnose. Future-you (or a teammate) will thank present-you for documenting the dead ends.
- **Not** for observed model/system behavior — that's an empirical finding, not a dead end. Put it in `Observed behavior` (below) or as an `Observed: …` bullet under `What changed` if it informs a specific edit.
- **Not** for trivial harness quirks (Edit-after-Write reload, slash-command not hot-reloading) once they're already captured in memory — no need to re-document each session.

## Observed behavior
- Optional. Empirical findings from running the code: latencies, model quirks confirmed/ruled out, edge cases seen on real traces. Only include if you actually ran something and saw something — do not pad with hypotheses.

## Open threads
- What's left undone, questions still open, follow-ups to think about next session. Each bullet gets `[backlog:<category>]` appended automatically (default `followup`) so `/backlog` can pick it up — override with `[backlog:bug]` / `[backlog:cleanup]` / `[backlog:docs]` / `[backlog:idea]` / `[backlog:prompt-tuning]`, or use `[no-backlog]` to opt a bullet out of the backlog entirely.

  **Do NOT put here:**
  - Actions already completed this session ("memory entry added", "stash popped") — that's `What changed`, not a thread.
  - One-shot admin chores (commit `.claude/`, mark backlog item Resolved) — either do them inline or push to `_backlog.md`; don't park them in session notes.
  - Meta-explanations of why something was *not* done.
  - Items already tracked in `_backlog.md` — do not duplicate.

  If after this filter the section is empty, omit it.
```

## Backlog tags

`/backlog` ищет отложенную работу по явному тегу в конце буллета. Грамматика:

- `[backlog]` — буллет уходит в бэклог с категорией по умолчанию (`followup`).
- `[backlog:<category>]` — категория из закрытого набора: `bug | cleanup | docs | followup | idea | prompt-tuning`.
- `[no-backlog]` — антимаркер; исключает буллет из бэклога. Имеет смысл только в `Open threads` (в `Decisions` / `Challenges / dead ends` авто-тегирования нет — `[no-backlog]` там no-op).

**Где ставить:**

- `## Open threads` — авто-тегирование. Когда пишешь ноту, каждому буллету, у которого ещё нет `[backlog...]` и нет `[no-backlog]`, допиши `[backlog:followup]`. Если из текста буллета очевидно, что категория другая, сразу ставь явный `[backlog:<category>]` — это перебивает дефолт.
- `## Decisions` и `## Challenges / dead ends` — **без** авто-тегирования. Тег ставится руками только на буллеты, которые действительно кодируют отложенную работу. Большинство строк в этих секциях — исторический контекст и в бэклог не идут.

**Примеры:**

- `Open threads` буллет, категория по умолчанию: `- Дождаться прогона миграции на VPN перед мержем. [backlog:followup]`
- `Open threads` буллет с явной категорией: `- Проверить дедупликацию ретраев в WSR. [backlog:bug]`
- `Open threads` буллет с doc-drift: `- Обновить CLAUDE.md после миграции b4c7d9e1f2a8 — known-limitation про blacklist больше не актуален. [backlog:docs]`
- `Open threads` буллет-не-defer: `- Отписаться Пете в чате про новый endpoint. [no-backlog]`
- `Decisions` буллет с признанным tech-debt: `- Оставили sticky-routing через crc32(run_id); альтернатива с shared-state сломала бы dev. [backlog:cleanup]`
- `Decisions` буллет без defer'а (тега нет): `- Выбрали Alembic вместо raw SQL — интеграция с FastAPI ровнее.`

## Rules

1. **Write from conversation context, not from re-reading the whole repo.** You already know what happened — don't go spelunking. One or two targeted `Read`s to double-check a file path is fine; a full re-exploration is not.
2. **Be honest about challenges.** If you went down a wrong path, got corrected by the user, or almost made a mistake — write it down. That's the highest-value content in these notes. Do not sanitize.
3. **Do not duplicate git.** "What changed" should give *context* for the diff, not reproduce it. If a change is self-explanatory from the filename, one line is enough.
4. **Promote durable decisions to memory.** After writing the session note, scan the Decisions section. For any decision that will still be relevant in *future* sessions (not just this one's context), also add a `project`-type memory to `.claude/memory/` and link it from `.claude/memory/MEMORY.md`. Session notes are a chronological archive; memory is what gets auto-loaded next time. If a decision only lives in the session note, it effectively doesn't exist for future-you.
5. **Report back concisely.** After writing the file, tell the user the path you wrote to and list any memory entries you added or updated. Do not paste the full note back — the user can open the file.
6. **Respect the backlog-tag grammar.** See `## Backlog tags` выше. В `## Open threads` каждому буллету без уже выставленного `[backlog...]` и без `[no-backlog]` допиши `[backlog:followup]` (или сразу явный `[backlog:<category>]`, если категория очевидна). В `## Decisions` и `## Challenges / dead ends` тег ставь только руками и только на буллеты, которые реально кодируют отложенную работу.
