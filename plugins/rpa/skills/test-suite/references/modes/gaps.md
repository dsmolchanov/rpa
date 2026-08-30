# Mode: gaps [--runtime] [apply]

Identify untested code. Default is static analysis (no coverage tooling
required); `--runtime` uses actual coverage data.

## Procedure

1. Require a current manifest; missing → direct to `audit`.
2. **Static**: delegate to `test-impact-mapper` — source files without
   tests, exported symbols unreferenced by tests, untested error paths,
   high fan-in modules with thin coverage.
3. **Runtime (`--runtime`)**: requires usable coverage data for the
   manifest's backend. Delegate parsing to `coverage-reporter`. If coverage
   output is missing or unparseable, report
   `not_available — run the coverage command first or use static gaps` and
   write nothing; do not silently fall back to static analysis.
4. Write the gap report per the artifact contract: qualitative high /
   medium / low priorities, each entry carrying its evidence (behavior
   criticality, import fan-in, recent change, security relevance, observed
   test absence or weakness). No numeric scores.
5. **apply**: for the report's high-priority gaps, scaffold tests via the
   init-mode delegation pattern (`test-architect` then `test-generator` per
   file), create the files, and report.

## Idempotency

The report is dated; re-running the same day with identical findings is a
no-op, and differing findings follow the same-day collision rule.
