---
name: agent-workflow-setup
description: Use when installing, configuring, or reconfiguring the portable multi-agent workflow globally or for one project.
---

# Agent Workflow Setup

Read [the setup flow](references/setup-flow.md) completely before planning
filesystem changes. For project setup or read-only project inference, also
read [project inference](references/project-inference.md).

Resolve the persistent manager in this order:

1. Use `agent-workflow` on `PATH` when available.
2. Otherwise run `~/.agents/workflow/agent-workflow.pyz` with Python 3.11 or
   newer.

Keep detection and preview read-only. Never apply a plan until the user has
seen its scope, targets, profile, warnings, conflicts, and exact file
operations and has explicitly confirmed that exact plan.

Do not download adapters or execute adapter code that the user did not
explicitly supply and trust. Describe unsupported agents as capability gaps;
do not invent agent-specific files or commands.
