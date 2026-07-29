# Руководство по созданию adapter

Adapter подключает новый агент к canonical `.agents` workflow. Наличие
adapter package означает «можно попробовать и измерить capabilities», а не
автоматическую гарантию полного parity.

## Package layout

Минимальный declarative package:

```text
adapters/
  my-agent/
    adapter.json
    templates/
      global.md
      project.md
```

Имя каталога обязано совпадать с kebab-case `id`. Symlinks и пути с `..`
отклоняются. Optional `adapter.py` разрешён только через явный
`--trust-adapter-code my-agent` и должен экспортировать
`create_adapter(manifest, package_root)`.

## Поля `adapter.json`

Schema version 1 принимает только известные поля:

| Поле | Назначение |
|---|---|
| `schema_version` | Сейчас только `1`. |
| `id`, `display_name` | Стабильный ID и имя для UI/report. |
| `executables`, `version_args` | Detection executable и безопасная команда версии. |
| `supported_versions` | Отсортированные exact строки версий, прошедших release smoke. |
| `global`, `project` | Scope-specific discovery, entrypoints, skills и inventory. |
| `capabilities` | `supported`, `partial`, `unsupported` или `unknown` по каждой возможности. |
| `sensitive_keys` | Отсортированные ключи, значения которых нельзя переносить. |
| `validation` | Relative paths, которые doctor обязан увидеть. |
| `smoke` | Human-readable шаги manual validation. |

Каждая `global`/`project` секция содержит:

- `discovery_paths`;
- `instruction_entrypoints`;
- `skill_locations`;
- optional `inventory_roots`.

Instruction entrypoint задаёт `target`, packaged `template` и список
`profiles`. Пустой список profiles применяется ко всему scope.

Skill location имеет mode:

- `direct` — агент читает canonical `.agents/skills` напрямую;
- `wrapper` — adapter создаёт native metadata wrapper со ссылкой на canonical
  skill и соответствующий overlay.

## Detection и versions

Detection ищет первый executable и вызывает его с `version_args` с timeout.
Наличие executable не даёт consent на setup. Если `supported_versions` пуст
или exact output отсутствует в списке, detection показывает warning.

Не добавляйте версию по догадке. Сначала выполните полный automated gate и
manual live smoke, затем внесите exact reported string в отсортированный
`supported_versions`.

## Capability matrix

Заполняйте capabilities отдельно для rules, skills, commands, subagents,
permissions, hooks и MCP. Значения:

- `supported` — поведение доказано автоматическими и live checks;
- `partial` — переносится документированный subset;
- `unsupported` — безопасного соответствия нет;
- `unknown` — исследование не завершено.

Не выводите поддержку hooks из поддержки commands и не объявляйте permissions
эквивалентными по похожим названиям.

## Entrypoints и templates

Declarative adapter копирует packaged template в exact native target. Template
должен быть самодостаточным, ссылаться на `.agents` и не содержать личных
абсолютных путей или credentials.

Built-in adapters могут использовать проверенный renderer для hash marker,
optional overlay и canonical imports. Сгенерированный native file не должен
дублировать общие rules.

## `inventory_roots`

Каждый root задаёт:

- relative `path`;
- artifact `kind`;
- `recursive`;
- безопасные `include_globs`.

Сканируйте только документированные agent-owned locations. Не добавляйте home
целиком, plugin caches или credential stores. Для новых kinds сначала
реализуйте deterministic normalization или closed classification contract.

## `sensitive_keys` и mappings

Внесите все известные credential-bearing keys в `sensitive_keys`. Значения
API keys, tokens, cookies, private keys и auth headers не должны попадать в
plan или classification prompt.

Native mappings должны возвращать один из документированных states: `exact`,
`partial`, `manual`, `unsupported`, `sensitive_skip`. Custom mapping code
требует Python adapter и explicit trust. Declarative package не получает
неявное право на semantic conversion.

## Validation и tests

Минимальный adapter contribution включает:

1. manifest parser/registry tests;
2. detection tests для absent, successful, timeout и unknown version;
3. global/project entrypoint goldens;
4. skill mode tests;
5. sanitized migration fixture для каждого claimed mapping;
6. credential/path redaction tests;
7. doctor validation;
8. manual smoke steps.

Используйте built-in Claude Code и Codex adapters как reference структуры, но
не копируйте их capability claims без evidence.

## Когда поддержка считается гарантированной

Для статуса guaranteed нужны:

- built-in ownership и maintainer;
- green tests на Windows, macOS и Linux;
- все profile/setup/migration goldens;
- установленный artifact без source checkout;
- live fresh-session smoke;
- exact version в `supported_versions`;
- документированные gaps без скрытого fallback.

Pi, Cursor, Gemini CLI, OpenCode и Cline могут начать с declarative adapter и
Agent Skills. Пока этот bar не пройден, документация должна называть поддержку
experimental или community, а не guaranteed.

Перед установкой external package прочитайте
[safety guide](safety.md).
