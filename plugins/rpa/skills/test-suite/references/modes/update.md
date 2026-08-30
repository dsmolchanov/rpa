# Mode: update [apply]

Sync tests with code changes non-destructively.

## Categories

- **Safe (auto-applicable)** — non-behavioral: file renames/moves (import
  paths), function renames (test names and calls), parameter renames,
  export-style changes.
- **Requires approval** — potentially behavioral: assertion value changes,
  expected error/message changes, snapshot updates, new required
  parameters, return-type changes. Each is a separate decision; `apply`
  never covers them.
- **Deletions** — tests for removed code: listed with options
  (delete / keep skipped / keep as regression), never auto-applied.

## Procedure

1. Require a current manifest; identify changed files
   (`git diff HEAD~1 --name-status`, or the user-named range).
2. Delegate categorization to `test-updater` (per-change diffs, safe vs
   approval vs deletion) and impact tracing to `test-impact-mapper` (which
   tests should run afterwards). The two are independent — run in parallel.
3. Write the update plan per the artifact contract.
4. **apply**: apply only the plan's safe updates, re-present approval items
   individually, present deletions for confirmation, then run the impacted
   tests and report.

## Idempotency

Safe updates are no-ops when re-applied; approval items are re-presented
until resolved; deletions stay tracked, never auto-applied.
