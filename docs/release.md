# Release gate

Стабильный release разрешён только после automated matrix и manual live smoke
на Claude Code и Codex. CI не запускает реальные agent sessions и не может
заменить этот gate.

## Automated gate

Локально:

```text
python scripts/release_check.py
```

Checker fail-fast выполняет:

1. portable skill lint;
2. documentation links и forbidden-content tests;
3. unit/migration tests;
4. setup/migration goldens;
5. transaction fault-injection tests;
6. installed-artifact setup/migration tests;
7. двойную byte-identical сборку `agent-workflow.pyz` и SHA-256;
8. `git diff --check`.

Для persistent artifacts:

```text
python scripts/release_check.py --artifact-dir dist
```

GitHub Actions запускает checker на `windows-latest`, `macos-latest` и
`ubuntu-latest`, Python 3.11 и newest stable (`3.x`). Ubuntu/Python 3.11 job
публикует `agent-workflow.pyz` и `agent-workflow.pyz.sha256`.

Automated gate доказывает filesystem/CLI behavior, но не утверждает, что
реальная версия агента загрузила native instructions и skills.

## Manual live smoke

Для каждого гарантированного агента используйте отдельные чистые temporary
home и Git project:

1. Запустите fresh agent session и укажите [SETUP.md](../SETUP.md).
2. Убедитесь, что агент проверяет Python, выполняет detection и спрашивает
   target/scope/profile.
3. Просмотрите fresh global preview, подтвердите и примените.
4. Переместите или удалите bootstrap clone.
5. Запустите новую session и вызовите установленный
   `agent-workflow-setup`.
6. Настройте temporary project в profile `split`.
7. Создайте sanitized legacy rule/memory/skill и выполните migration preview
   и apply.
8. Убедитесь, что native entrypoint ссылается на common `.agents/RULES.md`,
   portable skills доступны, manual memory читается из `.agents`.
9. Запустите global и project doctor.
10. Измените один generated file и убедитесь, что новый preview отказывается
    его перезаписывать.
11. Восстановите файл, откатите последнюю безопасную transaction и
    hash-сравните результат с backup.

Не используйте реальный home: smoke включает intentional drift и rollback.
Не добавляйте credentials в fixture.

## Результаты текущего candidate

| Дата | OS | Agent | Exact version | Result | Issue/notes |
|---|---|---|---|---|---|
| 2026-07-30 | Windows | Claude Code | `2.1.209 (Claude Code)` | BLOCKED | fresh session rejected an expired OAuth token with HTTP 401; re-authentication and a complete rerun are required |
| 2026-07-30 | Windows | Codex | `codex-cli 0.144.0-alpha.4` | PARTIAL | fresh agent read `SETUP.md` and selected the correct preview command; nested read-only policy blocked Python execution, while automated installed-release setup/project/migration/doctor passed; complete native-session rerun is required |

`BLOCKED`, `PARTIAL` и `FAIL` блокируют stable tag так же, как `pending`.
Detected version не добавляется в `supported_versions`, пока строка не получила
PASS по checklist выше. После PASS:

1. запишите дату, OS, exact version и result в таблицу;
2. добавьте exact output в отсортированный `supported_versions` нужного
   `adapter.json`;
3. повторите `python scripts/release_check.py`;
4. убедитесь, что рабочее дерево чистое.

Любой FAIL или pending блокирует stable tag. Ссылка на issue обязательна, если
FAIL переносится на следующий candidate.

## Release artifact

Публикуются:

- deterministic `agent-workflow.pyz`;
- `agent-workflow.pyz.sha256`;
- source archive соответствующего signed/tagged commit, создаваемый hosting
  platform.

Checksum проверяется до запуска:

```text
python -c "import hashlib, pathlib; p=pathlib.Path('agent-workflow.pyz'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

Релизная документация должна ссылаться на commit, automated CI run и две
manual PASS rows.
