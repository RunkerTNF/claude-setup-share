# Установка и перенастройка Agent Workflow

Этот документ описывает fresh setup, project profiles, legacy migration,
добавление агента и восстановление. Короткая инструкция для первого запуска —
[SETUP.md](SETUP.md).

## Требования

- Python 3.11 или новее;
- скачанный checkout этого репозитория для первой global-установки или
  global-upgrade;
- Git repository для project scope;
- Claude Code и/или Codex, либо явно предоставленный внешний adapter.

Setup не требует сети. Node.js нужен только при явном включении опционального
Claude statusline.

В примерах `MANAGER` означает одну из команд:

```text
agent-workflow
python ~/.agents/workflow/agent-workflow.pyz
```

На Windows вместо `~` укажите фактический home path.

## Fresh global setup

Самый короткий human-led flow из checkout:

```text
python scripts/bootstrap.py --target claude --target codex
python scripts/bootstrap.py --target claude --target codex --apply
```

Первая команда выполняет `setup detect` и `setup preview`, записей не делает.
Вторая заново материализует preview и перед записью спрашивает подтверждение.
Для неинтерактивного уже подтверждённого запуска можно добавить `--yes`.

Эквивалентный явный manager flow:

```text
python -m agent_workflow setup detect --scope global --home HOME
python -m agent_workflow setup preview --scope global --home HOME --source-root CHECKOUT --target claude --target codex --output setup-plan.json
python -m agent_workflow setup apply --plan setup-plan.json
```

Запускайте `python -m agent_workflow` из checkout с `src` на `PYTHONPATH`.
Применяйте только тот plan, который был показан пользователю. После apply:

```text
python ~/.agents/workflow/agent-workflow.pyz doctor --scope global
```

Глобально по умолчанию устанавливаются management skills
`agent-workflow-setup`, `agent-workflow-migrate` и portable workflow skills.
Обычный skill можно исключить только явно:

```text
python scripts/bootstrap.py --target codex --exclude-skill morning
```

Management skills исключить нельзя. Исключение отображается в preview и
manifest. Ранее управляемый skill удаляется только при совпадении hash;
пользовательские изменения вызывают conflict.

Опциональный Claude statusline включается отдельно и не загружается Codex:

```text
python scripts/bootstrap.py --target claude --include-claude-statusline
```

Проверьте `src/agent_workflow/adapters/claude/templates/settings.example.json`
и вручную адаптируйте нативные settings; credentials там быть не должно.

## Agent-led setup

Если checkout передан агенту, попросите его прочитать [SETUP.md](SETUP.md).
Агент должен:

1. проверить Python;
2. выполнить read-only detection;
3. спросить scope, targets и для проекта profile;
4. показать warnings, conflicts и все операции preview;
5. получить явное подтверждение именно этого plan;
6. применить plan и запустить doctor;
7. предложить fresh-session smoke для каждого выбранного агента.

Detection не является согласием на настройку найденного агента.

## Настройка проекта

Сначала нужна успешная global-установка. Project setup использует
установленный manager и не зависит от bootstrap clone:

```text
python ~/.agents/workflow/agent-workflow.pyz setup detect --scope project --project PROJECT --profile split --home HOME
python ~/.agents/workflow/agent-workflow.pyz setup preview --scope project --project PROJECT --profile split --home HOME --target claude --target codex --output project-plan.json
python ~/.agents/workflow/agent-workflow.pyz setup apply --plan project-plan.json
python ~/.agents/workflow/agent-workflow.pyz doctor --scope project --cwd PROJECT --home HOME
```

Выберите один profile:

- `local` — `.agents/` и локальные native entrypoints добавляются в managed
  `.gitignore`;
- `shared` — project workflow и native shared entrypoints предназначены для
  version control;
- `split` — `.agents/RULES.md` и project skills можно делить, а
  `.agents/memory/`, `.agents/sessions/`, `.agents/overlays/` остаются
  локальными.

Добавьте `--manage-syncprotect`, только если текущий sync tool действительно
использует `.syncprotect`. Manager изменяет только свой marked block.
Подробности: [docs/project-profiles.md](docs/project-profiles.md).

Project setup не дублирует global skills. Project-scoped skills появляются,
только если пользователь добавил их в project `.agents/skills/` или импортировал
через migration.

## Migration Claude-only, Codex-only или mixed state

Fresh setup не трогает legacy files. После global setup используйте
`agent-workflow-migrate` или явный CLI flow:

```text
MANAGER migrate scan --scope global --targets claude codex --output inventory.json
MANAGER migrate normalize --inventory inventory.json --output normalized.json
MANAGER migrate classify-request --inventory inventory.json --output request.json
MANAGER migrate plan --scope global --targets claude codex --inventory inventory.json --normalized normalized.json --response response.json --imported-at TIMESTAMP --output migration-plan.json
MANAGER migrate report --plan migration-plan.json --output migration-preview.md
MANAGER migrate apply --plan migration-plan.json
```

`--response` нужен только при наличии ambiguous artifacts в request. Сначала
создайте его по закрытому classification contract и выполните
`migrate validate-response`.

По умолчанию migration сохраняет исходные `.claude`/`.codex` files. Нативная
замена — отдельный opt-in `--replace-native`. Полный процесс, privacy boundary
и mapping states: [docs/migration.md](docs/migration.md).

## Добавление агента и reconfigure

Для нового агента снова скачайте актуальный checkout и выполните global
`setup preview` с полным желаемым списком targets и `--source-root CHECKOUT`.
Не передавайте только новый target: preview должен отражать итоговую
конфигурацию.

Внешний declarative adapter:

```text
MANAGER setup preview --scope global --home HOME --source-root CHECKOUT --target existing --target new-agent --adapter-dir ADAPTERS --output setup-plan.json
```

Если package содержит `adapter.py`, добавьте
`--trust-adapter-code new-agent` только после review кода. Без trust такой
adapter блокируется и не исполняется.

Для изменения profile проекта создайте новый project preview с желаемым
profile. Для удаления optional skill используйте `--exclude-skill NAME`.
Любой unmanaged drift надо сначала разобрать вручную; не подменяйте hashes.

## Checkout можно удалить

После успешной global-установки и doctor bootstrap checkout можно удалить.
Остаются:

- `~/.agents/workflow/agent-workflow.pyz`;
- `~/.agents/manifest.json`;
- `~/.agents/skills/`;
- `~/.agents/workflow/journals/` и `backups/`;
- сгенерированные native entrypoints выбранных agents.

Checkout снова нужен только для global-upgrade/reconfigure на новую версию
поставляемого manager или skills. Project setup и migration работают без него.

## Restore и uninstall

Каждый apply печатает transaction journal. Для отката точной транзакции:

```text
MANAGER rollback JOURNAL_PATH
MANAGER doctor --scope global --home HOME
```

Rollback проверяет hashes и отказывается затирать последующие изменения.
Откатывайте связанные транзакции в обратном порядке.

Отдельной команды `uninstall` пока нет. Для полного удаления:

1. сохраните нужную ручную память и user-authored skills;
2. прочитайте manifest и journals;
3. откатите применённые setup/migration transactions в обратном порядке;
4. убедитесь, что native entrypoints больше не ссылаются на `.agents`;
5. удаляйте оставшиеся managed artifacts только после проверки ownership.

Никогда не удаляйте весь `.claude`, `.codex` или project root по manifest:
там могут быть пользовательские файлы, которыми manager не владеет.

## Если что-то не работает

Сначала запустите doctor, затем откройте
[docs/troubleshooting.md](docs/troubleshooting.md). Правила no-clobber,
backups и trust boundary описаны в [docs/safety.md](docs/safety.md).
