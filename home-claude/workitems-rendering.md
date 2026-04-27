# Workitems rendering — shared rules

Этот файл подключают slash-команды `/morning`, `/tasks`, `/my-reviews`, `/feedback`. Содержит все правила формата вывода. Команды-файлы остаются короткими и делегируют сюда.

Ссылающиеся команды зовут это: `Read ~/.claude/workitems-rendering.md`.

## Tools quirks

**Glob на Windows-путях может вернуть `No files found` для multi-segment паттернов** вида `C:/Users/.../sync-projects/*/.sync-workitems/<kind>/_changes_since_last.json`, даже когда файлы существуют. Workaround — использовать `Bash ls` с тем же шаблоном (shell-glob отрабатывает корректно):

```
Bash: ls ~/sync-projects/*/.sync-workitems/<kind>/_changes_since_last.json
```

Вызов `Bash ls ...` — каноничный способ обхода для всех мест в этих правилах где иначе использовался бы Glob.

## Data layout на диске

**Tasks (Jira, глобально):** `~/sync-workitems/tasks/`
- `<KEY>.md` — per task (YAML frontmatter + `## Description` + `## Comments`)
- `_meta.json` — `{kind, source, username, last_fetched_at, previous_fetched_at, items_count}`
- `_changes_since_last.json` — `{fetched_at, previous_fetched_at, changes[]}`
- `_snapshot.json` — raw, internal (НЕ читай — не нужен для рендеринга)

**Reviews/Feedback (GitLab, per-project):** `~/sync-projects/<repo>/.sync-workitems/{reviews,feedback}/`
- Та же структура, но `MR-<iid>.md` + `MR-<iid>.diff` sidecar

## Change-kinds в `_changes_since_last.json`

Каждая запись в `changes[]`:
- `new` — `{kind:'new', id, summary, [author]}` — author только для PR-kinds (reviews/feedback)
- `closed` — `{kind:'closed', id, summary}`
- `status_changed` — `{kind:'status_changed', id, from, to}`
- `comments_added` — `{kind:'comments_added', id, new_count, authors[], previews[{author, body_preview}]}` (body_preview обрезан до 200 символов на сервере)
- `diff_changed` — `{kind:'diff_changed', id}` (только PR-kinds)
- `comment_resolved` — `{kind:'comment_resolved', id, count, discussion_ids[]}` (только PR-kinds; фиксирует переход тредов в `resolved=true` со времени прошлого fetch'а)
- `updated` — `{kind:'updated', id, fields_changed[]}` (fields_changed сейчас всегда `[]`)

Для `status_changed`/`comments_added`/`diff_changed`/`updated` в change-record нет `<title>` — читай из `<id>.md` (YAML frontmatter, поле `title:`). Используй `Read` с `limit: 12` чтобы взять только frontmatter без description.

## Level 1 — digest format

Каждый блок:

```
## <section-emoji> <kind> — <repo|global>
*last fetch: <YYYY-MM-DD HH:MM UTC>  (<N>h ago)*
*prev fetch: <YYYY-MM-DD HH:MM UTC>  (<N>h ago)*

[⚠️ data <N>h old — нужен `sync <kind>` на корп-стороне]   ← вставить если (now - last_fetched_at) > 24h

**<changes.length> changes:**

[per-change h3 блоки]

_Для полного тела — скажи id._   ← только если changes.length > 0
```

Если `previous_fetched_at` в `_meta.json` равен `null` — вторая мета-строка: `*prev fetch: (initial fetch — всё как new)*`.

Timestamp format: convert ISO timestamp в `YYYY-MM-DD HH:MM UTC`. Используй `(<N>h ago)` округлённое до целого часа; для < 1 часа — `(<M>m ago)`.

### Section emojis

- tasks → 📋
- reviews → 🔍
- feedback → 💌

### Per-change h3 блоки

Каждая запись change → один `### h3` заголовок:

| `kind` | h3 line | Доп. строки ПОСЛЕ заголовка |
|---|---|---|
| `new` | `### 🆕 new — **<id>** [<status-emoji> <status>] [by *<author>*] — "<summary>"` | (нет) |
| `closed` | `### ✅ closed — **<id>** [<status-emoji> <status>] — "<summary>"` | (нет) |
| `status_changed` | `### 🔄 status — **<id>** — "<title>"` | newline, потом `<from-emoji> <from>` → `<to-emoji> <to>` |
| `comments_added` | `### 💬 comments — **<id>** [<status-emoji> <status>] by *<authors[0]>*[, *<authors[1]>*, ...] — "<title>"` | newline, потом для каждого `previews[i]`: `- *<author>*: «<body_preview>»` |
| `diff_changed` | `### 📝 diff — **<id>** — "<title>"` | newline, потом `(.diff обновлён)` |
| `comment_resolved` | `### ✓ resolved — **<id>** — "<title>"` | newline, потом `(<count> тред<ов> закрыт<о>)` |
| `updated` | `### ✏️ updated — **<id>** [<status-emoji> <status>] — "<title>"` | (нет) |

`[by *<author>*]` для `new` — только если в change-record есть поле `author` (PR-kinds).

**Status в h3-заголовке** — `<status-emoji> <status>` (см. mapping ниже) показываем **только для tasks** во всех change-kinds кроме `diff_changed` (этого kind у tasks не бывает). Для `status_changed` рендерим `<from-emoji> <from> → <to-emoji> <to>` без code-fence'ов.

- Для tasks status берётся из frontmatter `<KEY>.md` (`Read` с `limit: 12`). Даже для `new`-kind таски нужно прочитать md, чтобы достать status.
- Для PR-kinds (reviews/feedback) статус в h3 **не показываем** — для `new` он тривиально `opened`, для остальных kinds либо подразумевается, либо уже в transition.

### Status-emoji mapping

**Jira tasks:**

| Status | Эмодзи |
|---|---|
| `Open` / `To Do` / `Selected for Development` | 🟡 |
| `In Progress` / `In Review` (active dev) | 🟢 |
| `Backlog` | ⚪ |
| `Done` / `Resolved` | ✅ |
| `Closed` | ⚫ |
| `Blocked` / `On Hold` / `Cancelled` | 🔴 |
| (неизвестный/новый) | ⬛ |

**GitLab MRs:**

| Status | Эмодзи |
|---|---|
| `opened` | 🟢 |
| `merged` | 🟣 |
| `closed` | 🔴 |
| `locked` | 🔒 |

Если статус в данных не совпадает с этой таблицей буква-в-букву (например русский Jira-flow `«В работе»` или кастомный workflow) — сопоставь по смыслу: «active dev» → 🟢, «queued» → 🟡, «parked» → ⚪, «done» → ✅, «blocked» → 🔴. Если совсем не понятно — ⬛ + текст как есть.

Пример tasks-блока:

```
### 🆕 new — **GIGADO-309** 🟡 Open — "Вынести все промпты из файлов в бд"
### 🆕 new — **GIGADO-311** 🟢 In Progress — "Интеграция новой модели 9B в агента и запуск бенчей на ней"
### 🆕 new — **GIGADO-171** ⚪ Backlog — "Рефакторинг репозитория с кодом агента"
```

Пример status_changed:

```
### 🔄 status — **GIGADO-309** — "Вынести все промпты из файлов в бд"
🟡 Open → 🟢 In Progress
```

### Форматирование

- `**bold**` — id-токены (`**GIGADO-311**`, `**MR-98**`). Tasks — id напрямую (`change.id` уже как `GIGADO-XXX`); MRs — префиксуй `MR-` (`change.id` числовой `98` → `MR-98`).
- `*italic*` — никнеймы авторов (`*adbdoyan*`).
- `` `code` `` — значения статусов (`Open`, `In Progress`, `merged`, `opened`, etc.).
- `"кавычки"` — title (без эмфазы).
- «угловые кавычки» — `body_preview` бодей комментов.
- Между h3 блоками оставляй пустую строку.

### Empty/edge states

- `_meta.json` отсутствует → `_(нет данных — на корп-стороне ещё не было `sync <kind>`)_`
- `_changes_since_last.json` есть, `changes[]` пуст → `_No changes since last fetch._` (хвостовую подсказку НЕ печатай)
- `previous_fetched_at: null` → мета-строка `*prev fetch: (initial fetch — всё как new)*`

## Level 2 — full body одной таски

Триггер: пользователь упоминает task-id (например «GIGADO-311» или «311») в follow-up сообщении после `/morning` или `/tasks`. Читай `<KEY>.md`, парси YAML frontmatter и body, рендери:

```
# 📋 <KEY>
## <title>

**Status:** `<status>`  ·  **Created:** <YYYY-MM-DD>  ·  **Updated:** <YYYY-MM-DD>

## 📄 Description

<description, нормализованный — см. Jira normalization>

## 💬 Comments (<N>)

### *<comment.author>* — <comment.timestamp>

<comment.body, нормализованный>

[следующий коммент...]
```

Date в meta-строке: только `YYYY-MM-DD` (без time). `<comment.timestamp>` — берём как есть из md (там уже `YYYY-MM-DD HH:MM UTC`).

### Jira normalization (для description и comment.body)

`.md` рендерятся сервером сырьём из Jira API; в них остаётся wiki-разметка Jira. Применяй при выводе:

| В исходнике | В output |
|---|---|
| `[https://gitlab/.../path/to/file.py?...#L42]` | `[file.py#L42](full-url)` |
| `[https://gitlab/.../path/to/file.py?...]` (без anchor) | `[file.py](full-url)` |
| `[https://other-host/...]` (не gitlab) | `<full-url>` (auto-link) |
| `[label\|url]` (Jira pipe-syntax) | `[label](url)` |
| `{{X}}` | `` `X` `` |

Bare URLs без скобок — оставляй как есть, чат сам auto-link'ает.

Параграфы (двойные `\n`) сохраняй как пустые строки. Не реформатируй списки/структуру.

### Edge cases

- `description` пуст → `_(описание не заполнено)_`
- Ноль комментов → `## 💬 Comments (0)` + `_(пока нет комментариев)_`
- Неизвестный id → `_(не нашёл <id>. Доступны: <list of KEYs>)_` (KEYs — глобальный listing `~/sync-workitems/tasks/*.md`)
- Несколько id в одном сообщении → рендерь последовательно через `---` separator

## Level 2 — full body одной MR

Триггер: упоминание MR-id (например «MR-98» или «98») в follow-up. Layout одинаковый для review и feedback, отличаются section-emoji в шапке и меню «✍️ What next?».

Если контекст drill-in очевиден из ранее вызванной команды — используй её section-emoji (🔍 для `/my-reviews`, 💌 для `/feedback`). Если контекст неочевиден (например после `/morning`) — определяй kind по тому где этот MR-iid лежит на диске:

- Если `~/sync-projects/<repo>/.sync-workitems/reviews/MR-<iid>.md` существует → 🔍.
- Если в `feedback/` → 💌.
- Если в обоих (одна и та же MR одновременно у тебя и review, и feedback — крайний случай) → 🔍 (приоритет review).

```
# <section-emoji> MR-<iid>
## <title>

**Status:** `<status>`  ·  **Author:** *<author>*  ·  **Branch:** `<source_branch>` → `<target_branch>`
**Created:** <YYYY-MM-DD>  ·  **Updated:** <YYYY-MM-DD>

## 🧠 In short

<2–4 предложения от тебя: что MR меняет по сути, синтез из .diff + description>

## 📄 Description

<description из md, нормализованный — те же Jira-правила>

## 📂 Files changed (<N>)

| File | Δ |
|---|---|
| `<path>` | +X −Y |
| ... | ... |
| **Total** | **+X −Y** |

_Скажи `дифф` (все) или `дифф <glob или fragment>` (конкретные файлы) — встрою как code-блоки._

## 💬 Comments (<N>)

### [<маркер>] *<author>* — <timestamp>  [· 📍 <path>:L<line>]  [· ✓ resolved | 🔓 unresolved]

<body, нормализованный>

> **<reply.author> — <reply.timestamp>**
> <reply.body>

[следующий тред...]

## ✍️ What next?

<меню — зависит от kind, см. ниже>
```

`<маркер>` — только в `/feedback`-контексте:
- `comment.author == _meta.username` → `📤`
- `comment.author != _meta.username` → `📥`

В `/my-reviews`-контексте (или drill-in после `/morning` для review-MR) маркеры не печатай — секция выглядит как `### *<author>* — <timestamp>`.

**Threading и якоря в md уже отрендерены сервером.** В `MR-<iid>.md`:
- `### …` (h3) = корень треда. После timestamp могут идти сегменты `· 📍 <path>:L<line>` (точная привязка к строке кода, `(removed)` для удалённой строки, `(image)` для image-position) и `· ✓ resolved` / `· 🔓 unresolved` (для resolvable-тредов).
- `> **author — ts**` blockquote-блоки = ответы внутри треда (вложенные через `discussion_id`).

При выводе **используй уже готовые** `📍`/`✓`/`🔓` сегменты как есть — не выдумывай и не пересчитывай. Сам анкор тоже не дописывай: если в md его нет (regular MR-level коммент или комменты от старого CLI без `discussion_id`) — рендери секцию без анкорной строки. Пустая «эвристика» удалена; либо у нас есть точная привязка от GitLab, либо мы не привязываем.

### Diff stats из `MR-<iid>.diff`

`.diff` — стандартный unified diff с `diff --git a/<path> b/<path>` хедерами. Алгоритм счётчика:

- `<N>` файлов = количество строк начинающихся с `^diff --git`.
- Путь файла = `<path>` из `b/<path>` (post-image). Если `+++ /dev/null` (файл удалён) → берём из `a/<path>`.
- Per-file `+X` = строк начинающихся с `+`, **исключая** строки начинающиеся с `+++`.
- Per-file `−Y` = строк начинающихся с `-`, **исключая** `---`.
- `**Total**` row = сумма по всем файлам.

### Меню «✍️ What next?»

Зависит от вызывающей команды:

**Для `/my-reviews` или drill-in после `/morning` где MR это review:**

```
- `дифф` / `дифф <pattern>` — встроить код
- `сделай ревью` — Claude разберёт дифф, предложит замечания и черновики комментов
- `<свободный вопрос>` — спрашивай по тексту/коду
```

**Для `/feedback` или drill-in после `/morning` где MR это feedback:**

```
- `дифф` / `дифф <pattern>` — встроить код
- `подготовь ответы` — Claude по каждому 📥-треду предложит:
   • интерпретацию замечания
   • suggested code fix (```diff блок)
   • draft reply на русском для копипаста в GitLab
- `ответь на тред #N` / `только патчи` / `только тексты` — фокусированные варианты
- `<свободный вопрос>`
```

## Level 3 — diff drill-in

Триггер: «дифф» или «дифф <pattern>» follow-up после level-2 MR.

1. Читай `MR-<iid>.diff` целиком (он может быть большим — 1000+ строк, это норма).
2. Парси на per-file блоки: split по `^diff --git` (каждый блок начинается со строки `diff --git`).
3. Если есть `<pattern>`: фильтруй блоки где `<path>` (post-image) матчится case-insensitive substring или glob.
4. Для каждого выбранного блока:

````
### 📂 `<path>`

```diff
<полное содержимое блока, включая @@ headers>
```
````

5. Если `<pattern>` ничего не выбрал → `_(не нашёл по `<pattern>`. Доступные пути: <list>)_` где list — все `<path>` из этого MR.

Цветовая подсветка `+`/`−` строк в `` ```diff ``-блоках **зависит от UI** — в некоторых конфигурациях Claude Code chat она не применяется (текст рендерится моноширинным, но монохромным). Не полагаемся на цвет: `+`/`−`-префиксы в начале каждой строки unified-diff'а достаточны для eye-scan'а изменений. Тег `diff` всё равно ставим — это семантически корректное обозначение содержимого, на ряде renderer'ов цвета будут.

**Важно: содержимое блока — буква-в-букву как в `.diff`-файле.** Никаких ручных сокращений, переносов длинных строк, замены `...`-многоточием, или склейки многострочных конструкций в одну. Если awk/sed-извлечение даёт какой-то текст — печатай его как есть. Иначе теряются строки кода и пользователь видит мусор.

## Level 3 — `сделай ревью` (для /my-reviews)

Триггер: «сделай ревью» (или с уточнением «сделай ревью особо смотри на X») follow-up после level-2 для review-MR.

Прочитай весь `.diff`, description (уже знаешь из level 2), comments. Возврати:

````
## 🧐 Мои наблюдения по MR-<iid>

### ✅ Что выглядит хорошо
- <bullet с конкретикой по файлу/функции>

### 🤔 Стоит обсудить
- **`<path>`** в районе `<функция или конструкция>`: <что показалось странным>
  ```<lang>
  # было
  <фрагмент>
  # стало
  <фрагмент>
  ```

### 🚨 Возможные баги
- <bullet>

### 💬 Готовые комменты для треда

> _Можешь скопировать в GitLab:_
> «<готовый коммент на русском, конкретный — цитируй файл/строку/функцию>»

[следующий черновик...]
````

`<lang>` — language tag для подсветки по расширению файла (`python`, `typescript`, `yaml`, etc.). Для diff-фрагментов — `diff`.

Тон комментов: actionable, конкретные, по-русски, без снисхождения. Цитируй файл/функцию/строку. Никаких generic «consider improving readability».

## Level 3 — `подготовь ответы` (для /feedback)

Триггер: «подготовь ответы» / «ответь на тред #N» / «только патчи» / «только тексты» follow-up после level-2 для feedback-MR.

Алгоритм:
1. Прочитай весь `.diff`, comments.
2. Треды уже сгруппированы в md по `discussion_id`: каждый h3-блок (`### …`) = корень одного треда, blockquote-блоки `> **author — ts**` под ним = ответы. Проходи по h3-блокам в порядке, в котором они в md.
3. Для каждого треда определи «незакрытость»:
   - Если на корне есть маркер `· ✓ resolved` → закрыт, ответ не нужен (skip).
   - Если на корне есть маркер `· 🔓 unresolved` → open, нужен ответ.
   - Если маркера нет (regular MR-level коммент: `resolvable: false`) → fallback на старое правило: тред считается open, если последний коммент в нём (либо корень, либо последний reply) НЕ от `_meta.username`.
4. Для каждой open-группы (это и есть «тред») возврати:

````
### 📥 Тред #<N> — *<initiating-author>* — <короткая тема, ~5 слов>

**Коммент:**
> «<comment.body>»

**Интерпретация.** <как ты понял замечание, 1-2 предложения>

**Suggested code fix** (`<path>`):

```diff
@@ -<line>,<count> +<line>,<count> @@ <context>
- <старая строка>
+ <новая строка>
```

**Draft reply:**
> <русский текст ответа>

[если уместно — варианты А (согласие)/Б (пушбэк)]
````

«Тред #<N>» нумеруй с 1, по порядку.

Подопции:
- `ответь на тред #N` → только эта группа.
- `только патчи` → пропусти `Draft reply` блоки.
- `только тексты` → пропусти `Suggested code fix` блоки.

Если `Suggested code fix` не применим (например коммент это вопрос «зачем ты это сделал?» а не указание на баг) — пропусти этот блок и оставь только Draft reply.