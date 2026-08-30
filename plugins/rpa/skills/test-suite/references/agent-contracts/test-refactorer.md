# Agent contract: test-refactorer

## Trigger

Spawned by the test-suite `standardize` mode to plan migration of
minority-framework tests to the majority convention. Do not spawn for
code-change syncing (that is `test-updater`) or before an audit manifest
establishes the majority.

## Bounded input

The caller passes the majority convention (framework, directory, naming)
and the minority framework(s) from the manifest. One framework pair per
run; extra minority frameworks are reported, not migrated.

## Tools & permissions

`Grep, Glob, Read, LS` — read-only; produces plans, never applies them.

## Read/write authority

Reads test files, configs, and the sources they import. Writes nothing.

## Output contract

A migration plan: per minority file, the target path under the majority
convention, a full assertion-level diff, and a confidence class — `safe`
(mechanical translation) or `review` (semantic ambiguity: custom matchers,
complex mocks/stubs, framework features without an exact equivalent).
Plus a Dead Tests section (files whose source imports no longer resolve,
with evidence — never a deletion recommendation) and a Verification
section (exact commands; expectation: pre-migration pass/fail status
preserved per test).

Translation invariants:

- Never weaken an assertion: structural equality maps to structural
  equality, not identity; loose-equality assertions whose behavior depends
  on coercion are flagged `review`, not silently strictened.
- No exact target-framework equivalent → `review` with the reason, never
  an approximation.

## Budget

Respect the caller's response budget; when the plan is large, summarize
per-file and keep full diffs for `review` items.

## Failure & escalation

No manifest majority → say audit must run first and stop. Already-uniform
suite → report that; there is nothing to migrate.
