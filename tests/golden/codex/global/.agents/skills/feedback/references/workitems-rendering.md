# Workitem Rendering Contract

Read local synchronized files, search their content, and render Markdown. Do
not contact Jira, GitLab, or another remote service. Preserve the language of
the source and the user in summaries, observations, and reply drafts.

## Local data contract

Tasks use `~/sync-workitems/tasks/`:

- `<KEY>.md`: YAML frontmatter plus Description and Comments sections;
- `_meta.json`: kind, source, username, fetch timestamps, and item count;
- `_changes_since_last.json`: fetch timestamps and change records;
- `_snapshot.json`: internal raw data; do not read it for rendering.

Reviews and feedback use
`~/sync-projects/<repo>/.sync-workitems/<kind>/`, where kind is `reviews` or
`feedback`. Items are `MR-<iid>.md` with an optional `MR-<iid>.diff` sidecar.

Discover sources with the current agent's read-only file listing or search
capability. If one path-expansion method is unreliable on the host, use
another read-only listing capability; do not hard-code a shell or tool name.

## Change records

`changes[]` may contain:

- `new`: id, summary, and optional author;
- `closed`: id and summary;
- `status_changed`: id, from, and to;
- `comments_added`: id, count, authors, and 200-character previews;
- `diff_changed`: id, for merge requests only;
- `comment_resolved`: id, count, and discussion IDs, for merge requests only;
- `updated`: id and changed fields.

Read the matching item frontmatter when a record does not contain its title.
For tasks, also read current status for every Level 1 change.

## Level 1: digest

Render one section per kind and repository:

```text
## <emoji> <kind> — <repo-or-global>
*last fetch: <YYYY-MM-DD HH:MM UTC>  (<age>)*
*prev fetch: <YYYY-MM-DD HH:MM UTC>  (<age>)*

<staleness warning when older than 24 hours>

**<count> changes:**

<one h3 block per change>

_For the full item, provide its id._
```

Use 📋 for tasks, 🔍 for reviews, and 💌 for feedback. Format age in whole
hours, or minutes below one hour. When `previous_fetched_at` is null, say that
this is the initial fetch and all items appear new.

Render change headings:

| Kind | Heading |
|---|---|
| `new` | `### 🆕 new — **<id>** <task-status> by <author> — "<summary>"` |
| `closed` | `### ✅ closed — **<id>** <task-status> — "<summary>"` |
| `status_changed` | `### 🔄 status — **<id>** — "<title>"`, then the transition |
| `comments_added` | `### 💬 comments — **<id>** <task-status> by <authors> — "<title>"`, then previews |
| `diff_changed` | `### 📝 diff — **MR-<iid>** — "<title>"`, then a short updated note |
| `comment_resolved` | `### ✓ resolved — **MR-<iid>** — "<title>"`, then the count |
| `updated` | `### ✏️ updated — **<id>** <task-status> — "<title>"` |

Bold IDs, italicize authors, use inline code for statuses, quote titles, and
use angled quotes for comment previews. Show status only for tasks; merge
request state is omitted from Level 1 headings.

## Status mapping

Map Jira statuses:

- 🟡: Open, To Do, Selected for Development, or semantically queued;
- 🟢: In Progress, In Review, or semantically active development;
- ⚪: Backlog or semantically parked;
- ✅: Done or Resolved;
- ⚫: Closed;
- 🔴: Blocked, On Hold, or Cancelled;
- ⬛: unknown.

Map merge request states: opened 🟢, merged 🟣, closed 🔴, locked 🔒.
For custom workflows, map by meaning and keep the original status text.

## Empty and edge states

- Missing metadata means no synchronized data exists yet; say so without
  failing.
- An empty changes array means no changes since the previous fetch and omits
  the drill-in hint.
- A missing item ID lists available IDs.
- Multiple requested IDs render sequentially with a horizontal separator.
- Stale data remains usable but gets a warning; do not trigger synchronization
  automatically.

## Level 2: task

Render the task ID and title, status, created and updated dates, normalized
description, and every comment with author and timestamp. Use an explicit
placeholder for an empty description or no comments.

### Jira normalization

Preserve paragraphs and list structure. Convert Jira wiki fragments:

- a bracketed GitLab file URL becomes a Markdown link labelled with filename
  and line anchor when present;
- another bracketed URL becomes an autolink;
- Jira label-and-target syntax becomes an ordinary Markdown link;
- double-braced inline text becomes inline code;
- bare URLs remain unchanged.

## Level 2: merge request

Render:

1. ID, title, state, author, branches, and dates;
2. `In short`: two to four evidence-based sentences from description and
   diff;
3. normalized description;
4. a per-file diff-statistics table and total;
5. comment threads in source order;
6. a compact menu of available Level 3 follow-ups.

For feedback, mark comments from `_meta.username` with 📤 and other authors
with 📥. Omit these markers for reviews. Preserve server-rendered code anchors
and resolved or unresolved markers exactly; never invent an anchor.

### Diff statistics

Split unified diff content on `diff --git`. Use the post-image path, or the
pre-image path for a deletion. Count added lines beginning with `+` except
`+++`, and removed lines beginning with `-` except `---`. Sum a total row.

If a merge request exists in both reviews and feedback and earlier context
does not disambiguate it, prefer the review interpretation.

## Level 3: diff drill-in

On a diff follow-up, read the entire sidecar and split it into per-file
unified-diff blocks. An optional glob or case-insensitive fragment filters
paths. Render each complete selected block in a `diff` fence without
truncating, rewrapping, joining, or replacing lines. If no path matches, list
available paths.

## Level 3: Review observations

For a review request, inspect the full description, comments, and diff.
Return concrete strengths, discussion points, possible bugs, and actionable
draft review comments. Cite files, functions, or lines. Avoid generic style
advice and do not post comments remotely.

## Level 3: Reply drafting

For feedback, group comments by source h3 thread. Skip a thread explicitly
marked resolved. An explicitly unresolved thread needs a response. When a
non-resolvable thread has no marker, it is open only when its last comment is
not from `_meta.username`.

For each open thread, provide an interpretation, an optional unified suggested
fix when technically applicable, and a copy-ready draft reply in the user's
language. Support focusing one numbered thread, patches only, or reply text
only. Never send the reply.
