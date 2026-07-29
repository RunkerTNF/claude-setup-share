# Migration Preview

## Source mappings

- claude:.claude/CLAUDE.md -> neutral:rules/claude-shared-rules-from-claude.md
- claude:.claude/commands/backlog.md -> neutral:skills/backlog
- claude:.claude/commands/feedback.md -> neutral:skills/feedback
- claude:.claude/commands/init-claude.md -> neutral:skills/init-claude
- claude:.claude/commands/morning.md -> neutral:skills/morning
- claude:.claude/commands/my-reviews.md -> neutral:skills/my-reviews
- claude:.claude/commands/pick.md -> neutral:skills/pick
- claude:.claude/commands/tasks.md -> neutral:skills/tasks
- claude:.claude/commands/wrap.md -> neutral:skills/wrap
- claude:.claude/settings.json:effortLevel -> codex:unmapped (manual)
- claude:.claude/settings.json:permissions -> codex:unmapped (manual)

## Preserved source files

- claude:.claude/CLAUDE.md
- claude:.claude/agents/code-reviewer.md
- claude:.claude/agents/plan-reviewer.md
- claude:.claude/commands/backlog.md
- claude:.claude/commands/feedback.md
- claude:.claude/commands/init-claude.md
- claude:.claude/commands/morning.md
- claude:.claude/commands/my-reviews.md
- claude:.claude/commands/pick.md
- claude:.claude/commands/tasks.md
- claude:.claude/commands/wrap.md
- claude:.claude/settings.json
- claude:.claude/statusline.js
- claude:.claude/workitems-rendering.md

## Blocking conflicts

- None

## Warnings

- unsupported: .claude/agents/code-reviewer.md
- unsupported: .claude/agents/plan-reviewer.md
- unsupported: .claude/statusline.js
- unsupported: .claude/workitems-rendering.md

## Sensitive skips

- None

## Unsupported fields

- None

## Deduplications

- None

## Expected doctor checks

- generated hashes
- manifest schema
- portable skill references
