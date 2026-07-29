# Claude Code Review Workflow

The installed portable `plan-review` and `code-review` skills are the semantic
source of truth.

Perform reviews in the current session by default. Use a named reviewer
subagent only when the user explicitly requests delegated review or project
rules explicitly require it and the harness supports it. Generated convenience
calls may use `Agent(subagent_type="plan-reviewer")` or
`Agent(subagent_type="code-reviewer")`, passing the relevant request, plan, or
diff context and requiring the portable contract's output format.

If named delegation is unavailable, perform the same portable skill in the
current session.
