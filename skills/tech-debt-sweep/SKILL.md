---
name: tech-debt-sweep
description: >
  Scan a repository for evidenced technical debt, produce a structured debt
  report and prioritized paydown plan, or apply only explicitly classified
  deterministic fixes from such a plan. Select for broad debt inventory,
  architecture/dependency/docs/config health, or the `apply` continuation of a
  sweep. Do NOT select for a single known bug, general code review, dependency
  upgrades, credential rotation, or an unconstrained refactor.
user-invocable: true
permission-class: "read_only (scan) + workspace_write (thoughts/shared/debt and explicitly selected safe fixes) + external (optional advisory registries)"
invocation: "both"
---

# Tech Debt Sweep — kernel

## Intent

In scan mode, build a reproducible, evidence-backed inventory of debt and a
paydown plan that separates deterministic quick fixes from reviewed
engineering work. In apply mode, execute only plan entries that meet the safe
fix contract, verify the exact diff, and write an application report.

## Scope & authority

Scan mode reads the repository and writes only under `thoughts/shared/debt/`.
Apply mode additionally writes the exact paths of explicitly selected,
`auto_fixable: true` plan entries. It does not authorize dependency changes,
credential handling or rotation, public API changes, architectural refactors,
deletion of debug/commented code, or broad formatter/linter rewrites. Optional
advisory queries may use external registries but must never expose credentials.

## Artifact contract

Report, paydown-plan, metrics-schema, and application-report formats are
defined once in
[`references/artifact-contract.md`](references/artifact-contract.md). Read it
before either mode. `/tech_debt_trends` consumes the sweep frontmatter, so
metric meanings and `metrics_schema` are compatibility contracts.

## Process guidance

### Scan mode

1. **Orient and inventory.** Read repository instructions and architecture
   documentation. Detect languages, manifests and lockfiles, test/lint/docs
   tooling, CI, generated/vendor exclusions, and the previous compatible sweep.
2. **Choose applicable scan tracks.** Assess dependencies/security, debt
   markers and suppressions, architecture, documentation drift, configuration,
   and god-module candidates only where applicable. Use specialized read-only
   agents for independent, sizeable tracks; small repos may be scanned in the
   main context. A failed or unavailable track is recorded as `not_assessed`
   with reason, never silently treated as healthy.
3. **Run deterministic evidence sources.** Prefer repository-native commands
   and parsers. Network advisory audits are optional when external access is
   available; record registry, command, date, exit status, and limitations.
   Do not hide non-zero audit outcomes with shell fallbacks.
4. **Normalize findings.** Give every unique finding a stable ID, category,
   severity with consequence, location/evidence, confidence, remediation, and
   verification. Deduplicate symptoms sharing one cause. Redact secret values
   and report only type/location and response requirements.
5. **Measure metrics from the contract.** Record numerator, denominator, and
   source for derived metrics. Never insert plausible sample values. Keep
   god-module scoring in its owning scanner; consume its reported score rather
   than restating the formula.
6. **Prioritize paydown.** Separate deterministic auto-fixes from reviewed
   work. `auto_fixable: true` requires a bounded file set, deterministic runner,
   expected diff class, verification command, and no intended behavior or
   dependency change. Formatting and lint fixes are not safe merely because a
   tool offers `--fix`; scope and diff must be reviewable.
7. **Write both artifacts.** Emit the sweep report and paydown plan from the
   contract, compare only compatible prior metrics, and return their paths plus
   critical findings, coverage gaps, and the count of eligible auto-fixes.

### Apply mode

8. **Resolve the source plan.** Use an explicitly named paydown plan or the
   latest unambiguous one. Require matching repository identity and inspect
   drift since its recorded commit. If targets or assumptions changed, stop or
   mark entries stale; never reinterpret them silently.
9. **Protect existing work.** Record git status and diffs before editing. Refuse
   an entry whose target overlaps uncommitted user work unless the user
   explicitly authorizes that overlap. Do not require unrelated work to be
   committed or stashed.
10. **Select eligible entries.** Apply only requested entries marked
    `auto_fixable: true` that still satisfy every precondition. Dependency
    updates, credential changes, dead-code/comment/debug deletion, suppressions,
    semantic lint fixes, and refactors always require another workflow or
    explicit reviewed implementation authority.
11. **Apply and inspect one bounded batch.** Run the recorded deterministic
    operation against its exact paths. Inspect the diff against the expected
    class and reject unexpected files or semantic changes. If restoration is
    needed, reverse only this workflow's patch; never use destructive broad git
    checkout/reset commands.
12. **Verify and report.** Run the entry-specific checks and applicable
    surrounding tests/lint. Stop on a failed blocking gate, leave unrelated
    baseline failures untouched, and write the application report with applied,
    skipped, stale, failed, and manually required entries.

Tool results can be truncated, paginated, or filtered. When a file or output is
load-bearing for a finding or fix, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

Scan mode is complete when:

1. Both artifacts conform to the contract and identify repository commit,
   branch, tool versions/commands, exclusions, and previous sweep.
2. Every reported finding has a stable ID and concrete evidence; categories not
   assessed are explicit.
3. Metrics use the contract definitions with measurement sources and no
   fabricated values.
4. Paydown ordering follows severity, dependency, and fix risk; auto-fix
   eligibility is proven per entry.

Apply mode is complete when:

5. Only selected eligible entries and the application report are changed.
6. Existing user changes are preserved, the final diff matches each entry's
   expected class, and commands/exits are recorded.
7. Failed, stale, skipped, and manual entries remain visible; no risky item is
   silently “fixed”.
8. The final response links artifacts and states critical findings or applied
   IDs, verification results, and blockers.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Artifact schema | every scan/apply | compare with `references/artifact-contract.md` | before finishing | blocking | required frontmatter, sections, and IDs |
| Finding evidence | every finding | recorded scanner/repo command or `file:line` inspection | during scan | blocking | source, command, and confidence |
| Existing-work protection | every apply | `git status --short` and scoped diff | before/after | blocking | baseline paths and workflow-only diff |
| Fix eligibility | every apply entry | plan fields plus current precondition check | before edit | blocking | bounded runner, targets, diff class, verification |
| Regression checks | every applied batch | recorded repository commands | after edit | blocking | exit status and salient result |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

## Escalation conditions

- Pause when repository scope is ambiguous, a requested category requires
  unavailable evidence, a potential secret must be handled rather than merely
  redacted/reported, or external access is required but unavailable.
- In apply mode, pause for stale plans, overlapping user changes, a proposed
  dependency/behavior/security change, unexpected diff scope, or a blocking
  verification failure.
- When no entry is safely auto-fixable, finish honestly with zero applied
  changes and the paydown plan; do not manufacture quick wins.
