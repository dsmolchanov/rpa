---
name: enhance-plan
description: >
  Improve an existing implementation plan by reconciling multiple critiques,
  reviews, or alternative proposals into one coherent, evidence-backed plan.
  Select when feedback competes, spans several plan sections, or needs
  acceptance/rejection decisions. Do NOT select for a single focused edit, a
  new plan, plan execution, or implementation validation; use iterate-plan,
  create-plan, implement-plan, or validate-plan instead.
user-invocable: true
permission-class: "read_only (target repo and feedback) + workspace_write (named plan only)"
invocation: "both"
---

# Enhance Plan — kernel

## Intent

Synthesize supplied feedback into a stronger existing implementation plan.
Evaluate each material suggestion against the user's objective, the current
repository, and other feedback; integrate the best compatible ideas, reject or
adapt weaker ones transparently, and leave one internally consistent plan.

## Scope & authority

Read the named plan, supplied feedback, repository sources, and relevant
`thoughts/` artifacts. Write authority is limited to the named plan under
`thoughts/shared/plans/`. Do not implement the plan, edit feedback sources, or
turn a requested enhancement into an unrelated redesign without explicit user
direction.

## Artifact contracts

- Preserve the canonical plan shape from
  [`../create-plan/references/artifact-contract.md`](../create-plan/references/artifact-contract.md).
- Record the synthesis once using
  [`references/enhancement-record.md`](references/enhancement-record.md).

Read both before editing. Do not duplicate either template in this package or
in the command adapter.

## Process guidance

1. **Require the plan and feedback.** Identify the target plan and the
   critiques, opinions, or review sources to synthesize. If either is missing,
   ask one focused question. Resolve every supplied file or link before
   proceeding; report inaccessible inputs rather than silently omitting them.
2. **Read the whole evidence set.** Read the complete plan, applicable
   repository instructions, and every supplied feedback document. Separate
   requested outcomes from proposed solutions and style preferences.
3. **Build a decision set.** Group duplicate suggestions and classify each
   material item as a technical correction, scope change, phase/dependency
   change, verification improvement, risk mitigation, or alternative design.
   Identify contradictions and downstream sections each option would affect.
4. **Verify only load-bearing claims.** Check feasibility, affected files,
   APIs, established patterns, tests, migration, and rollback against the
   current checkout when a suggestion depends on them. Use the optional shared
   routes in
   [`../create-plan/references/research-routing.md`](../create-plan/references/research-routing.md)
   only for independent, sizeable tracks; small checks stay in the main
   context.
5. **Synthesize, do not concatenate.** Accept, adapt, or reject each material
   suggestion based on evidence and the plan's objective. Prefer the simplest
   compatible approach that closes the identified gap. Ask the user only when
   competing valid options materially change product scope, architecture,
   compatibility, or another hard-to-reverse decision.
6. **Revise coherently.** Apply focused edits across every affected section:
   overview, current/desired state, exclusions, approach, phases, success
   criteria, testing, risks, migration/rollback, and references. Reorder and
   renumber phases when dependency changes require it. Remove stale text left
   behind by superseded decisions.
7. **Record and report.** Append one enhancement record for this synthesis,
   naming the accepted/adapted/rejected themes without copying entire reviews.
   Return the plan path plus the main decisions and rejected suggestions with
   concise reasons.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for the synthesis, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The workflow is complete when:

1. Only the named plan is modified.
2. Every material feedback theme is accepted, adapted, or rejected; no supplied
   review silently disappears.
3. Accepted changes are integrated into the relevant plan sections rather than
   appended as disconnected commentary.
4. Changed technical claims carry current `file:line` evidence, and affected
   verification commands are real and measurable.
5. The plan remains internally consistent, dependency ordered, and compliant
   with the create-plan artifact contract.
6. One enhancement record captures the source themes, decisions, and resulting
   changes without duplicating the feedback itself.
7. The final response links the plan and surfaces consequential rejections or
   remaining limits.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Path authority | every enhancement | inspect changed paths | before finishing | blocking | only the named plan is changed |
| Plan structure | every enhancement | compare against the create-plan artifact contract | before finishing | blocking | required sections and phase fields remain coherent |
| Feedback coverage | every enhancement | compare material feedback themes with the enhancement record | before finishing | blocking | each theme has a disposition |
| Referenced commands | when verification commands change | repository command/config inspection | before finishing | blocking | command definition or successful dry check |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

Record `not_applicable` with a reason for gates the enhancement does not touch.
Do not run a full application test suite solely to revise its plan.

## Escalation conditions

- Continue while synthesis remains within the named plan and supplied
  authority.
- Pause when the plan or feedback is missing, a source is inaccessible, two
  evidence-backed choices have materially different consequences, or the best
  option requires expanding scope beyond the request.
- If feedback exposes broad checkout drift rather than a bounded plan defect,
  show the evidence and ask whether to re-plan that scope instead of hiding a
  wholesale rewrite inside an enhancement.
