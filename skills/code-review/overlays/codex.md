# Codex Review Workflow

The installed portable `plan-review` and `code-review` skills are the semantic
source of truth.

Perform reviews in the current task by default. Use a generic worker only when
the user explicitly requests delegated review and generic-agent delegation is
available. Give that worker the relevant request, plan, or diff plus the
portable contract; do not depend on a named reviewer role.

If delegation is unavailable, perform the same portable skill in the current
task.
