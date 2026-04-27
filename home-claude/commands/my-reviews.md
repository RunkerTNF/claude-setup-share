---
description: Дайджест GitLab MR'ов где ты reviewer. Аргумент — repo (default cwd) или `all`.
---

Команда показывает один или несколько reviews-блоков для конкретного репо.

## Парсинг аргумента

`$ARGUMENTS` может быть:

- **Пусто** → определи репо по `basename(cwd)` (запусти `pwd` через Bash). Проверь `~/sync-projects/<basename>/.sync-workitems/reviews/_changes_since_last.json`. Если есть — это default. Если нет — friendly error:
  ```
  _(cwd `<basename>` — не sync-project (нет `.sync-workitems/reviews/`). Передай `<repo>` или `all`. Доступны: <list>)_
  ```
  где `<list>` — repos у которых есть `~/sync-projects/<X>/.sync-workitems/reviews/` (через Glob `~/sync-projects/*/.sync-workitems/reviews/`, имена директорий извлекаются).

- **`<repo>`** (один словесный токен, не `all`) → проверь `~/sync-projects/<repo>/.sync-workitems/reviews/_changes_since_last.json`. Если нет — error с тем же listing'ом.

- **`all`** → перечисли все `~/sync-projects/*/.sync-workitems/reviews/`. Если ни один не найден → `_(ни в одном проекте нет данных kind=reviews)_`.

## Что делать после успешного резолва

1. **Прочитай shared rules:** `Read ~/.claude/workitems-rendering.md`.

2. **Для каждого выбранного репо:**
   - Прочитай `_meta.json` + `_changes_since_last.json` из `<repo>/.sync-workitems/reviews/`.
   - Рендери блок Level 1 — section header `## 🔍 reviews — <repo>`.
   - Без хвостовой строки `**Итого:**`.
   - Для inline-деталей читай `MR-<iid>.md` (frontmatter, `limit: 12`).

3. **Если репо несколько (case `all`)** — рендери блоки последовательно один за другим. Без `**Итого:**`.

## Follow-ups

При drill-in MR-id (например «MR-98» или «98») — рендери MR Level 2 из shared rules.
- Section-emoji в шапке = 🔍 (контекст /my-reviews).
- Markers 📥/📤 на комментах НЕ ставить (это для /feedback).

Меню «✍️ What next?» в конце Level 2:

```
- `дифф` / `дифф <pattern>` — встроить код
- `сделай ревью` — Claude разберёт дифф, предложит замечания и черновики комментов
- `<свободный вопрос>` — спрашивай по тексту/коду
```

Дальше:
- «дифф» / «дифф <X>» → Level 3 diff drill-in.
- «сделай ревью» → Level 3 сделай ревью.
- Свободный вопрос → отвечай опираясь на md+diff.

Если user сказал просто число «98» — трактуй как `MR-98` если он есть в текущем активном репо (или среди всех если контекст `all`).
