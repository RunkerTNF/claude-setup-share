# Customization без forked agent state

Главное правило: общая семантика живёт в `.agents`; generated native files
редактировать не надо.

## Добавить общие rules

Не меняйте generated template ради локального правила. Создайте отдельный
Markdown-файл:

```text
~/.agents/rules/20-my-rule.md
<project>/.agents/rules/20-project-rule.md
```

`RULES.md` требует загружать `rules/` в lexical order. Global правила подходят
для поведения во всех проектах, project rules — для архитектуры и политики
конкретного репозитория.

Если вы намеренно меняете управляемый `RULES.md`, следующий setup покажет
drift и не перезапишет файл. Перенесите customization в extension file, затем
восстановите generated source через rollback или осознанный reconfigure.

## Manual memory и sessions

Global memory хранится в `~/.agents/memory/`, project memory — в
`<project>/.agents/memory/`. Добавляйте durable note и retrieval hook в
`MEMORY.md` одновременно. Task progress и handoff относятся к
`.agents/sessions/`, а не к memory.

Imported legacy notes перечислены в `memory/IMPORTED.md`; provenance не надо
удалять при редактировании содержимого.

## Custom Agent Skills

Создайте новый каталог с уникальным kebab-case именем:

```text
.agents/skills/my-skill/
  SKILL.md
  references/
  scripts/
```

Portable body не должен требовать Claude-only или Codex-only tool syntax.
Agent-specific invocation поместите в `overlays/claude.md`,
`overlays/codex.md` или будущий overlay. Не меняйте shipped skill in place,
если хотите продолжать получать upgrades без conflicts; создайте отдельный
skill или поддерживаемый fork с новым именем.

Project setup не копирует global skills. Project-scoped skill добавляйте в
project `.agents/skills/` только когда он действительно относится к одному
репозиторию.

## Native settings и overlays

Generated Claude/Codex entrypoint содержит hash marker и canonical imports.
Не вставляйте туда общие правила вручную: setup расценит это как drift.

- Общую семантику добавляйте в `.agents/rules/` или portable skill.
- Разницу agent harness добавляйте в `.agents/overlays/<agent>/`.
- Permissions, hooks, MCP и UI settings меняйте в нативном settings file,
  предварительно сверившись с adapter capability matrix.

Claude settings/statusline example лежит внутри Claude adapter и не
применяется автоматически.

## Reconfigure и regeneration

Всегда создавайте новый materialized preview:

```text
MANAGER setup preview --scope global --home HOME --source-root CHECKOUT --target claude --target codex --output setup-plan.json
MANAGER setup apply --plan setup-plan.json
```

Для project scope используйте `--project`, `--profile` и полный список
targets. Manager перегенерирует только управляемые files с ожидаемым hash.
Unmanaged customization сохраняется, drift блокирует apply.

После regeneration выполните doctor и fresh-session smoke.

## Optional personal examples

[`templates/examples/two-machine-workflow.md`](../templates/examples/two-machine-workflow.md)
и соседний `syncprotect` — parameterized examples, они не устанавливаются по
умолчанию. Скопируйте нужный фрагмент в user-authored rule и замените
placeholders. Не превращайте личный machine topology в shipped default.

Sharing policy для project state:
[project profiles](project-profiles.md).
