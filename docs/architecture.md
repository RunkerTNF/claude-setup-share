# Архитектура Agent Workflow

## Цель

Agent Workflow отделяет переносимое состояние от формата конкретного агента.
Canonical rules, manual memory, sessions и skills живут в `.agents`.
Claude Code, Codex и внешние adapters создают только нативные точки входа и
явно agent-specific state.

```text
bootstrap checkout
      │ build preview
      ▼
TransactionPlan ── apply ──► .agents canonical core
      │                         │
      │                         ├─ manifest + manager + journals
      │                         └─ skills/rules/memory/sessions
      ▼
generated native entrypoints ◄── adapter
```

Bootstrap checkout не является runtime dependency. Global setup сохраняет
self-contained `~/.agents/workflow/agent-workflow.pyz`; после doctor checkout
можно удалить. Он снова нужен только как источник новой версии при global
upgrade.

## Слои

### Neutral core

Global root — `~/.agents/`, project root — `<project>/.agents/`.

- `RULES.md` задаёт стабильный порядок загрузки;
- `rules/` содержит пользовательские расширения общих правил;
- `memory/MEMORY.md` индексирует durable manual memory;
- `sessions/` хранит хронологический continuation context;
- `skills/` содержит portable Agent Skills;
- `overlays/<agent>/` содержит только различия harness;
- `workflow/` содержит manager, adapters, backups, journals и staging.

### Adapter layer

Adapter отвечает за:

- detection executable и версии;
- global/project discovery paths;
- generated instruction entrypoints;
- `direct` или `wrapper` skill locations;
- inventory roots для migration;
- capability states и sensitive keys;
- validation и manual smoke checklist.

Built-in Claude Code и Codex adapters могут дополнительно реализовать
проверенные native mappings. Внешний declarative adapter не получает
неограниченное выполнение кода.

### Native layer

Native entrypoints принадлежат generator и ссылаются на `.agents`. Native
settings, permissions, hooks и MCP остаются adapter-owned: они не становятся
canonical только потому, что похожее поле есть у другого агента.

## Владение файлами

План различает три практических класса:

- canonical — переносимый workflow content;
- generated — manager, manifest, native entrypoints и managed ignore blocks;
- user-authored — дополнительные rules, memory, sessions и custom skills, не
  перечисленные в manifest.

`manifest.json` хранит targets, profile, excluded skills и hashes управляемых
файлов. Manager не перезаписывает unmanaged path и не принимает drift
управляемого файла без явного разрешения конфликта.

## Setup data flow

1. `setup detect` читает registry и окружение без записи.
2. `setup preview` валидирует source root, targets, profile и adapter trust.
3. Core planner, profile policy и adapters создают один `TransactionPlan`.
4. Пользователь проверяет exact operations и подтверждает именно этот plan.
5. Apply повторно проверяет hashes, создаёт backup/staging и пишет journal.
6. Doctor сверяет manifest, portability и native entrypoints.

Global setup устанавливает shipped skills. Project setup использует global
manager и не дублирует global skills; project skills появляются как
user-authored content в project `.agents/skills/` или через migration.

## Migration data flow

Migration разделяет deterministic Python и semantic classification:

1. adapters перечисляют только известные inventory roots;
2. scanner фиксирует hashes и sensitivity;
3. deterministic normalization переносит однозначные artifacts;
4. неоднозначные artifacts попадают в redacted classification request;
5. агент выбирает только закрытый decision kind;
6. Python проверяет response и вычисляет destinations;
7. preview показывает imports, mappings, conflicts и preserved sources;
8. apply выполняет journaled import и, отдельно, optional native replacement.

Подробности: [migration guide](migration.md) и
[safety boundary](safety.md).

## Scope и profile

Global и project state не смешиваются. Project profile определяет только
sharing/ignore policy, а не семантику rules или memory. Точная матрица:
[project profiles](project-profiles.md).

## Extension boundary

Agent Skills дают переносимый минимальный контракт. Всё, что требует нативного
пути, lifecycle hook, permission schema или model-specific API, должно
находиться в adapter/overlay. Требования к новому adapter:
[adapter authoring](adapter-authoring.md).
