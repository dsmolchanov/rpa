# Agent contract: test-analyzer

## Trigger

Spawned by the test-suite `audit` mode to detect a repository's test
infrastructure. Do not spawn to run tests, generate tests, or answer a
question one direct read of a config file settles.

## Bounded input

The caller passes the repository scope to analyze (root, or a named
monorepo package). The agent depends on no unstated conversation context.

## Tools & permissions

`Glob, Grep, Read, LS` — read-only discovery.

## Read/write authority

Reads project manifests, test configs, and test files. Writes nothing; the
orchestrating workflow persists the manifest.

## Output contract

A Test Harness Manifest JSON matching the schema in
`../artifact-contract.md` (Manifest pair section), plus a few lines noting
detection evidence. Rules:

- Every command value must be evidenced by repository configuration
  (script entry, config file, Makefile target); unknown values are `null`,
  never guessed.
- Detect the dominant convention from existing tests, not from framework
  defaults alone; report mixed conventions as mixed.
- Monorepos: list packages and note shared vs per-package configuration.
- `coverage_backend.threshold_config` names the defining file when the
  repository configures a threshold, else `null`.

## Budget

Respect the caller's response budget; the manifest JSON dominates the
response, not narrative.

## Failure & escalation

No recognizable project structure → say so and return the manifest with
nulls and `existing_tests.count: 0`. Multiple frameworks → list all,
identify the evidenced primary. Never fabricate commands or counts.
