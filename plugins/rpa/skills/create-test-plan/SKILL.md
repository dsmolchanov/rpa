---
name: create-test-plan
description: >
  Create a feature-scoped test and verification plan from an implementation
  plan, ticket, PR, or code path, grounded in the repository's real test stack
  and existing coverage. Select when the user wants risk-based test strategy
  or an executable Red-phase specification before implementation. Do NOT
  select to write or run tests, repair a failing suite, plan repo-wide coverage
  work, or implement the feature; use tdd, test-suite (run executes suites),
  or implement-plan instead.
user-invocable: true
permission-class: "read_only (target repo) + workspace_write (thoughts/shared/tests/ only)"
invocation: "both"
---

# Create Test Plan — kernel

## Intent

Produce a feature-scoped verification blueprint that tells an implementer what
behavior to test, at which boundary, with which real framework and fixtures,
and how to know the change is safe. The artifact specifies the Red phase but
does not create test files or execute the implementation cycle.

## Scope & authority

Read the supplied source of truth and repository. Write one plan under
`thoughts/shared/tests/`. Source code, tests, configuration, implementation
plans, and other artifacts are read-only. Repo-wide coverage remediation and
actual test generation are separate workflows.

## Artifact contract

The output path, required sections, case schema, and exit-criteria format are
defined once in
[`references/artifact-contract.md`](references/artifact-contract.md). Read it
before writing. `/tdd` consumes this shape; keep case identifiers, locations,
assertions, dependencies, and commands explicit.

## Process guidance

1. **Establish inputs.** Require a source of truth: implementation plan,
   ticket, PR context, or code path. Scope defaults to all applicable layers;
   honor an explicit `unit`, `integration`, or `e2e` limit and any environment,
   security, data, or cost constraints. If the source is missing, ask one
   focused question.
2. **Read and orient.** Read the complete source and applicable repository
   instructions. Extract required behavior, state transitions, failure modes,
   external boundaries, non-functional requirements, and compatibility or
   migration concerns.
3. **Run a repository-reality preflight.** Inspect manifests, lockfiles, test
   configuration, CI, representative tests, fixtures, and utilities. Record
   the actual framework and commands. Locate existing coverage so the plan
   proposes deltas rather than duplicates. Do not recommend a new dependency
   unless adding it is explicitly in scope.
4. **Model risk without a fake score.** For each material failure mode, state
   likelihood, impact, and consequence using evidence from the source and
   system boundaries. Use qualitative high/medium/low priority only when the
   reasoning is written beside it; do not invent numeric probabilities or a
   coverage target.
5. **Choose the lowest adequate test layer.** Put deterministic logic and
   state transitions in unit tests, real serialization/persistence/auth
   boundaries in integration tests, and only critical user journeys in E2E.
   Avoid testing framework guarantees or repeating the same assertion across
   layers without a distinct risk reason.
6. **Define boundaries and determinism.** Name which dependencies stay real
   and which are substituted, using mechanisms already present in the repo.
   Control time, randomness, identifiers, network, and cleanup. Prefer real
   boundary behavior in integration tests and avoid sleeps or live third-party
   calls.
7. **Specify an executable Red phase.** For every proposed case, give an ID,
   exact target file, behavior, setup/input, expected observable result,
   dependency or fixture needs, and applicable negative cases. Name new helper
   files and reuse existing builders explicitly.
8. **Define gates and handoff.** Use only discovered commands. Separate
   automated exit criteria from genuinely human exploratory checks, and state
   `not_applicable` with a reason for irrelevant layers or non-functional
   categories. Write the artifact and return its path plus the top risks and
   execution handoff.

Delegation is optional. Use specialized read-only analysis only for genuinely
independent, sizeable tracks such as test-infrastructure discovery, dependency
boundary analysis, or existing-coverage mapping. Small repositories and narrow
features stay in the main context; agent output is verified against source
before entering the plan.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for the plan, ensure you have seen all of it before relying on
it.

## Acceptance criteria & evidence

The workflow is complete when:

1. The test plan exists at the contract path and contains every required
   section.
2. Its repo-reality section cites the actual framework, commands, conventions,
   helpers, and relevant existing tests.
3. Every source requirement and material failure mode maps to coverage or an
   explicit evidence-backed exclusion.
4. Proposed cases have stable IDs, exact locations, observable assertions,
   setup, dependencies, and negative paths sufficient for an implementer to
   write failing tests without guessing.
5. Test-layer and mock/real-boundary choices are justified by risk and match
   installed tooling.
6. Exit criteria use real commands and measured project policy; no invented
   coverage percentage, flake threshold, or tool appears.
7. No source or test file is created or modified by this workflow.
8. The final response links the plan and summarizes top risks, chosen layers,
   and the recommended execution workflow.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Write boundary | every plan | inspect changed paths | before finishing | blocking | only one `thoughts/shared/tests/` artifact is added or updated |
| Artifact structure | every plan | compare against `references/artifact-contract.md` | before finishing | blocking | required headings and case fields present |
| Tooling reality | every referenced test command/tool | inspect repo manifests, config, and CI | before finishing | blocking | defining file and command location |
| Duplicate avoidance | every proposed case | compare with relevant existing tests | before finishing | blocking | existing-test citations and delta explanation |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

Record `not_applicable` with a reason for gates or test layers outside the
source's scope.

## Escalation conditions

- Continue while research and plan writing remain inside the authority above.
- Pause when the source of truth is missing, requirements conflict, a material
  testability decision would require changing production architecture, or the
  requested scope requires a new tool/dependency not already authorized.
- Redirect a repo-wide untested-code or coverage-remediation request to the
  test-suite workflow instead of stretching a feature plan to fit it.
