# Mode: standardize [apply]

Migrate a fragmented suite (mixed frameworks, scattered conventions) to the
majority pattern the audit found.

## Procedure

1. Require a current manifest — standardize depends on the audit's
   majority evidence. If the suite is already uniform, report that and
   stop.
2. Delegate migration planning to `test-refactorer` (one framework pair per
   run): per minority file, a target path under the majority convention, an
   assertion-level diff, and a confidence class — `safe` (mechanical) or
   `review` (semantic ambiguity). It also flags dead tests (unresolvable
   source imports).
3. Write the migration plan per the artifact contract.
4. **apply**: apply only `safe` migrations (rewrite assertions, move
   files); present `review` items and dead tests for per-item decisions —
   never auto-delete. Run the migrated tests and compare with their
   pre-migration status; any test whose pass/fail status changed is
   reverted and flagged.

## Idempotency

Already-migrated files are detected via the manifest convention and
skipped; `review` items are re-presented until resolved; re-running after a
partial apply continues from the remaining minority files.
