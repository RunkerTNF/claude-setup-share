---
description: Scan sessions and memory for deferred todos, bugs, and follow-ups, then maintain a ranked backlog at .claude/sessions/_backlog.md
---

The user wants a single, ranked list of everything we meant to do but didn't — out-of-scope bugs, typo fixes, follow-ups from `Open threads`, idea-backlog items scattered across sessions and memory. Your job is to keep that list up to date incrementally.

## Output file

Everything lives in `.claude/sessions/_backlog.md`. It has exactly three top-level sections, in this order:

```markdown
# Project backlog

_Last updated: YYYY-MM-DD_

## Active

### [H] <short title>
- **Category:** bug | cleanup | docs | followup | idea | prompt-tuning
- **Source:** [filename.md#L44](.claude/sessions/filename.md#L44)
- **What:** one or two sentences — the actual thing to do
- **Why it matters:** one sentence explaining the chosen priority
- **id:** `kebab-case-stable-slug`

### [M] …

### [L] …

## Resolved

<items the user moved here by hand. Never write to this section — only read `id`s from it for dedup.>

## Processed sources

- `.claude/sessions/2026-04-13-gv-uivla-solo-navigator.md` — mtime `1776086405`
- `.claude/memory/navigator_v3_latent_bug.md` — mtime `1776086709`
- ...
```

Mtimes are stored as raw Unix epoch seconds (what `stat -c %Y` returns). No date conversion — keeps the permission surface minimal.

## Sources to scan

Сканируем три директории:

- `.claude/sessions/*.md`
- `.claude/memory/*.md`
- User-level memory for this project — compute the path from CWD. Claude Code stores project-scoped user memory under `~/.claude/projects/<encoded-cwd>/memory/`, where `<encoded-cwd>` is the absolute project path with the drive letter and every `/` or `\` encoded as a dash, prefixed by the drive letter's lowercase + `--` (e.g. `C:\Users\Runker\sync-projects\gigado-trace-service` → `c--Users-Runker-sync-projects-gigado-trace-service`). Run `pwd` and construct the path. If the directory does not exist, skip silently.

Извлекаем кандидатов двумя проходами — **оба прохода применяются к одному и тому же набору файлов** (не «fallback только если primary пуст»), чтобы частично-мигрированные session-ноты не теряли legacy-кандидатов из Decisions/Challenges при наличии нового `[backlog]` тега в Open threads.

### Primary pass — tag-based

Один вызов Grep-tool:

- `pattern`: `\[backlog(:[a-z-]+)?\]`
- `output_mode`: `content`
- `-n`: `true`
- `path` / `glob`: по очереди применить к каждой из трёх директорий (`glob: "*.md"`)

Каждый хит — кандидат. Категория парсится прямо из тега:

- пустой тег `[backlog]` → `followup`;
- `[backlog:<c>]` где `<c>` ∈ `{bug, cleanup, docs, followup, idea, prompt-tuning}` → как в теге;
- `[backlog:<c>]` с неизвестной категорией → `followup` + сохранить warning «unknown category `<c>` in <file>:<line>, treated as followup» для chat-отчёта.

Антимаркер `[no-backlog]` не матчится этим паттерном (после `[` идёт `n`, а не `b`), поэтому специальной обработки не требует — естественным образом выпадает из выдачи.

### Legacy fallback pass — natural-language markers

Для обратной совместимости со старыми session-нотами, написанными до конвенции тегов:

1. Grep-tool по той же выдаче директорий с расширенным `pattern`:
   `(отложен|out of scope|не чиним|typo|когда-нибудь|TODO|FIXME|стоит зафиксировать|не починили|fallback на|надо бы|когда руки дойдут)` (с флагом `-i: true`).
2. Для memory-файлов, чьё имя содержит `bug`, `latent`, `issue`, `todo` — дополнительно полный `Read` (один item per file, если тело само не перечисляет несколько).
3. Для session-нот `Open threads` секция — все буллеты внутри её диапазона являются кандидатами даже без маркера (старое поведение). Эту часть нельзя покрыть одним grep-ом: после primary/legacy grep-ов определить, в каких session-файлах были хиты в `Open threads`; для session-файлов, у которых в Open threads ни одного `[backlog...]` / `[no-backlog]`, сделать узкий Read этой секции. Это компромисс — но читаются только уже-«старые» ноты без ни одного тега, со временем выбирается в ноль.

### Merge

Результаты обоих проходов объединяются; при дубликате по `(file, line)` оставляется primary-кандидат (его категория — ground truth, см. правило 9 в `## Rules`).

Do **not** scan `src/**`, `git log`, or anything outside these three directories. The sessions already capture what matters; grepping code produces noise.

## Workflow

1. **Read the current backlog file.** If `.claude/sessions/_backlog.md` is missing, this is a first run — treat every source file as new.
2. **Build the list of source files** from the three directories above. Get all mtimes in a single call:

   ```
   stat -c '%Y %n' .claude/sessions/*.md .claude/memory/*.md
   ```

   Each line is `<epoch> <path>`. This is the only shell command the skill needs — no `for` loops, no `date`, no `printf`. The user-level memory dir is computed from CWD (see третий пункт списка в `## Sources to scan` выше); check with a single `test -d <computed-path>` and, if it exists, one more `stat` call with the right glob.
3. **Read `Processed sources`** from the existing file and build a map `path → mtime`.
4. **Decide what to (re)scan.** A file needs scanning if:
   - it isn't in the map, OR
   - its current mtime is newer than the stored one.
   If *every* session file in the map has an identical mtime (clone/checkout artifact on Windows), fall back to rescanning everything — dedup by `id` will handle duplicates.
5. **Extract candidates** from the files marked for scanning, двумя проходами (см. `## Sources to scan`):
   - **5a. Primary Grep** — один Grep-tool вызов с `pattern: '\[backlog(:[a-z-]+)?\]'`, `output_mode: content`, `-n: true`. Категория берётся из тега (правило 9). Для пустого `[backlog]` → `followup`. Для unknown-категории → `followup` + warning в накопленный список (выводится в chat-отчёт на шаге 10).
   - **5b. Legacy fallback Grep + Read** — отдельный Grep с `-i: true` и `pattern: '(отложен|out of scope|не чиним|typo|когда-нибудь|TODO|FIXME|стоит зафиксировать|не починили|fallback на|надо бы|когда руки дойдут)'`. Для memory-файлов с `bug|latent|issue|todo` в имени — полный Read. Для session-файлов, у которых в `## Open threads` секции нет ни одного `[backlog...]` и ни одного `[no-backlog]`, — узкий Read этой секции (все буллеты внутри — кандидаты).
   - **Merge** — дедуп по `(file, line)`; при совпадении побеждает кандидат из 5a.

   Для каждого кандидата записать:
   - short title (≤60 chars),
   - category,
   - absolute source link with a line number (`[fname.md#L44](.claude/sessions/fname.md#L44)`),
   - one-sentence `What`,
   - raw text snippet (kept in memory only, used for dedup heuristics).
6. **Read existing `id`s** from both `Active` and `Resolved` in the current file.
7. **Dedup and merge:**
   - For each candidate, generate a stable `id`: kebab-case of the short title, stripped of Russian diacritics and punctuation. Before finalizing, scan existing `id`s; if one of them clearly describes the same thing, reuse it instead of minting a new one. When in doubt, prefer reuse.
   - If the `id` already exists in `Resolved` → drop the candidate entirely.
   - If the `id` already exists in `Active` → update its `Source` (append the new link if different) and refresh `Why it matters` if there's new signal. Don't duplicate.
   - Otherwise → add it to the working `Active` set.
8. **Rank the full `Active` set** (existing + newly merged) into `[H]` / `[M]` / `[L]`:
   1. Explicit user signal («важно», «критично», «надо починить», «пользователь попросил») → at least `[M]`, usually `[H]`.
   2. Category weight (ties broken by): bug > followup > cleanup > docs > prompt-tuning > idea.
   3. Blast radius: touches shared code (`BaseNavigator`, factory, server, pipelines) → bump up; narrow flow → bump down.
   4. Recency & repetition: mentioned in multiple sessions or recent memory files → bump up.
   5. Uncertainty («надо посмотреть на прогонах», «если окажется») → default `[L]` until data exists.
   The `Why it matters` line must explicitly reference which criterion drove the rank, so the user can argue with it.
9. **Write back the file.** Overwrite `## Active` and `## Processed sources` entirely. Never touch `## Resolved`. Update `_Last updated_` to today's date (from the `currentDate` context in the system prompt — do not guess). Within `Active`, sort by `[H]` → `[M]` → `[L]`, and within each bucket keep the order stable across runs (alphabetize by `id` to avoid churn in diffs).
10. **Print the full active list in chat as regular markdown** (NOT wrapped in a ``` code fence — the chat renders markdown, and a code fence makes the whole list a horizontally-scrolling monospace box that cuts off long lines). Format is title-first with a metadata line under each item:

    First, a one-line header as regular text:

    > Scanned: N files (K new/changed, M skipped)  ·  +X new, ~Y re-ranked, ↔Z merged

    Then, for each priority that has items, a bold header line and the items — **no code fence around any of it**. Each item is two lines:

    > **[M]**
    >
    > **URL-input guard: Этап 2 — прогон на VPN и измерение**
    > followup  ·  `uivla-url-guard-run-on-vpn`  ·  [src](.claude/sessions/2026-04-15-uivla-micro-and-url-guard.md#L40)
    >
    > **Clicker UIVLA: снять безусловную debug-инструментацию**
    > cleanup  ·  `clicker-uivla-debug-strip`  ·  [src](.claude/sessions/2026-04-13-uivla-clicker-coords.md#L32)

    Rules for the chat output:
    - **No triple-backtick fence around the list.** Ever. The chat UI renders markdown — fenced text becomes a monospace scroll box, which is exactly what we're avoiding.
    - Priority section header is `**[H]**` / `**[M]**` / `**[L]**` on its own line (bold).
    - Item title line is **bold** (`**Title**`). It is NOT prefixed with the priority bracket — the section header already carries that.
    - Metadata line sits directly under the title (no indent, no bullet): `category  ·  \`id\`  ·  [src](link)`, joined by two-space-middot-two-space. Id is inline-code (single backticks) so the slug stands out. If an item has multiple sources, show the first one only.
    - Put a blank line between items so each two-line block reads as a unit.
    - Empty priority sections are omitted entirely (don't print `**[H]**` if there are no `[H]` items).
    - Do NOT paste the `What` / `Why it matters` bodies — they live in the file.
    - Header line rules: one sentence, plain text. Omit counters that are zero — e.g. if `~0 re-ranked, ↔0 merged`, drop both and just print `Scanned: N (K new, M skipped)  ·  +X new`. If there are zero new items AND zero re-ranks AND zero merges, finish the header with `·  no changes`.
    - Если primary pass (5a) накопил warnings про unknown category, перед `Scanned:` вывести дополнительную строку вида `> Unknown categories: <cat1> at <file:line>, <cat2> at <file:line>` (перечислить все, по одному хиту в строке). Каждый такой кандидат попал в бэклог как `followup` — пользователь может переименовать тег руками и пересканировать.

## Rules

1. **Stable `id`s are sacred.** If the user moves an item to `Resolved`, re-running the skill must never bring it back. When generating an id, always check existing ids first and reuse if the meaning matches. Prefer short, descriptive slugs over long ones.
2. **Never invent items.** Every backlog entry must point at a real line in a real file. If you can't cite a source, don't include it.
3. **Don't sanitize the language.** Russian is the native language of sessions and memory — keep Russian titles and `What` text as Russian when that's how the source wrote them. Don't translate.
4. **Don't touch `## Resolved`.** Read-only. Ever.
5. **One item per concrete action.** If a bullet in `Open threads` bundles three unrelated things, split it into three entries with three `id`s.
6. **Don't re-parse what you don't need.** The whole point of the `Processed sources` map is to avoid re-reading unchanged files. Honor it.
7. **Be honest about rank.** If you downgrade an existing item, say so in the chat report and update `Why it matters` to explain why.
8. **When in doubt about category, pick the most conservative** (cleanup over bug, idea over followup). The user can promote it manually. Применяется к legacy-fallback-кандидатам (5b) — tag-derived кандидаты идут мимо этого правила (см. 9).
9. **Tag is ground truth for category.** Для кандидатов из primary pass (5a) категория берётся из `[backlog:<category>]` как есть — без эвристик поверх текста. Unknown-категория → `followup` + warning в chat-отчёт. Правило 8 (conservative-guess) к ним не применяется.
