---
description: Дайджест Jira-тасок (последний sync task) — один блок, без итога.
---

Команда показывает один блок tasks-секции. Использовать когда не нужен полный `/morning`.

## Что делать

1. **Прочитай shared rules:** `Read ~/.claude/workitems-rendering.md`. Это твой источник истины по форматированию (эмодзи, типографика, edge-states, level-2 drill-in поведение).

2. **Прочитай данные:**
   - `~/sync-workitems/tasks/_meta.json`
   - `~/sync-workitems/tasks/_changes_since_last.json`

   Если `_meta.json` или `_changes_since_last.json` отсутствуют — рендери placeholder из shared rules (Empty/edge states).

3. **Рендери один блок tasks** по правилам Level 1 из shared rules.
   - Section header: `## 📋 tasks — global`
   - Без хвостовой строки `**Итого:**` (она только в `/morning`).
   - Для `status_changed`/`comments_added`/`diff_changed`/`updated` — title из `<KEY>.md` frontmatter (`Read` с `limit: 12`).

## Follow-ups

После того как пользователь увидит дайджест, он может:
- Назвать task-id (например «GIGADO-311» или «311») → рендери full body таски (Level 2 в shared rules).
- Спросить любой свободный вопрос про данные — отвечай опираясь на md/JSON, не выдумывай.

Если user сказал просто число «311» — найди подходящий KEY в листинге `~/sync-workitems/tasks/*.md` и трактуй как `GIGADO-<число>`.
