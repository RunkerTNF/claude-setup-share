# Setup Flow

1. Run the manager's `scan --agents --json` command.
2. Show detected targets and every explicitly supplied adapter package. Ask
   the user to choose the target agents.
3. For a project setup, ask the user to choose `local`, `shared`, or `split`
   storage and whether an existing sync-protection file should be managed.
4. Run `plan setup` and present the complete plan, including trust warnings,
   conflicts, and every affected file.
5. Obtain explicit confirmation before running `apply`.
6. Run `doctor` against the installed neutral scope.
7. Report the new-session smoke steps for every selected target.

Treat an unavailable selected adapter as a warning. Treat a missing or drifted
generated entrypoint as a conflict. Never scan arbitrary plugin or download
directories and never perform network access as part of setup.
