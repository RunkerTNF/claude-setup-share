# Migration Recovery

Migration is additive by default. Source artifacts remain in place unless the
user explicitly confirms a preview that replaces native generated
entrypoints. Never delete legacy content as an informal cleanup step.

## Before apply

Verify that the materialized migration plan records:

- every imported source artifact;
- every proposed destination;
- all conflicts, unsupported fields, and sensitive skips;
- whether native replacement was requested;
- backup and rollback destinations.

If any of these differ from what the user reviewed, generate a new plan and
obtain new confirmation.

## After apply

Preserve and report the transaction journal path, backup locations, rollback
locations, and migration report. Run doctor against the affected neutral
scope. A doctor failure does not authorize manual deletion or overwriting.

## Rollback

Use the manager's `rollback <journal>` command with the exact journal produced
by the applied transaction. Preview or inspect the journal before rollback
when the affected paths are not already clear to the user.

After rollback:

1. run doctor again;
2. verify that preserved source artifacts still exist;
3. report restored paths and any unresolved diagnostics.

If the journal or backup is missing, stop and report the missing evidence.
Do not reconstruct a destructive rollback from memory.
