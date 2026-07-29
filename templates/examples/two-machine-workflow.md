# Optional Two-Machine Workflow

This example is not installed by default. Copy and adapt it only when editing
and execution happen on different machines.

## Topology

- The agent-capable machine edits projects below `<sync-root>`.
- `<corporate-machine>` can reach private source control and services.
- A user-operated sync tool transfers application files between the machines.
- Tool-local baseline state such as `.sync-state/` stays local and is never
  edited, committed, or transferred.

## Working agreement

Before editing, confirm which machine owns the newest project state and sync it
to the agent-capable machine. After editing, transfer only the intended project
changes back to `<corporate-machine>`, then run private-service checks and create
team commits there.

Keep personal workflow state out of the transferred application tree. If the
sync tool supports a protection file, start from the adjacent `syncprotect`
example and adapt it to the selected `local`, `shared`, or `split` project
profile. Never assume that ignored files are also protected from sync.

Inspect sync status before and after each transfer. Treat conflicts as a reason
to stop and reconcile both sides; do not overwrite the newer side
automatically.
