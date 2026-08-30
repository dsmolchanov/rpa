---
name: test-suite
description: >
  Create, update, and maintain a repository's test suites through eight
  modes — audit, adopt, init, update, gaps, run, ci, standardize — planning
  by default and applying changes only with `apply`. Select when the user
  asks to audit test infrastructure, harmonize or scaffold tests, sync tests
  with code changes, find coverage gaps, execute the suite, generate CI test
  configuration, or migrate fragmented suites. Do NOT select to implement a
  feature through TDD, write a feature-scoped test strategy, or investigate
  one failing test; use tdd, create-test-plan, or debug instead.
user-invocable: true
permission-class: "workspace_write (thoughts/shared/test-suite artifacts; with apply: plan-listed tests, fixtures, named test config, or one selected CI file)"
invocation: "both"
---

# Test Suite — kernel

## Intent

Keep a repository's test infrastructure healthy end to end: detect it,
harmonize fragmented suites, scaffold missing tests, sync tests with code
changes, surface coverage gaps, execute suites, and generate CI wiring —
always through reviewable plan artifacts, never through silent mutation.

## Scope & authority

The mode is the first `$ARGUMENTS` token. `apply` extends authority only as
this matrix states; a path class not listed for the mode is out of scope and
stops for a decision rather than being written.

| Mode | Without `apply` | With `apply` |
|---|---|---|
| `audit` | refresh the manifest pair under `thoughts/shared/test-suite/` | n/a — `audit` rejects `apply` |
| `adopt` | write the harmonization plan | additionally write plan-listed wrapper scripts, marked script blocks, and Makefile targets; never move or rewrite test files |
| `init` | write the init plan | additionally create plan-listed test files and fixtures |
| `update` | write the update plan | additionally apply only the plan's safe (non-behavioral) updates |
| `gaps` | write the gap report | additionally create plan-listed test scaffolds for top gaps |
| `run` | execute the manifest's evidenced test command and report; no persisted artifact | n/a |
| `ci` | write the CI plan | additionally write the one explicitly selected CI file |
| `standardize` | write the migration plan | additionally apply only `safe` migrations |

Cross-mode invariants:

- Assertion meaning, expected values or errors, snapshot updates, and test
  deletions always require an explicit per-item user decision; `apply` alone
  is never consent for them.
- Every non-`audit` mode requires a current manifest at
  `thoughts/shared/test-suite/test-suite-manifest.json` (currency is
  defined by the artifact contract's `commit` ancestry rule). If it is
  missing or stale, direct the user to run `audit`; no other mode silently
  refreshes it.
- `init` on a repository that already has tests produces an adopt plan and
  says why, instead of scaffolding duplicates.
- The legacy `init --force` overwrite flag is retired: reject it and point
  to reviewing the init plan, then `init apply`.
- `ci` resolves its provider from an explicit `--github`/`--gitlab` flag or
  from exactly one provider evidenced by existing repository CI files; with
  none or both, stop and ask — never invent a platform.
- No mode writes product source code.
- A same-day artifact whose content would differ from an existing one stops
  for an explicit decision (identical content is an idempotent no-op).

## Artifact contracts

- Every persisted artifact family is defined once in
  [`references/artifact-contract.md`](references/artifact-contract.md).
- Coverage thresholds are resolved by
  [`references/coverage-policy.md`](references/coverage-policy.md); no
  default percentage exists.
- Each mode's procedure lives in `references/modes/<mode>.md`. Read the
  selected mode's file and the artifact sections it names before acting.
- Use [`../../docs/testing-patterns.md`](../../docs/testing-patterns.md)
  for language-appropriate test shapes when the repository has no nearer
  established pattern.

## Process guidance

1. Parse the mode and options from `$ARGUMENTS`. An unknown mode or option,
   `apply` on `audit`/`run`, or a bare invocation prints usage and makes no
   repository inspection.
2. Read the selected mode reference. Delegate to the test agents it names
   (their contracts live under `references/agent-contracts/`); run
   `test-architect` before `test-generator` for the same file — generation
   consumes the mock strategy. Do not delegate what a couple of direct tool
   calls settle.
3. Test execution belongs to this workflow, not to agents: run the
   manifest's evidenced command yourself, capture output to a log, and
   digest large logs through `file-analyzer` instead of reading them into
   the main context.
4. Report artifact paths and measured findings. Never invent counts,
   coverage numbers, thresholds, runtimes, or platform choices.

## Acceptance criteria & evidence

A mode invocation is complete when:

1. The mode's artifact exists at its contract path (or, for `run`, results
   are reported) with only the authority matrix's paths touched.
2. Findings cite evidence: `file:line` references, executed commands with
   exit status, or manifest fields — no fabricated metrics.
3. Approval-class items (assertions, snapshots, deletions) are listed
   individually and none was applied without an explicit decision.
4. The final response names the artifact, the mode's key findings, and the
   follow-up mode when one naturally applies.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Manifest validity | every `audit` | JSON parse + required fields per artifact contract | before writing the Markdown projection | blocking | valid JSON, fields present |
| Apply scope | every `apply` | compare written paths against the plan and authority matrix | after writing | blocking | written-path list |
| Suite execution | `run`, and post-apply verification in `init`/`update`/`standardize` | the manifest's evidenced test command | after changes | blocking | exit status and parsed counts |
| Docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

For a gate that does not apply, report `not_applicable` with the reason.

## Escalation conditions

- Continue while actions stay inside the selected mode's authority.
- Stop for one focused decision on: approval-class items; an ambiguous or
  dual CI provider; a same-day artifact collision; migration items marked
  `review`; dead tests (never auto-delete); or a coverage policy conflict
  per the coverage-policy reference.
- If the repository's actual test behavior contradicts the manifest,
  re-run `audit` before acting on stale data.
