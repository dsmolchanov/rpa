---
name: tdd
description: >
  Execute a feature-scoped Red-Green-Refactor cycle from a test plan, creating
  tests, implementing the required behavior, and preserving green tests through
  justified cleanup. Select when the user asks to implement through TDD or run
  a named TDD phase. Do NOT select to write only a test strategy, repair an
  unrelated failing suite, add repo-wide coverage, or perform an unconstrained
  refactor; use create-test-plan, debug/test-runner, test-suite, or refactor
  instead.
user-invocable: true
permission-class: "workspace_write (plan-scoped source, tests, and thoughts/shared/tests session log)"
invocation: "both"
---

# TDD — kernel

## Intent

Implement the behavior described by a test plan through evidence-bearing
Red-Green-Refactor transitions. A valid Red state proves the new behavioral
assertion can fail for the expected missing behavior; Green satisfies it with
the smallest correct implementation; Refactor improves structure without
changing behavior.

## Scope & authority

Read the named test plan and repository. Write only the source, tests, fixtures,
and session artifact needed for cases in that plan and the requested phase.
Preserve pre-existing user changes and unrelated failures. Do not add
dependencies, broaden product behavior, weaken assertions, alter project-wide
quality thresholds, or commit/push unless separately authorized.

## Artifact contracts

- Consume the test-plan shape from
  [`../create-test-plan/references/artifact-contract.md`](../create-test-plan/references/artifact-contract.md).
- Maintain the evidence log defined by
  [`references/session-log-contract.md`](references/session-log-contract.md).
- Use [`../../docs/testing-patterns.md`](../../docs/testing-patterns.md) for
  language-appropriate test shapes when the repository itself has no nearer
  established pattern.

Read the applicable contracts before editing.

## Process guidance

### Entry and baseline

1. Require a test-plan path. Phase defaults to `full`; valid explicit phases
   are `red`, `green`, and `refactor`. Read the complete plan and applicable
   repository instructions.
2. Inspect git status, target implementation/tests, installed test stack, and
   exact commands. Map each planned case to current behavior and note drift,
   duplicates, pre-existing failures, or missing prerequisites.
3. Continue without ritual phase confirmations while work remains within the
   user's requested phase and plan scope. Pause only under the escalation rules.

### Red

4. Create or update only the planned test files, fixtures, and helpers. Follow
   local conventions and assert observable behavior rather than implementation
   structure. Preserve stable case IDs from the test plan where the framework
   permits comments or names.
5. Run the narrowest command that executes each new case. A valid Red result
   must fail because the specified behavior is absent or incorrect. Import,
   syntax, environment, discovery, or fixture failures are infrastructure
   defects: fix those until the test reaches the intended assertion. It is
   acceptable for unaffected or already-implemented cases to pass; explain
   duplicates or drift rather than forcing artificial failure.
6. Record command, exit status, and the expected failure signal. If every new
   assertion already passes, verify the test is meaningful and whether the
   behavior already exists; do not sabotage production code to manufacture Red.

### Green

7. Green requires valid Red evidence for each newly implemented behavior,
   either from this session or an auditable prior phase. Implement the smallest
   **correct, general** behavior that satisfies the agreed requirement and
   repository contracts. Do not hard-code a one-example answer, omit necessary
   validation, or introduce speculative extras simply because the current test
   set is small.
8. Run the focused cases after each coherent implementation chunk, then the
   relevant surrounding suite. Distinguish failures introduced by the change
   from unrelated baseline failures; never weaken or delete an assertion just
   to reach Green.
9. Green is reached only when planned cases pass and no relevant previously
   passing case regresses. Record exact commands and outcomes.

### Refactor

10. Refactor requires a green baseline. Apply only evidence-backed improvements
    within touched code: duplication, boundary clarity, naming, cohesion, or
    maintainability issues that materially benefit the change. A refactor phase
    may legitimately be `not_applicable` when Green code is already clear.
11. Keep behavior and public contracts stable. Verify after each coherent
    refactor batch with the narrow suite, then re-run the relevant surrounding
    suite. If a change breaks tests, diagnose from the diff and restore behavior
    with a targeted patch; never discard unrelated work with destructive git
    commands.

### Completion

12. Run all applicable plan gates, including coverage only when the repository
    or test plan defines a threshold. Coverage is supporting evidence, not a
    substitute for behavior and failure-mode coverage. Do not invent an 80%
    target, timing limit, or flake threshold.
13. Finish the session log with actual transitions, files, commands, exit
    statuses, deviations, and `not_applicable` outcomes. Return a concise result
    with changed files, phase state, verification evidence, and remaining
    blockers.

Delegation is optional and limited to independent, sizeable analysis or
generation tracks. The orchestrator owns edits, phase evidence, and final
verification; it checks agent output against the plan and repository before
applying it.

Tool results can be truncated, paginated, or filtered. When a file or output is
load-bearing for a phase decision, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The requested TDD scope is complete when:

1. Every executed planned case has a recorded disposition: valid Red, Green,
   refactored-green, already covered, blocked, or `not_applicable` with reason.
2. Red failures reach the intended behavioral assertion rather than failing on
   infrastructure.
3. Green implements the agreed behavior without weakening tests or regressing
   the relevant existing suite.
4. Refactoring, when applicable, preserves behavior and public contracts.
5. Only plan-scoped files and the session log are changed; pre-existing user
   changes remain intact.
6. Commands, exit statuses, and salient outcomes are recorded exactly; counts,
   coverage, duration, and LOC are never guessed.
7. The final response links the session log and states the achieved phase,
   verification results, deviations, and blockers.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Baseline protection | every session | `git status --short` plus target diff inspection | before and after edits | blocking | pre-existing vs session changes identified |
| Red causality | every new behavior | narrow repository test command | before Green | blocking | non-zero exit and expected assertion failure |
| Green regression | every Green/refactor phase | focused tests plus relevant existing suite | after each coherent batch | blocking | commands, exits, test summary |
| Coverage policy | only when repo/plan defines a threshold | repository coverage command | at completion | blocking when policy says so | measured report and configured threshold |
| Session artifact | every session | compare with `references/session-log-contract.md` | before finishing | blocking | phase evidence and dispositions present |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

## Escalation conditions

- Pause when the plan is missing or materially ambiguous, planned work requires
  a new dependency or wider production scope, a test contradicts the agreed
  requirement, or an external/irreversible action lacks authority.
- Stop before Green when Red cannot reach the intended assertion after bounded
  infrastructure diagnosis; report the blocker and evidence.
- Stop before Refactor when the relevant suite is not green.
- If unrelated baseline failures exist, continue only when the requested phase
  can be isolated safely; report them without repairing out-of-scope code.
