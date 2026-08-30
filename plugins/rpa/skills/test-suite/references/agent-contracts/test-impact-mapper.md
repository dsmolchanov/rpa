# Agent contract: test-impact-mapper

## Trigger

Spawned by the test-suite `gaps` (static analysis) and `update` (impact
tracing) modes. Do not spawn when runtime coverage data should answer the
question (that is `coverage-reporter`) or for a single file one direct
grep settles.

## Bounded input

The caller passes either the changed-file list (impact tracing) or the
analysis scope (gap detection), plus the manifest's test patterns.

## Tools & permissions

`Grep, Glob, Read, LS` — read-only static analysis.

## Read/write authority

Reads source, tests, and git metadata the caller provides. Writes nothing.

## Output contract

- **Impact tracing**: changed files mapped to their direct tests and to
  tests reached through the import chain (state the depth actually
  traced), plus the evidenced command to run exactly that set.
- **Gap detection**: source files without tests, exported symbols
  unreferenced by any test, untested error paths (throw/catch/null
  returns), and high fan-in modules with thin coverage — each entry with
  `file:line` or file-level evidence and a qualitative high/medium/low
  priority justified by that evidence (criticality, fan-in, churn,
  security relevance, test absence). No numeric scores.

## Budget

Respect the caller's response budget; prioritize high-priority findings
when trimming.

## Failure & escalation

No git history → analyze current state only and say so. Dynamic imports →
flag "may have additional impacts". Monorepo → scope to the named package.
Never present a heuristic estimate as measured coverage.
