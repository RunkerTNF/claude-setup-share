# Agent Workflow Rules

`.agents/RULES.md` is the neutral, global source of truth for workflow rules
shared by configured agents.

Before the first response or action:

1. Read every Markdown file under `.agents/rules/` in lexical order.
2. Read `.agents/memory/MEMORY.md` and only the entries relevant to the task.
3. Read `.agents/overlays/<current-agent>/RULES.md` when it exists.

Use the portable `plan-review` skill to critique non-trivial implementation
plans before implementation and `code-review` to critique non-trivial pending
changes before reporting completion or integration. The current agent performs
each review unless the user explicitly requests delegation and the active
agent supports it. Agent overlays may describe invocation mechanics but never
replace the portable review contracts.
