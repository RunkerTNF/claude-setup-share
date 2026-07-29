# Agent Workflow

Agent Workflow переносит правила, ручную память, session notes и skills между
агентными LLM, не делая каталог одного инструмента источником истины. Полезно,
если вы работаете с Claude Code, Codex или хотите подготовить тот же workflow
для следующего агента без второго набора памяти и инструкций.

Репозиторий — одноразовый bootstrap. После установки постоянный manager и
данные находятся в `~/.agents/` глобально и в `<project>/.agents/` для
проекта. Checkout можно удалить: настройка проектов, doctor, rollback и
миграция продолжают работать через установленный `agent-workflow.pyz` и
portable skills.

## Модель

```text
canonical .agents core
  ├─ RULES.md + rules/
  ├─ memory/
  ├─ sessions/
  ├─ skills/
  └─ overlays/
          │
          ├─ generated Claude Code entrypoints/wrappers
          └─ generated Codex entrypoints
```

Общие правила и skills пишутся один раз. Adapter знает только нативные пути,
формат entrypoint, discovery и возможности конкретного агента. Нативные
settings, permissions, hooks и MCP-конфигурация не объявляются универсальными,
если между инструментами нет доказанного соответствия.

Подробная схема владения файлами описана в
[архитектуре](docs/architecture.md).

## Поддержка агентов

Claude Code и Codex — встроенные гарантированные adapters. Для них есть
детектирование, global/project entrypoints, skills, миграционные mappings,
golden-тесты и обязательный live smoke перед релизом.

Pi, Cursor, Gemini CLI, OpenCode, Cline и будущие агенты могут подключаться
через Agent Skills и внешний adapter. Это путь расширения, а не заявление о
гарантированном parity: уровень поддержки определяется capability matrix,
golden fixtures и live smoke конкретной версии. Контракт находится в
[руководстве по adapters](docs/adapter-authoring.md).

## Быстрый старт

Нужен Python 3.11+.

```text
git clone <this-repository>
cd <this-repository>
python scripts/bootstrap.py --target claude --target codex
```

Первый запуск только показывает detection и materialized preview. После
проверки примените тот же выбор:

```text
python scripts/bootstrap.py --target claude --target codex --apply
```

Без `--yes` manager отдельно попросит подтверждение. Затем:

```text
python ~/.agents/workflow/agent-workflow.pyz doctor --scope global
```

Полный одностраничный контракт для человека или любого агентного LLM:
[SETUP.md](SETUP.md). Подробные сценарии:
[INSTALL.md](INSTALL.md).

## Fresh setup и legacy migration

Fresh setup создаёт нейтральное ядро и выбранные нативные entrypoints. Он не
импортирует и не удаляет существующие `.claude`, `.codex` или другие
настройки.

Legacy migration отдельно:

1. сканирует Claude-only, Codex-only или mixed state;
2. нормализует переносимые commands, skills, memory и sessions;
3. просит агента классифицировать только неоднозначный заранее ограниченный
   набор;
4. показывает preview с conflicts и unsupported state;
5. применяет journaled transaction, сохраняя исходники по умолчанию.

Пошаговый процесс: [docs/migration.md](docs/migration.md).

## Global и project scope

Global scope хранится в `~/.agents/` и доступен во всех проектах. Project scope
хранится в `<project>/.agents/` и добавляет правила, память и продолжение
работы конкретного репозитория.

При настройке проекта пользователь выбирает профиль:

- `local` — workflow остаётся локальным и игнорируется git;
- `shared` — правила, память, sessions и project skills можно коммитить;
- `split` — правила и project skills общие, личная память, sessions и overlays
  локальные.

Точная таблица tracked/ignored/generated:
[docs/project-profiles.md](docs/project-profiles.md).

## Что живёт в `.agents`

- `RULES.md` и `rules/` — всегда применимые общие правила;
- `memory/` — вручную поддерживаемые долговечные знания с индексом
  `MEMORY.md`;
- `sessions/` — хронологический контекст продолжения работы и backlog;
- `skills/` — portable Agent Skills, включая setup, migration, wrap, backlog,
  workitem digests и review workflow;
- `overlays/<agent>/` — только различия конкретного harness;
- `workflow/` — manager, manifest-related runtime, adapters, journals,
  backups и staging.

Редактировать canonical state и регенерировать нативные файлы нужно по
[руководству по customization](docs/customization.md).

## Безопасность

Setup и migration работают preview-first. Materialized plan имеет стабильный
ID и точные hashes; apply отказывается перезаписывать unmanaged или
изменившийся файл. Запись проходит через staging, backup и transaction journal.
Credentials не переносятся, а внешний Python adapter не исполняется без
явного `--trust-adapter-code`.

Основные документы:

- [safety и trust boundary](docs/safety.md);
- [troubleshooting и recovery](docs/troubleshooting.md);
- [live smoke для гарантированных agents](docs/live-smoke.md).

## Опциональные примеры

Личный topology не входит в defaults. Обезличенный двухмашинный сценарий лежит
в
[`templates/examples/two-machine-workflow.md`](templates/examples/two-machine-workflow.md)
и не устанавливается автоматически. Скопируйте и параметризуйте его только
если такой workflow действительно нужен.

## Расширение и гарантия

Декларативный adapter можно передать через `--adapter-dir`; Python adapter
дополнительно требует явного trust. Наличие adapter ещё не означает
«гарантированную поддержку». Такой статус требует полного automated gate,
live smoke на заявленных версиях и заполненного `supported_versions`.

С чего продолжить:
[adapter authoring](docs/adapter-authoring.md),
[project profiles](docs/project-profiles.md),
[release policy](docs/live-smoke.md).
