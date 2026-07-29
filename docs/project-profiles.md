# Project profiles

Profile определяет, какие project workflow files предназначены для sharing.
Он не меняет global `~/.agents` и не делает private data безопасной для commit
автоматически.

| Project artifact | `local` | `shared` | `split` | Ownership |
|---|---|---|---|---|
| `.agents/RULES.md`, `.agents/rules/` | ignored | tracked | tracked | canonical/user-authored |
| `.agents/memory/` | ignored | tracked | ignored | canonical/user-authored |
| `.agents/sessions/` | ignored | tracked | ignored | user-authored |
| `.agents/skills/` | ignored | tracked | tracked | canonical/user-authored |
| `.agents/overlays/` | ignored | tracked | ignored | agent-specific |
| `.agents/manifest.json` и managed runtime | ignored | tracked by policy | tracked by policy | generated |
| Claude project entrypoint | `CLAUDE.local.md`, ignored | `CLAUDE.md`, tracked | `CLAUDE.md`, tracked | generated |
| Codex project entrypoint | `AGENTS.override.md`, ignored | `AGENTS.md`, tracked | `AGENTS.md`, tracked | generated |

`tracked` здесь означает «profile не добавляет path в managed ignore block».
Перед commit всё равно проверьте repository policy и содержимое.

## `local`

Подходит для личного workflow в командном репозитории. Manager добавляет в
marked `.gitignore` block:

```text
.agents/
AGENTS.override.md
CLAUDE.local.md
```

Native shared entrypoints не создаются. Project state остаётся на машине.

## `shared`

Подходит, когда команда согласовала общий agent workflow. Managed ignore block
для workflow пуст. Rules, memory, sessions и project skills могут попасть в
version control, поэтому review private context обязателен.

Используйте shared только если команда принимает generated Claude/Codex
entrypoints и выбранный формат manual memory.

## `split`

Подходит для общих engineering rules и project skills при личной памяти и
session history. Manager игнорирует:

```text
.agents/memory/
.agents/sessions/
.agents/overlays/
AGENTS.override.md
CLAUDE.local.md
```

Canonical `RULES.md`, `rules/`, project skills и shared native entrypoints
остаются доступными для tracking.

## `.gitignore` и `.syncprotect`

Manager изменяет только блок между:

```text
# BEGIN agent-workflow
# END agent-workflow
```

Unrelated content сохраняется. `.syncprotect` меняется только при явном
`--manage-syncprotect` или если файл уже существует. Git ignore и sync
protection — разные механизмы; настройте оба, если transfer tool не уважает
`.gitignore`.

Опциональный двухмашинный пример:
[`templates/examples/two-machine-workflow.md`](../templates/examples/two-machine-workflow.md).

## Смена profile

Создайте новый project preview с тем же project root и желаемым profile.
Проверьте изменения managed blocks и native entrypoints, затем примените exact
plan. Profile change не удаляет user-authored data; перед первым commit после
перехода на `shared` или `split` проверьте `git status` и credentials.
