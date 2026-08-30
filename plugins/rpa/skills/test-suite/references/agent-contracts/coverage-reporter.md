# Agent contract: coverage-reporter

## Trigger

Spawned by the test-suite `gaps --runtime` flow (and other callers with
coverage data) to parse coverage backend output. Do not spawn without
coverage data on disk — it parses, it does not run tests — and not for
static gap analysis (that is `test-impact-mapper`).

## Bounded input

The caller passes the coverage output location (from the manifest) and the
resolved threshold context per `../coverage-policy.md`, when one exists.

## Tools & permissions

`Glob, Grep, Read, LS` — read-only parsing.

## Read/write authority

Reads coverage output (Istanbul/nyc summaries and lcov, pytest-cov
XML/JSON, go coverprofiles, tarpaulin reports) and, for trend context,
prior reports the caller names. Writes nothing; the orchestrating workflow
persists any report.

## Output contract

Structured measured data: overall and per-file line/function/branch
percentages as parsed; uncovered regions with `file:line` ranges;
threshold status only against the caller-resolved policy, citing its
source. With no resolved threshold, coverage is reported as data with
`threshold: not_applicable — no configured threshold` — no default value
exists. Trends only when prior reports were provided.

## Budget

Respect the caller's response budget; summarize per-file detail beyond the
worst offenders.

## Failure & escalation

No coverage data found → "no coverage data available — run the coverage
command first"; never estimate. Unknown format → best-effort parse with
the uncertainty stated. Missing history → omit trends.
