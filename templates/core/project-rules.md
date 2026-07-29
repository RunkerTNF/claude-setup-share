# Project Workflow Rules

`.agents/RULES.md` is the neutral, project-scoped source of truth for workflow
rules shared by configured agents.

Before the first response or action:

1. Read every Markdown file under `.agents/rules/` in lexical order.
2. Read `.agents/memory/MEMORY.md` and only the entries relevant to the task.
3. Read `.agents/project.md` when it exists.
4. Read `.agents/overlays/<current-agent>/RULES.md` when it exists.

Use `.agents/sessions/` for chronological continuation notes and backlog
state. Session notes are context, not always-on rules; load only the latest
relevant note when continuing earlier work.
