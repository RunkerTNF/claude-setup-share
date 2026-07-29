# Универсальная настройка Agent Workflow

Этот репозиторий — одноразовый bootstrap. После global setup manager, общие
правила, manual memory и portable skills живут в `~/.agents/`, а native files
Claude Code и Codex только ссылаются на нейтральное ядро. Checkout после
проверки можно удалить.

Нужны Python 3.11+ и скачанный checkout. Setup не использует сеть и не
исполняет внешний Python adapter без явного trust.

## Быстрый запуск

Из корня checkout:

```text
python scripts/bootstrap.py --target claude --target codex
```

Команда показывает detection и полный setup preview, но ничего не меняет.
После проверки примените тот же выбор:

```text
python scripts/bootstrap.py --target claude --target codex --apply
```

Без `--yes` будет отдельное подтверждение. Проверка:

```text
python ~/.agents/workflow/agent-workflow.pyz doctor --scope global
```

Для проекта после global setup:

```text
python ~/.agents/workflow/agent-workflow.pyz setup preview --scope project --project PROJECT --profile split --target claude --target codex --output project-plan.json
python ~/.agents/workflow/agent-workflow.pyz setup apply --plan project-plan.json
```

Profiles: `local` — всё локально; `shared` — workflow можно коммитить;
`split` — rules/project skills общие, memory/sessions/overlays локальные.

Обычный shipped skill можно явно убрать через `--exclude-skill NAME`.
Claude statusline включается только через `--include-claude-statusline`.

## Инструкция для любого агентного LLM

Если пользователь дал ссылку или путь на этот репозиторий:

1. Проверь `python --version`; нужен Python 3.11+.
2. Запусти bootstrap без `--apply`.
3. Покажи detection и спроси, какие targets настраивать.
4. Спроси scope. Для project scope также спроси `local`, `shared` или `split`
   и нужно ли управлять `.syncprotect`.
5. Материализуй новый preview с выбранными параметрами. Покажи warnings,
   conflicts и точные write/delete operations.
6. Получи явное подтверждение именно показанного scope, targets, profile и
   plan. При изменении выбора создай новый preview.
7. Примени этот exact plan, запусти doctor и сообщи journal/rollback path.
8. Предложи fresh-session smoke для каждого выбранного агента.

Detection — не consent. Existing Claude Code, Codex и другие настройки нельзя
неявно перезаписывать или импортировать. Для legacy state используй
`agent-workflow-migrate` и [migration guide](docs/migration.md).

Credentials, cookies, tokens и private keys не копируются. External adapters
принимаются только из явно переданного `--adapter-dir`; `adapter.py` требует
отдельного `--trust-adapter-code ID`.

После успешной global-установки остаются:

- manager: `~/.agents/workflow/agent-workflow.pyz`;
- manifest: `~/.agents/manifest.json`;
- skills: `~/.agents/skills/`;
- journals/backups: `~/.agents/workflow/journals/` и `backups/`.

Если `agent-workflow` не найден на `PATH`, вызывай manager через Python.
Подробные fresh, project, migration и reconfigure flows:
[INSTALL.md](INSTALL.md).
