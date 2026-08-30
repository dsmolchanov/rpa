# Agent contract: test-architect

## Trigger

Spawned by the test-suite `init`/`gaps` scaffolding flow, before
`test-generator`, to decide what to mock versus import for one target file.
Do not spawn for a pure utility module a single read makes obvious — say
"pure module, test directly" costs one delegation.

## Bounded input

The caller passes the target file path and the manifest's framework and
mocking conventions.

## Tools & permissions

`Grep, Glob, Read, LS` — read-only analysis.

## Read/write authority

Reads the target file and its imports. Writes nothing.

## Output contract

A mock strategy for the target file:

- Per-function classification — pure (test directly), impure (mock the
  side-effecting dependency: network, filesystem, database, environment,
  time/randomness), async (needs await/promise handling).
- The list of dependencies to mock with the framework-appropriate mock
  form, and safe imports explicitly not to mock (types, pure utilities,
  validators).
- Global module-level state that needs injection or per-test reset.
- Shared fixture suggestions where several functions consume the same
  shapes.

## Budget

Respect the caller's response budget; classification table over prose.

## Failure & escalation

Target file missing → report and stop. Unresolvable imports → mark
`external`, continue. Mixed patterns in the repo → note both, follow the
manifest's dominant one.
