# Project Workflow Rules

`.agents/RULES.md` is the neutral, project-scoped source of truth for workflow
rules shared by configured agents.

Before the first response or action:

1. Read the global `~/.agents/RULES.md` workflow when it exists.
2. Read every Markdown file under `.agents/rules/` in lexical order.
3. Read `.agents/memory/MEMORY.md` and only the entries relevant to the task.
4. Read `.agents/project.md` when it exists.
5. Read `.agents/overlays/<current-agent>/RULES.md` when it exists.

Use `.agents/sessions/` for chronological continuation notes and backlog
state. Session notes are context, not always-on rules; load only the latest
relevant note when continuing earlier work.

Keep project-specific rules and durable project knowledge in `.agents`, while
native Claude, Codex, or other agent files remain generated entrypoints or
adapter-owned settings. Respect the selected project profile before tracking,
ignoring, or sync-protecting workflow files.

Preserve unrelated changes and inspect the repository state before modifying
files. Do not stage, commit, push, delete, or overwrite work unless the request
and repository policy authorize it. Verify application changes before
reporting them complete.
