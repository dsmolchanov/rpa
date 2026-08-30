---
name: tdd
description: >
  Execute a feature-scoped Red-Green-Refactor cycle from a test plan, creating
  tests, implementing the required behavior, and preserving green tests through
  justified cleanup. Select when the user asks to implement through TDD or run
  a named TDD phase. Do NOT select to write only a test strategy, repair an
  unrelated failing suite, add repo-wide coverage, or perform an unconstrained
  refactor; use create-test-plan, debug, test-suite, or refactor
  instead.
user-invocable: true
permission-class: "workspace_write (plan-scoped source, tests, thoughts/shared/tests session log and receipts, thoughts/shared/one-pagers digest, .rpa/evidence local state)"
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

Read the named test plan and repository. Write only the source, tests, and
fixtures needed for cases in that plan and the requested phase, the session log
and its receipt export under `thoughts/shared/tests/`, and the local evidence
store under `.rpa/evidence/` (never committed; nothing else under `.rpa/`).
Preserve pre-existing user changes and unrelated failures. Do not add
dependencies, broaden product behavior, weaken assertions, alter project-wide
quality thresholds, or commit/push unless separately authorized.

## Artifact contracts

- Consume the test-plan shape from
  [`../create-test-plan/references/artifact-contract.md`](../create-test-plan/references/artifact-contract.md).
- Maintain the evidence log defined by
  [`references/session-log-contract.md`](references/session-log-contract.md).
- Produce receipts with the evidence kernel defined by
  [`references/evidence-contract.md`](references/evidence-contract.md).
  `<skill-dir>` is the directory containing this file; the tool is
  `python3 <skill-dir>/scripts/evidence.py` and the log validator is
  `python3 <skill-dir>/scripts/validate_session_log.py`.
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
   duplicates, pre-existing failures, or missing prerequisites. If a session
   log for this plan already exists, `evidence.py begin --resume <its Evidence
   run>`; otherwise `evidence.py begin --plan <test plan>`. Then
   `evidence.py checkpoint baseline`.
3. Continue without ritual phase confirmations while work remains within the
   user's requested phase and plan scope. Pause only under the escalation rules.

### Red

4. Create or update only the planned test files, fixtures, and helpers. Follow
   local conventions and assert observable behavior rather than implementation
   structure. Preserve stable case IDs from the test plan where the framework
   permits comments or names.
5. Run the narrowest command that executes each new case **through the
   kernel**: `evidence.py run --phase red --case <id> --scope red_inputs=<tests,
   fixtures, helpers, runner config, lockfiles> --scope plan=<test plan>
   --report <name>` with `{report}` in the argv when the stack emits JUnit, and
   the plan's `test <selector> fail-with "<literal>"` claim (or its stand-in
   pair). A valid Red result is a receipt with `outcome=PASS`: the test failed
   because the specified behavior is absent or incorrect. `ERROR` or
   `SURPRISE` means import, syntax, environment, discovery, or fixture failure
   — infrastructure defects: fix those until the test reaches the intended
   assertion. It is acceptable for unaffected or already-implemented cases to
   pass; explain duplicates or drift rather than forcing artificial failure.
6. Cite the receipt in the log. If every new assertion already passes, verify
   the test is meaningful and whether the behavior already exists; do not
   sabotage production code to manufacture Red. `evidence.py checkpoint red`
   (again after any re-run Red).

### Green

7. Green requires valid Red evidence for each newly implemented behavior,
   either from this session or an auditable prior phase — concretely, a `PASS`
   Red receipt in the same evidence run; Green runs pass `--phase green --case
   <id> --requires <Red ref>`. Implement the smallest
   **correct, general** behavior that satisfies the agreed requirement and
   repository contracts. Do not hard-code a one-example answer, omit necessary
   validation, or introduce speculative extras simply because the current test
   set is small.
8. Run the focused cases after each coherent implementation chunk, then the
   relevant surrounding suite. Distinguish failures introduced by the change
   from unrelated baseline failures; never weaken or delete an assertion just
   to reach Green. A `STALE` result means the Red inputs, plan, branch, or
   `HEAD` changed since Red (or during the run): re-run Red and re-checkpoint
   it; do not edit the claim to fit.
9. Green is reached only when planned cases pass and no relevant previously
   passing case regresses. Cite the receipts, then `evidence.py checkpoint
   green`.

### Refactor

10. Refactor requires a green baseline; refactor runs pass `--phase refactor
    --case <id> --requires <Green ref>`. Apply only evidence-backed improvements
    within touched code: duplication, boundary clarity, naming, cohesion, or
    maintainability issues that materially benefit the change. A refactor phase
    may legitimately be `not_applicable` when Green code is already clear.
11. Keep behavior and public contracts stable. Verify after each coherent
    refactor batch with the narrow suite, then re-run the relevant surrounding
    suite. If a change breaks tests, diagnose from the diff and restore behavior
    with a targeted patch; never discard unrelated work with destructive git
    commands. `evidence.py checkpoint refactor` when the batch is green.

### Completion

12. Run all applicable plan gates, including coverage only when the repository
    or test plan defines a threshold. Coverage is supporting evidence, not a
    substitute for behavior and failure-mode coverage. Do not invent an 80%
    target, timing limit, or flake threshold.
13. Final-verification runs use `--phase final`. When the cycle ends
    (Refactored Green, Green with Refactor not applicable, or Blocked),
    `evidence.py checkpoint final --achieved <phase>`. In **every** session:
    `evidence.py export`, finish the session log with actual transitions,
    files, receipts, deviations, `not_applicable` outcomes, and `**Cycle
    state**`, then run `validate_session_log.py <log>`. Finally refresh the
    repository's digest with `python3 <one-pager skill-dir>/scripts/onepager.py generate --write` — the session log it just wrote is
    uncommitted, and the digest is what makes it visible to the next session.
    A refresh that fails is reported and never blocks the session or alters
    the log. Return a concise result with changed files, phase state,
    verification evidence, and remaining blockers.

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
5. Only plan-scoped files, the session log, its receipt export, and the
   repository's one-pager digest are changed; the local evidence store is not
   committed; pre-existing user changes remain intact.
6. Commands, exit statuses, and outputs are persisted by the kernel in the
   receipt export — never transcribed into the log; the log cites receipts
   and salient outcomes; counts, coverage, duration, and LOC are never
   guessed.
7. The final response links the session log and states the achieved phase,
   verification results, deviations, and blockers.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Baseline protection | every session | `git status --short` plus target diff inspection | before and after edits | blocking | pre-existing vs session changes identified |
| Red causality | every new behavior | `evidence.py run --phase red --case <id>` with mandatory `red_inputs`/`plan` scopes and a `test … fail-with` claim or the stand-in pair | before Green | blocking | receipt ref with outcome PASS |
| Green regression | every Green/refactor phase | `evidence.py run --phase green --case <id> --requires <Red ref>` (refactor: `--phase refactor --requires <Green ref>`), focused tests plus relevant existing suite | after each coherent batch | blocking | receipt refs, outcome PASS, no STALE |
| Coverage policy | only when repo/plan defines a threshold | repository coverage command | at completion | blocking when policy says so | measured report and configured threshold |
| Recovery capsule | every phase boundary | `evidence.py checkpoint <phase>` | at each boundary | blocking | checkpoint record and capsule snapshot |
| Evidence export | every session | `evidence.py export` (after `checkpoint final` when the cycle ends) | before finishing | blocking | receipt file committed alongside the log |
| Session artifact | every session | `python3 <skill-dir>/scripts/validate_session_log.py <log>` | before finishing | blocking | exit status 0 |
| One-pager refresh | every session | `python3 <one-pager skill-dir>/scripts/onepager.py generate --write` | after the session log validates | advisory | digest path printed |
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
- Stop and report when `run` returns `STALE` twice for the same Red ref without
  an intervening test/plan edit you made — the scope declaration is wrong, not
  the code.
- Stop when `run` returns `STALE` with `drift during execution` — the command
  mutates its own inputs.
- Stop when `run` returns `TIMEOUT` or `INTERRUPTED` for a command that should
  be fast — do not raise `--timeout` to hide a hang.
- Stop when `run` reports `execution in progress` and you did not start it —
  another session holds the lease.
