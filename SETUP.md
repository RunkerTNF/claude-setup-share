# Универсальная настройка agent workflow

Репозиторий нужен только как одноразовый bootstrap-источник. После глобальной
установки менеджер, общие правила, память и portable skills живут в нейтральной
директории `.agents`, а нативные файлы выбранных агентов генерируются как
тонкие entrypoints или wrapper'ы.

Нужны Python 3.11+, clone/download этого репозитория и хотя бы один
поддерживаемый или обнаруживаемый агент. Установка не использует сеть и не
исполняет код внешнего адаптера без явного доверия.

## Быстрый запуск

Из корня скачанного репозитория:

```text
python scripts/bootstrap.py
```

Команда сначала показывает обнаруженные агенты и полный setup-plan, но ничего
не меняет. Пользователь выбирает scope (`global` или `project`) и target
agents. Для project scope также выбирается профиль `local`, `shared` или
`split`. После проверки примените тот же выбор:

```text
python scripts/bootstrap.py --target codex --target claude --apply
```

Без `--yes` перед записью будет отдельное подтверждение. Для проекта укажите
корень и профиль:

```text
python scripts/bootstrap.py --scope project --project-root PATH --profile split
```

Профили:

- `local` — все workflow-файлы проекта остаются локальными;
- `shared` — правила, память, сессии и skills можно хранить в репозитории;
- `split` — общими остаются правила и skills, а память, сессии и overlays
  игнорируются.

Существующие Claude Code, Codex и другие настройки не являются целями для
неявной перезаписи. Они сначала инвентаризируются как кандидаты на migration;
исходники сохраняются, а замена нативных entrypoints требует отдельного
preview и подтверждения. Токены, пароли, cookies, ключи и другие credentials
никогда не копируются.

## Инструкция для любого агентного LLM

Если пользователь дал ссылку или путь на этот репозиторий:

1. Проверь Python командой `python --version`; нужен Python 3.11+.
2. Запусти `python scripts/bootstrap.py` без `--apply`.
3. Покажи пользователю обнаруженные targets и попроси выбрать агентов.
4. Для project scope попроси выбрать `local`, `shared` или `split`, а также
   нужно ли управлять `.syncprotect`.
5. Перезапусти preview с выбранными параметрами и покажи warnings, conflicts
   и точный список операций.
6. Получи явное подтверждение именно показанного scope, targets и списка
   операций. Любое изменение выбора требует нового preview.
7. Запусти ту же команду с `--apply`, затем проверь результат через
   `agent-workflow doctor --scope global` или, из проекта,
   `agent-workflow doctor --scope project`.
8. Сообщи, какие smoke-проверки надо выполнить в новой сессии каждого агента.

Внешние адаптеры принимаются только из явно переданного `--adapter-dir`.
Python-код такого адаптера разрешается только отдельным
`--trust-adapter-code ID`. Не сканируй произвольные plugin/download директории
и ничего не скачивай во время setup.

После успешной глобальной установки checkout можно удалить. Постоянные
артефакты находятся здесь:

- менеджер: `~/.agents/workflow/agent-workflow.pyz`;
- manifest: `~/.agents/manifest.json`;
- portable skills: `~/.agents/skills/`;
- transaction journals и backups: `~/.agents/workflow/journals/` и
  `~/.agents/workflow/backups/`.

Если `agent-workflow` не найден на `PATH`, запускайте менеджер через Python:
`python ~/.agents/workflow/agent-workflow.pyz`. Project-настройки используют
этот установленный менеджер и глобальные canonical skills.
