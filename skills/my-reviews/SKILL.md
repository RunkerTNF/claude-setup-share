---
name: my-reviews
description: Use when showing locally synchronized merge requests where the user is a reviewer, selecting one repository or all repositories, drilling into diffs, or preparing review observations.
---

# Merge Requests to Review

Read [the rendering contract](references/workitems-rendering.md) completely
before rendering data.

Resolve the optional argument:

1. With no argument, use the basename of the current working directory when
   `~/sync-projects/<repo>/.sync-workitems/reviews/` exists.
2. A repository name selects that exact local source.
3. `all` selects every repository with review data.

If resolution fails, show the current name and available repositories. If
`all` finds none, report that no local review data exists.

For each selected repository, read metadata, changes, and necessary item
frontmatter. Render one review Level 1 section per repository without a
combined total.

On a follow-up ID, render MR Level 2 in review context. Support complete or
filtered diff drill-in, concrete review observations, and free-form questions
from the local Markdown and diff. Do not add feedback direction markers and
do not post review comments.
