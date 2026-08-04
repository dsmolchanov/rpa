---
name: iterate-plan
description: >
  Revise an existing implementation plan in response to specific requested
  changes while preserving valid content and grounding technical updates in
  the current repository. Select when the user names a plan and asks to add,
  remove, reorder, clarify, or correct part of it. Do NOT select to create a
  plan from scratch, execute it, validate completed implementation, or
  synthesize a broad set of competing reviews; use create-plan,
  implement-plan, validate-plan, or enhance-plan instead.
user-invocable: true
permission-class: "read_only (target repo) + workspace_write (named plan only)"
invocation: "both"
---

# Iterate Plan — kernel

## Intent

Apply the user's requested changes to an existing implementation plan with the
smallest coherent edit. Preserve correct decisions and structure, verify new
technical claims against the current checkout, and leave the plan actionable
for its downstream implementation and validation workflows.

## Scope & authority

Read the target plan, relevant repository sources, and supporting `thoughts/`
artifacts. Write authority is limited to the named plan file under
`thoughts/shared/plans/`. Do not implement the plan, rewrite unrelated phases,
edit source files, or broaden scope beyond the requested revision without an
explicit decision from the user.

## Artifact contract

The canonical plan structure is owned by
[`../create-plan/references/artifact-contract.md`](../create-plan/references/artifact-contract.md).
Preserve that shape and the target file path. Do not create a second copy of
the plan template in this package.

## Process guidance

1. **Require two inputs.** Identify both the plan path and the requested
   change. If either is missing, ask one focused question for the missing
   input. If the named file cannot be found, report that fact and likely
   matches; do not guess which plan to edit.
2. **Read before editing.** Read the entire plan, applicable repository
   instructions, and every source document explicitly named in the feedback.
   Map the request to affected sections and note dependencies on untouched
   phases.
3. **Research proportionally.** A wording, ordering, or scope clarification
   may need no new code research. Verify feedback that changes technical
   feasibility, file ownership, APIs, dependency order, tests, migration, or
   rollback against the current checkout. Use the shared routes in
   [`../create-plan/references/research-routing.md`](../create-plan/references/research-routing.md)
   only for genuinely independent, sizeable investigation tracks.
4. **Resolve conflicts explicitly.** If feedback contradicts current code,
   another accepted plan decision, or repository policy, present the evidence
   and the consequence. Ask only when resolving the conflict materially
   changes the user's intended outcome.
5. **Edit surgically.** Change the minimum set of sections needed for a
   coherent result. When one edit affects scope, phase order, testing, risks,
   migration, or references, update those dependent sections in the same
   pass. Preserve accurate citations and valid plan content.
6. **Recheck the whole plan.** Ensure phase numbering and dependencies remain
   consistent, exact commands still exist, automated and manual verification
   remain distinct, and no removed decision survives elsewhere as stale text.
7. **Report the revision.** Return the plan path and a concise account of what
   changed, what was deliberately preserved, and any technical claim that was
   rejected or adjusted after verification.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for the revision, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The workflow is complete when:

1. Only the named plan is modified by the workflow.
2. Every requested change is reflected, or the final response explains with
   evidence why a requested change was not applied.
3. Unrelated correct content is preserved; dependent sections are updated only
   where needed to keep the document coherent.
4. New or changed repository claims carry current `file:line` evidence, and
   affected verification commands are real and measurable.
5. The resulting plan still satisfies the create-plan artifact contract and
   contains no unresolved product or architecture decision disguised as work.
6. The final response links the plan and summarizes the actual diff in intent,
   scope, ordering, and verification.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Path authority | every revision | inspect changed paths | before finishing | blocking | only the named plan is changed |
| Plan structure | every revision | compare against the create-plan artifact contract | before finishing | blocking | required headings and phase fields remain coherent |
| Referenced commands | when verification commands change | repository command/config inspection | before finishing | blocking | command definition or successful dry check |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

Record `not_applicable` with a reason for gates the requested revision does not
touch. Do not run an application's full test suite merely to edit its plan.

## Escalation conditions

- Continue while the requested edits remain within the named plan and do not
  create a material new decision.
- Pause when the plan path or requested change is missing, the request admits
  materially different interpretations, the edit requires broader authority,
  or a conflict cannot be resolved from repository evidence.
- If the existing plan already diverges substantially from the checkout,
  describe the drift and ask whether to repair that broader scope instead of
  silently rewriting it during a narrow iteration.
