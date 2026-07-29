# Agent Workflow Rules

`.agents/RULES.md` is the neutral, global source of truth for workflow rules
shared by configured agents.

Before the first response or action:

1. Read every Markdown file under `.agents/rules/` in lexical order.
2. Read `.agents/memory/MEMORY.md` and only the entries relevant to the task.
3. Read `.agents/overlays/<current-agent>/RULES.md` when it exists.

Keep universal behavior in `.agents`; native agent files are generated
entrypoints or adapter-owned settings, not competing sources of truth.
Project rules add to these global rules and take precedence only for their
project.

Preserve unrelated working-tree changes. Inspect scope and current state before
editing, never hide user changes, and require explicit approval for destructive
or hard-to-recover actions. Verify changed behavior in proportion to its risk
before reporting completion.

Store durable global knowledge under `.agents/memory/` and index it in
`.agents/memory/MEMORY.md` as soon as it becomes useful. Store chronological
continuation context in a project's `.agents/sessions/`; session notes are
context, not always-on rules.

Use the portable `plan-review` skill to critique non-trivial implementation
plans before implementation and `code-review` to critique non-trivial pending
changes before reporting completion or integration. The current agent performs
each review unless the user explicitly requests delegation and the active
agent supports it. Agent overlays may describe invocation mechanics but never
replace the portable review contracts.
