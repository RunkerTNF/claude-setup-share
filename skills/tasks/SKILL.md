---
name: tasks
description: Use when showing the latest locally synchronized task digest, opening one task by ID, or answering follow-up questions from the task snapshot.
---

# Task Digest

Read [the rendering contract](references/workitems-rendering.md) completely
before rendering data.

Read `~/sync-workitems/tasks/_meta.json` and
`~/sync-workitems/tasks/_changes_since_last.json` with the current agent's
local file capabilities. Render one Level 1 `tasks — global` section without a combined total.
Use the contract's no-data and empty-change states when files are absent or
changes are empty.

Read task frontmatter for missing titles and current statuses. On a follow-up
task ID, render task Level 2. A bare number may match the unique available key
with that numeric suffix; list candidates rather than guessing when
ambiguous. Answer other questions only from the synchronized Markdown and
JSON data.
