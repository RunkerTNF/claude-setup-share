---
name: agent-workflow-setup
description: Install or configure the portable multi-agent workflow globally or for one project.
---

# Agent Workflow Setup

Use this skill when the user asks to install, configure, or reconfigure the
portable agent workflow.

Read [references/flow.md](references/flow.md) completely before planning any
filesystem changes. Keep detection and planning read-only. Never apply a plan
until the user has seen its targets, profile, warnings, conflicts, and exact
file operations and has explicitly confirmed it.

Use the persistent manager archive under the neutral workflow root and run it
with Python 3.11 or newer. Do not download adapters or execute adapter code
that the user did not explicitly supply and trust.
