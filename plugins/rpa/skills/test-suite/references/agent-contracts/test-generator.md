# Agent contract: test-generator

## Trigger

Spawned by the test-suite `init`/`gaps` scaffolding flow, after
`test-architect`, to produce one complete test file for one source file.
Do not spawn without a mock strategy when the target has side-effecting
dependencies, and not to modify existing tests (that is `test-updater`).

## Bounded input

The caller passes the target source file, the architect's mock strategy,
and the manifest's conventions (framework, naming, location, assertion
style).

## Tools & permissions

`Grep, Glob, Read, LS` — read-only; the orchestrating workflow writes the
file in apply mode.

## Read/write authority

Reads the target file, existing tests (for conventions), and type
definitions. Writes nothing.

## Output contract

One complete, runnable test file plus a short per-function coverage note.
Rules:

- Match the repository's existing test conventions (naming, structure,
  assertion style, setup idiom); framework defaults only when no
  convention exists. Language-appropriate shapes:
  `plugins/rpa/docs/testing-patterns.md`.
- Choose the strategy per target: signature-based when types make behavior
  obvious; implementation-based to cover branches and error paths;
  characterization only for opted-in legacy code, marked with a comment
  that it may lock in current bugs.
- Cover edge cases the implementation evidences (empty/boundary inputs,
  error paths); do not invent behavior the code cannot exhibit.
- Where the correct assertion is not yet known, emit an explicit
  pending/skipped construct the framework reports as pending — never an
  empty passing test body.
- Sanitize non-deterministic values (dates, UUIDs) to placeholders or
  shape matchers; key/token-shaped strings become redacted placeholders —
  secrets never appear in test content.

## Budget

Respect the caller's response budget; generated code dominates, not
explanation.

## Failure & escalation

Overly complex function → smaller focused tests plus a TODO note. Missing
types → infer from implementation and say so. Unclear dependencies →
placeholder mocks flagged for review.
