# Troubleshooting

Начинайте с exact command, scope и полного error text. Не исправляйте manifest,
plan или journal вручную.

## Python или manager не запускается

Проверьте:

```text
python --version
python ~/.agents/workflow/agent-workflow.pyz --version
```

Нужен Python 3.11+. Если archive отсутствует, global setup не завершён:
повторите preview/apply из checkout.

## Agent не обнаружен

`setup detect` ищет executable из adapter manifest через `PATH`. Запустите
нативную команду версии в том же shell. Detection warning про unverified
version не всегда блокирует preview, но означает, что exact release smoke для
версии не записан.

Detection не выбирает target автоматически при явном `--target`. Проверьте ID:
для built-ins это `claude` и `codex`.

## `unknown adapter`

External package должен находиться в `ADAPTER_ROOT/<id>/adapter.json`, а имя
каталога — совпадать с `id`. Передайте `--adapter-dir ADAPTER_ROOT`.
Python package дополнительно требует `--trust-adapter-code ID`.

## `source root` missing или unsafe

Первая global-установка и global-upgrade строят self-contained manager из
полного checkout. Передайте абсолютный `--source-root CHECKOUT`. Не передавайте
архив, symlink или каталог без `src`, `templates/core` и shipped skills.

Project setup использует установленный global manager и clone не требует.

## `global manager and setup skill must be installed first`

Project setup запущен до валидной global-установки или global manifest/archive
изменены. Выполните global doctor. Если есть drift, восстановите последнюю
транзакцию или повторите global setup из checkout.

## Unmanaged output или generated drift

Сообщения `unmanaged generated output`, `unmanaged non-empty output` и
`managed output modified` — no-clobber, а не просьба добавить force.

1. откройте destination;
2. определите ownership;
3. сохраните user changes;
4. для generated file восстановите known version через rollback;
5. создайте новый preview.

Не меняйте hash в manifest.

## Doctor сообщает stale/missing file

Запустите doctor с правильным scope:

```text
MANAGER doctor --scope global --home HOME
MANAGER doctor --scope project --home HOME --cwd PROJECT
```

Проверьте первый blocking diagnostic. Missing canonical skill может означать
неполный install; modified native entrypoint — ручное редактирование generated
file; portability diagnostic — vendor syntax или unsafe reference в skill.

## Migration выдаёт unsupported/manual

Это ожидаемый capability gap. Сохраните source и выполните указанную native
настройку вручную. Не превращайте `unsupported` в `exact` без нового adapter
mapping и tests.

Если classification request содержит artifacts, создайте response только по
его closed decision kinds и выполните `migrate validate-response`. Source drift
после scan требует повторить весь pipeline.

## Blocking collision

Разные artifacts претендуют на один canonical destination. Preview показывает
стабильные alternative names. Выберите семантически правильный вариант,
переименуйте source или обновите classification; silent merge запрещён.

## Rollback отказывается восстанавливать

Файл изменился после transaction. Сначала сохраните текущее содержимое и
сравните hashes из journal/backup. Rollback не должен затирать новую работу.
Связанные transactions откатываются в обратном порядке.

## Claude statusline не работает

Statusline не входит в defaults. Он появляется только после
`--include-claude-statusline`, требует Node.js и отдельной ручной адаптации
Claude settings по packaged example. Codex этот asset не загружает.

Проверьте JSON settings, абсолютный native command path и:

```text
node --check PATH_TO_STATUSLINE
```

## После удаления checkout

Используйте:

```text
python ~/.agents/workflow/agent-workflow.pyz
```

Project setup, migration, doctor и rollback должны работать. Для global
upgrade новой версии снова скачайте checkout и передайте `--source-root`.

Архитектура и ownership: [architecture](architecture.md). Полные safety rules:
[safety](safety.md).
