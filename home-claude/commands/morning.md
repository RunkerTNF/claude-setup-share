---
description: Утренний бриф по workitems — tasks, reviews, feedback в одном ответе.
---

Master-команда для разбора workitems-данных. Цель — за один вызов получить дайджест изменений с прошлого fetch'а по всем трём типам.

## Что делать

1. **Прочитай shared rules:** `Read ~/.claude/workitems-rendering.md`. Это твой источник истины по форматированию.

2. **Собери источники данных:**
   - **Tasks** (один источник): `~/sync-workitems/tasks/`
   - **Reviews** (несколько источников): пройди `Glob ~/sync-projects/*/.sync-workitems/reviews/_changes_since_last.json` — каждый match = отдельный блок per repo.
   - **Feedback** (несколько источников): то же для `feedback/`.

3. **Для каждого источника прочитай `_meta.json` + `_changes_since_last.json`.** Если `_meta.json` отсутствует — рендери placeholder из shared rules (`_(нет данных — на корп-стороне ещё не было `sync <kind>`)_`). Если файлы есть, но `changes[]` пуст — `_No changes since last fetch._`.

4. **Для inline-деталей** (`status_changed`/`comments_added`/`diff_changed`/`updated`) — title из соответствующего `<id>.md` (Read с `limit: 12`).

5. **Рендери три секции в порядке: tasks → reviews → feedback.**
   - Tasks: одна section `## 📋 tasks — global`.
   - Reviews: одна или несколько section'ов `## 🔍 reviews — <repo>` — по одной на репо у которого есть данные. Если ни в одном репо нет данных для kind=reviews — печатай ОДНУ секцию `## 🔍 reviews — _(нет данных)_` с placeholder.
   - Feedback: то же для feedback.

6. **Закрой ответ строкой:**

```
**Итого:** 📋 <N> tasks · 🔍 <M> reviews · 💌 <K> feedback.
```

где N/M/K — суммарное количество changes по соответствующим секциям.

## Follow-ups

После показа брифа пользователь может:
- Назвать task-id («GIGADO-311» или «311») → рендери full body таски (Level 2 в shared rules).
- Назвать MR-id («MR-98» или «98») → рендери MR Level 2. Какой kind (reviews/feedback) — определи по тому где этот MR-iid лежит на диске. Section-emoji 🔍 или 💌 соответственно. Меню «✍️ What next?» — соответствующее (см. shared rules).
- Сказать «дифф» или «дифф <pattern>» в контексте конкретного MR → Level 3 diff drill-in.
- Сказать «сделай ревью» — для review-MR → Level 3 сделай ревью.
- Сказать «подготовь ответы» — для feedback-MR → Level 3 подготовь ответы.
- Любой свободный вопрос — отвечай опираясь на данные.
