---
name: feedback
description: Use when showing locally synchronized merge requests authored by the user, selecting one repository or all repositories, inspecting review threads, or preparing reply drafts and suggested fixes.
---

# Review Feedback

Read [the rendering contract](references/workitems-rendering.md) completely
before rendering data.

Resolve the optional argument:

1. With no argument, use the basename of the current working directory when
   `~/sync-projects/<repo>/.sync-workitems/feedback/` exists.
2. A repository name selects that exact local source.
3. `all` selects every repository with feedback data.

If resolution fails, show the current name and available repositories. If
`all` finds none, report that no local feedback data exists.

For each selected repository, read metadata, changes, and necessary item
frontmatter. Render one feedback Level 1 section per repository without a
combined total.

On a follow-up ID, render MR Level 2 in feedback context and use the metadata
username for 📥 and 📤 markers. Support complete or filtered diff drill-in,
reply drafts for all or one open thread, patches-only or text-only variants,
and free-form questions. Never send replies or change remote state.
