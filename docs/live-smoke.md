# Live smoke: Claude Code and Codex

The release-blocking checklist and result table now live in
[release.md](release.md). This file remains the detailed per-agent walkthrough.

Run these checks before a release after all automated tests pass. Use a fresh
temporary home and temporary Git project for each agent. Do not reuse a
developer's real configuration.

Record for every run:

- date and workflow commit;
- operating system and Python version;
- agent name and exact agent version;
- scope and project profile;
- pass/fail outcome and any warning.

## Claude Code

1. Create an empty temporary home and an empty temporary project with a `.git`
   marker.
2. Follow [SETUP.md](../SETUP.md) to preview and apply global setup for the
   `claude` target.
3. Preview and apply project setup for one of `local`, `shared`, or `split`.
   Rotate profiles across release environments so all three receive periodic
   live coverage.
4. Open a fresh Claude Code session with the temporary home.
5. In Claude Code's native UI, verify that the generated instruction
   entrypoint loaded the neutral rules and memory index.
6. In the native skill UI, verify that `agent-workflow-setup` is available.
7. Invoke `agent-workflow-setup` and stop after its dry-run plan. Confirm that
   it reports detected targets, scope/profile choices, exact operations, and
   asks before apply.
8. Delete or move away the bootstrap checkout.
9. Run the installed manager archive's `doctor` command against the temporary
   neutral scope. It must complete without a missing-bootstrap dependency.
10. Record the Claude Code version, OS, profile, and outcome.

## Codex

1. Create a different empty temporary home and temporary Git project.
2. Follow [SETUP.md](../SETUP.md) to preview and apply global setup for the
   `codex` target.
3. Preview and apply project setup for one of `local`, `shared`, or `split`.
   Rotate profiles across release environments.
4. Open a fresh Codex session with the temporary home.
5. In Codex's native UI, verify that the generated instruction entrypoint
   loaded the neutral rules and memory index.
6. In the native skill UI, verify that `agent-workflow-setup` is available
   directly from the canonical skills directory.
7. Invoke `agent-workflow-setup` and stop after its dry-run plan. Confirm that
   it reports detected targets, scope/profile choices, exact operations, and
   asks before apply.
8. Delete or move away the bootstrap checkout.
9. Run the installed manager archive's `doctor` command against the temporary
   neutral scope. It must complete without a missing-bootstrap dependency.
10. Record the Codex version, OS, profile, and outcome.
