# Mode: init [apply]

Scaffold tests for uncovered code following the manifest's conventions.

If the repository already has tests, do not scaffold duplicates: produce an
adopt plan instead (see `adopt.md`), say why, and name
`adopt apply --plan …` as the continuation. The legacy `--force` overwrite
flag is retired — reject it and point to reviewing the init plan, then
`init apply`.

## Procedure

1. Require a current manifest; missing or stale → direct to `audit`.
2. Find source files without tests by mapping sources to expected test
   locations per the manifest pattern; order candidates by export surface
   and import fan-in.
3. Per candidate file, delegate **sequentially**: `test-architect` first
   (mock strategy — pure/impure/async classification, dependencies to mock,
   global state), then `test-generator` consuming that strategy (complete
   test file following manifest conventions). Independent candidate files
   may run in parallel with each other.
4. Write the init plan per the artifact contract, with scaffold previews.
5. **apply**: create the plan's test files and fixtures, run the manifest's
   test command to verify the scaffolds compile and report as
   pending/skipped, and report results.

## Scaffold rules

- Scaffolds assert observable behavior where it is clear; otherwise they
  are explicit pending/skipped constructs the framework reports as pending.
  Never an empty test body that passes silently.
- Sanitize any snapshot-like values: dates, UUIDs, and key/token-shaped
  strings become placeholders or shape matchers — secrets never appear in
  test files.
- A characterization test (capturing current legacy behavior) is opt-in and
  carries a comment stating it may lock in existing bugs.
