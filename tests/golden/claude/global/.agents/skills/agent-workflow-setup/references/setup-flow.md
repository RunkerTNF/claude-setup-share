# Setup Flow

The repository checkout is only bootstrap media. A successful global install
places the persistent manager and management skills under `~/.agents/`; the
checkout may then be removed.

## 1. Resolve the manager

Prefer the `agent-workflow` executable on `PATH`. If it is unavailable, invoke
`~/.agents/workflow/agent-workflow.pyz` with Python 3.11 or newer.

Use the resolved command consistently for detection, preview, apply, and
doctor.

## 2. Detect without writing

Run `setup detect` for the requested scope. Show every detected adapter,
availability warning, and explicitly supplied adapter package. Ask the user
which target agents to configure.

For project scope, also establish:

- the repository root;
- the `local`, `shared`, or `split` storage profile;
- whether `.syncprotect` should be managed.

Global scope does not accept a project profile. Project scope requires a Git
repository and a profile.

## 3. Materialize and show a preview

Run `setup preview` and save its JSON plan to a user-visible temporary path.
Present:

- scope, profile, and selected targets;
- trust warnings and unavailable capabilities;
- blocking conflicts;
- every exact destination and operation.

For the first global install or a global upgrade, `--source-root` must point to
the bootstrap checkout. Project setup uses the already installed global
manager and canonical skills.

If preview reports conflicts, stop. Do not edit the materialized plan or work
around ownership checks.

## 4. Confirm and apply the exact plan

Ask for explicit confirmation that names the scope and selected targets. Then
run `setup apply --plan <previewed-plan>`. Use `--yes` only after that
confirmation.

Never substitute a newly generated plan after confirmation. If requirements
change, create and present a new preview.

## 5. Verify

Run `doctor --scope global` for a global install. For project scope, run
`doctor --scope project` from the repository. Report:

- doctor findings;
- transaction journal and rollback location;
- installed neutral paths;
- a new-session smoke check for each selected agent.

Setup never imports or deletes legacy content. Use the migration skill when
existing rules, skills, commands, memory, sessions, or native settings must be
unified.
