---
name: morning
description: Use when producing one morning brief from locally synchronized tasks, merge requests awaiting review, and review feedback across all available repositories.
---

# Morning Workitem Brief

Read [the rendering contract](references/workitems-rendering.md) completely
before rendering data.

Use only local synchronized files:

- tasks from `~/sync-workitems/tasks/`;
- reviews and feedback from
  `~/sync-projects/<repo>/.sync-workitems/<kind>/`.

With the current agent's read-only file capabilities, collect metadata and
changes for every available source. Render Level 1 sections in this order:
tasks, reviews by repository, then feedback by repository. When a kind has no
source, render one clear no-data section for that kind.

Finish with a combined total of task, review, and feedback change counts.
Afterward, handle task or merge-request IDs, diff drill-ins, review
observations, reply drafting, and free-form questions using the bundled
rendering contract and the already established source context.
