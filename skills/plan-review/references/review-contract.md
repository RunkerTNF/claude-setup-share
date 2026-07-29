# Plan Review Contract

Review as a critic, not a co-author. The subject is the supplied plan and its
relationship to the request, current repository, neutral rules, and relevant
memory.

## Required evidence

1. Read the complete plan and the original request or specification.
2. Read `.agents/RULES.md`, applicable project rules, and relevant entries
   indexed by `.agents/memory/MEMORY.md`.
3. Verify named files, functions, classes, flags, environment variables,
   commands, and configuration keys against current code with read-only
   inspection.
4. Read enough surrounding code to judge the proposed location and approach.

## Triviality

For a truly trivial plan such as a one-line typo or single configuration
change, say review is unnecessary in one line. Do not invent findings.

## Plan adherence

- Every step must map to the request or specification.
- References must exist and be precise enough to implement.
- The plan must not silently omit an explicitly requested outcome.

## Convention compliance

Check neutral project rules, environment constraints, architecture, ownership,
storage profile, language, and review conventions. Flag prohibited commands,
directories, or agent-native canonical state.

## Memory invariants

Apply only relevant indexed `.agents/memory/` notes. Treat a documented
project invariant or prior incident as blocking when the plan violates it.
Cite the note.

## Safety

Check trust boundaries, credentials, destructive operations, external writes,
rollback needs, path containment, and confirmation gates. A plan must not
broaden authority beyond the request.

## Tests and verification

Non-trivial changes need proportionate verification. Check that the plan covers
important edge cases and specifies an observable success condition. Do not
demand unavailable infrastructure when project rules prohibit it.

## Scope discipline

Flag speculative abstractions, unrelated refactors, compatibility shims,
feature flags without a requirement, impossible-state validation, and
unrequested fallback behavior.

## Output

Return plain Markdown under 400 words:

```text
## Plan review: <plan name>

### Blocking
- <specific location or quoted step> - <problem and evidence>

### Suggestions
- <optional non-blocking improvement>

### Verdict
<Blocking issues found - address before implementation | Clean, good to go | Minor suggestions, not blocking>
```

Omit empty Blocking or Suggestions sections. Findings must cite a plan section,
file, rule, or memory note. Do not restate the plan.
