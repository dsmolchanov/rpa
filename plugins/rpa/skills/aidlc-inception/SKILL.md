---
name: aidlc-inception
description: >
  Execute or resume the approved AI-DLC inception stages recorded in canonical
  state and execution-plan files, producing requirements, reverse-engineering,
  user-story, design, and unit artifacts. Select when `/aidlc_start` has
  prepared an approved inception plan or the user asks to resume that phase.
  Do NOT select to initialize/classify a request, implement construction units,
  run global build/test, or bypass pending file-based decisions; use
  aidlc-start, aidlc-bolt, or aidlc-build-test instead.
user-invocable: true
permission-class: "read_only (repository and rules) + workspace_write (aidlc-docs inception artifacts and state only)"
invocation: "both"
---

# AI-DLC Inception — kernel

## Intent

Execute the durable inception plan stage by stage, generate the canonical
AI-DLC compatibility artifacts, and keep state resumable and truthful. The
execution plan decides which stages run; pinned compatibility rules decide
their semantics; depth changes detail only within an executed stage.

## Scope & authority

Read repository sources, compatibility rules, state, execution plan, answered
question files, and historical context. Write only canonical inception
artifacts under `aidlc-docs/inception/` and the corresponding progress fields
in `aidlc-docs/aidlc-state.md`. Do not edit source code, construction artifacts,
the approved execution-plan decisions, rule files, or `thoughts/`. A requested
change to stage selection returns to `/aidlc_start` rather than being applied
implicitly here.

## Authoritative inputs and artifact contract

Read these sources completely before execution:

1. `.aidlc-rule-details/core-workflow.md`
2. `.aidlc-rule-details/common/depth-levels.md`
3. `.aidlc-rule-details/common/question-format-guide.md`
4. `aidlc-docs/aidlc-state.md`
5. `aidlc-docs/inception/plans/execution-plan.md`
6. all required question/approval files under
   `aidlc-docs/inception/questions/`

Canonical artifact paths and minimum content are defined once in
[`references/artifact-contract.md`](references/artifact-contract.md). Repo-local
rule overrides and enabled extensions apply in the loading order stated by the
repository's AI-DLC bootstrap instructions.

## Process guidance

1. **Validate durable readiness.** Confirm state, execution plan, rules, and
   repository identity are mutually consistent. Every inception stage must
   have an explicit `EXECUTE` or `SKIP`, depth, rationale, and sufficient
   approval. If a required `[Answer]:` or approval remains blank/pending, stop
   and point to the existing file; do not replace it with a chat-only answer.
2. **Reconcile invocation arguments.** Treat a description, type, or depth
   argument as context only when it matches durable state. If it would change
   the request classification, depth, or stage decision, emit or reuse a
   question file and route the change through `/aidlc_start`.
3. **Resume from evidence, not labels.** For each prior completed stage, verify
   the referenced canonical artifact exists and satisfies its contract at the
   current recorded request. A state label without its artifact is incomplete;
   an existing valid artifact is preserved rather than regenerated.
4. **Execute in planned order.** Process only `EXECUTE` stages and leave `SKIP`
   stages untouched. Read all prerequisite artifacts before a dependent stage.
   Depth controls concision, trace detail, and alternatives considered inside
   the stage; it never adds, removes, or substitutes a stage.
5. **Ground brownfield claims.** Reverse-engineering and design claims about an
   existing workspace require `file:line` evidence. Historical `thoughts/`
   material provides context only and is rechecked against the current code.
   Greenfield artifacts identify assumptions rather than inventing current
   implementation.
6. **Delegate conditionally.** Use codebase discovery/analysis or thoughts
   analysis only for independent, sizeable brownfield tracks. Unit decomposition
   is allowed only after every executed prerequisite among requirements,
   workflow planning, and application design has a valid approved artifact.
   The orchestrator verifies delegated output and owns canonical writes.
7. **Gate each stage durably.** Write the artifact, validate its required IDs,
   traceability, evidence, and unresolved decisions, then update state. Never
   mark a stage complete before the artifact is valid. When a material decision
   or approval is required, create a question file using the pinned guide,
   record the pending stage in state, and stop.
8. **Keep updates recoverable.** Update one coherent stage at a time. On resume,
   append or surgically revise the canonical artifact without duplicating
   sections. Preserve prior approved decisions and never discard user-authored
   answers.
9. **Complete inception truthfully.** Inception is complete only when every
   `EXECUTE` stage has a valid approved artifact and every `SKIP` decision is
   preserved in the execution plan. Update state and direct the user to
   `/aidlc_bolt` with the first dependency-ready unit; do not begin construction.

Tool results can be truncated, paginated, or filtered. When a file or output is
load-bearing for a stage decision, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The workflow is complete or durably paused when:

1. All authoritative inputs were loaded, and unanswered/approval-pending files
   were handled through the canonical question mechanism.
2. Each stage has an evidence-backed disposition: preserved `SKIP`, valid
   completed artifact, or explicit pending question/approval/blocker.
3. Generated artifacts conform to the contract, use stable IDs, and trace
   requirements → stories/design → units where those stages execute.
4. Brownfield claims carry current `file:line` evidence; greenfield assumptions
   are labeled.
5. `aidlc-state.md` never claims progress beyond the artifacts on disk and
   contains the current stage/depth/pointers needed to resume.
6. Only inception artifacts and state are changed.
7. The final response links completed artifacts or the blocking question file,
   states the durable current stage, and names the next valid command.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Durable-input readiness | every invocation | parse state, execution-plan rows, and required `[Answer]:` fields | before execution | blocking | stage dispositions and pending file list |
| Artifact structure | every executed stage | compare with `references/artifact-contract.md` | before state update | blocking | required sections/IDs/trace links |
| Brownfield evidence | brownfield findings/design | source inspection | before artifact approval | blocking | `file:line` references |
| State/artifact consistency | every state update | verify pointers and completed-stage files | after each stage | blocking | state value and existing valid artifact |
| Write boundary | every invocation | changed-path inspection | before finishing | blocking | only inception/state paths changed |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

## Escalation conditions

- Pause for missing/corrupt canonical inputs, unanswered questions, pending
  approvals, conflicting durable decisions, or unavailable load-bearing source.
- Create a file-based question when a material ambiguity affects requirements,
  workflow, architecture, NFRs, or unit boundaries. Do not use chat approval as
  the canonical decision.
- Route classification/depth/stage changes to `/aidlc_start`, construction to
  `/aidlc_bolt`, and global verification to `/aidlc_build_test`.
