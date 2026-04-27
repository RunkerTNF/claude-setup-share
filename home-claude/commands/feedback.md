---
description: Дайджест GitLab MR'ов где ты автор (получаешь review). Аргумент — repo (default cwd) или `all`.
---

Команда показывает один или несколько feedback-блоков для конкретного репо.

## Парсинг аргумента

`$ARGUMENTS` может быть:

- **Пусто** → определи репо по `basename(cwd)`. Проверь `~/sync-projects/<basename>/.sync-workitems/feedback/_changes_since_last.json`. Если нет — friendly error:
  ```
  _(cwd `<basename>` — не sync-project (нет `.sync-workitems/feedback/`). Передай `<repo>` или `all`. Доступны: <list>)_
  ```
  где `<list>` — repos с `~/sync-projects/<X>/.sync-workitems/feedback/`.

- **`<repo>`** → проверь `~/sync-projects/<repo>/.sync-workitems/feedback/_changes_since_last.json`. Error с listing'ом если нет.

- **`all`** → перечисли все. Если ни одного → `_(ни в одном проекте нет данных kind=feedback)_`.

## Что делать после успешного резолва

1. **Прочитай shared rules:** `Read ~/.claude/workitems-rendering.md`.

2. **Для каждого выбранного репо:**
   - Прочитай `_meta.json` + `_changes_since_last.json` из `<repo>/.sync-workitems/feedback/`.
   - Рендери блок Level 1 — section header `## 💌 feedback — <repo>`.
   - Без `**Итого:**`.
   - Для inline-деталей читай `MR-<iid>.md` (frontmatter, `limit: 12`).

## Follow-ups

При drill-in MR-id («MR-119» или «119») — рендери MR Level 2 из shared rules.
- Section-emoji = 💌 (контекст /feedback).
- Markers 📥/📤 на комментах активны: сравни `comment.author` с `_meta.username` (из `_meta.json`):
  - `author == username` → `📤`
  - `author != username` → `📥`

Меню «✍️ What next?» в конце Level 2:

```
- `дифф` / `дифф <pattern>` — встроить код
- `подготовь ответы` — Claude по каждому 📥-треду предложит:
   • интерпретацию замечания
   • suggested code fix (```diff блок)
   • draft reply на русском для копипаста в GitLab
- `ответь на тред #N` / `только патчи` / `только тексты` — фокусированные варианты
- `<свободный вопрос>`
```

Дальше:
- «дифф» / «дифф <X>» → Level 3 diff drill-in.
- «подготовь ответы» → Level 3 подготовь ответы.
- «ответь на тред #N» → только эта группа.
- «только патчи» → пропусти Draft reply блоки.
- «только тексты» → пропусти Suggested code fix блоки.
- Свободный вопрос → отвечай опираясь на md+diff.
