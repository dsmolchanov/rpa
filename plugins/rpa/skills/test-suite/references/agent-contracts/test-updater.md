# Agent contract: test-updater

## Trigger

Spawned by the test-suite `update` mode to categorize how source changes
affect existing tests. Do not spawn for framework migration (that is
`test-refactorer`) or to create tests for new code (that is the
init/gaps flow).

## Bounded input

The caller passes the changed-file list (with git status letters) and the
manifest's source-to-test mapping.

## Tools & permissions

`Grep, Glob, Read, LS` — read-only; the orchestrating workflow applies
changes in apply mode.

## Read/write authority

Reads changed sources (old versions via the caller-provided diff context),
their tests, and the manifest. Writes nothing.

## Output contract

A categorized update plan with per-change diffs:

- **Safe (non-behavioral)** — file renames/moves (imports), function and
  parameter renames, export-style changes: exact diff, auto-applicable.
- **Requires approval (behavioral)** — assertion value changes, expected
  error changes, snapshot updates, new required parameters, return-type
  changes: the source change, the proposed test diff, and the open
  question, one item per decision.
- **Deletions** — tests for removed code, with options (delete / keep
  skipped / keep as regression), never marked auto-applicable.

Preserving test intent is the invariant: a change that could alter what
the test asserts is never categorized safe.

## Budget

Respect the caller's response budget; unchanged sections stay out of
diffs.

## Failure & escalation

No test file for a changed source → skip it (no update needed). A refactor
too tangled to categorize confidently → flag the file for manual review
rather than guessing categories.
