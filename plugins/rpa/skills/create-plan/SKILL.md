---
name: create-plan
description: >
  Create a persistent, implementation-ready plan for a software change after
  grounding it in the current repository. Select for requests to plan a new
  feature, fix, migration, or refactor, especially from a ticket or research
  document. Do NOT select to execute a plan, revise an existing plan from
  feedback, document current behavior without proposing changes, or perform a
  code review; use the implementation, plan-iteration, research, or review
  workflow instead.
user-invocable: true
permission-class: "read_only (target repo) + workspace_write (thoughts/shared/plans/ only)"
invocation: "both"
---

# Create Plan — kernel

## Intent

Turn an agreed software change into a self-contained implementation plan that
another engineer or agent can execute without reconstructing the original
conversation. Ground the plan in the checked-out code and write it at the path
defined by the artifact contract.

## Scope & authority

Research the repository and write one plan under `thoughts/shared/plans/`.
Source code, tests, configuration, tickets, research documents, and existing
plans are read-only. Planning does not authorize implementation, external
state changes, or edits to orientation documents.

## Artifact contract

The plan path, required sections, phase structure, and verification format are
defined once in
[`references/artifact-contract.md`](references/artifact-contract.md). Read that
file before writing. Keep the stable section names so `/implement-plan`,
`/iterate_plan`, `/enhance_plan`, and `/validate_plan` can consume the result.

## Process guidance

1. **Establish the planning target.** If the invocation names a ticket,
   research document, plan, or source file, read every named file completely
   before decomposing the work. If no target is supplied, ask one focused
   question for the task or source document. A research document is evidence
   as of its `git_commit`: for any file it cites that changed since, re-verify
   the finding at the current checkout before the plan relies on it.
2. **Orient before searching.** Read applicable `AGENTS.md` / `CLAUDE.md` and
   `ARCHITECTURE.md` files first. Treat code and repository configuration at
   the current checkout as authoritative; prior `thoughts/` documents provide
   context, not proof of current behavior.
3. **Research only to close material gaps.** Locate the implementation, trace
   the affected behavior, inspect representative tests, and find established
   patterns. Use the optional shared research fleet according to
   [`references/research-routing.md`](references/research-routing.md); do not
   delegate small searches or spawn agents merely to repeat main-context work.
4. **Resolve decisions before finalizing.** Derive answers from the repository
   where possible. Ask the user only when plausible interpretations materially
   change scope, architecture, compatibility, or another hard-to-reverse
   choice — and then put the fork as options with their trade-offs and a
   recommendation, one decision at a time. Continue without ritual outline
   approvals when the supplied request and evidence already determine the
   approach. Record how each material decision was settled.
5. **Separate obligations from guidance.** State as an obligation only what
   must hold for the change to be correct, as an observable outcome with the
   criterion that demonstrates it. Approach, naming, ordering, and file
   layout are design guidance: an implementer may adapt them, and a reviewer
   may not block on them. Requirements the request implies but does not state
   — compatibility, authorization, data handling, existing callers — are the
   ones most often missed; look for them in the affected code and write them
   down as obligations or as explicit exclusions.
6. **Design in dependency order, sized for one review.** State the current and
   desired states, exclusions, and overall approach. Divide the work into
   independently verifiable phases ordered by real dependencies, each a
   vertical slice that ends with something observable. Keep the whole plan to
   one reviewable change and move the remainder to follow-up issues. Name
   exact files and symbols when known; describe new files explicitly. Prefer
   pointers and interface shapes over pasted implementation bodies, and let
   the plan's length follow the size of the change.
7. **Make verification executable.** For every phase, name applicable repo
   commands and observable outcomes; for new behavior prefer a check that
   fails before the phase and passes after. Whatever an agent can observe
   with the repository's tools is an automated criterion; reserve manual
   criteria for human judgment and say who checks them and when. Include
   migrations, rollback, compatibility, performance, security, and
   operational checks only when the change makes them relevant; state
   `not applicable` with a reason rather than inventing a checklist.
8. **Write and report.** Emit the artifact contract exactly, then return the
   plan path plus the obligations, decisions, risks, and any `not_applicable`
   verification outcomes that matter to the implementer.

When the invocation says nobody will answer, or the run is controller-driven,
do not ask and do not wait: settle each fork with the most defensible option,
record it as an assumption, and publish the plan as `approved`. A fork too
consequential to assume — it changes what is built, or cannot be undone —
ends the run without a plan and with the question stated.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for the plan, ensure you have seen all of it before relying on
it.

## Acceptance criteria & evidence

The workflow is complete when:

1. The plan exists at the contract path and contains every required section.
2. Current-state claims and proposed touch points cite concrete `file:line`
   evidence from the current checkout; external API or library claims cite an
   authoritative source when they affect the design.
3. Each phase identifies its files or symbols, changes, dependencies, and
   measurable automated and/or manual success criteria.
4. Every obligation is an observable outcome mapped to at least one criterion
   or test, and nothing the change must satisfy appears only as narrative.
5. Scope exclusions, risks, migration or rollback needs, and cross-component
   effects are explicit where applicable.
6. No unresolved decision is disguised as an implementation step. A bounded
   uncertainty may remain only when the plan states how implementation will
   resolve it deterministically without changing agreed scope.
7. The final response links the artifact and briefly identifies the selected
   approach, the obligations, and the verification profile.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Repository metadata | when the installed metadata script is available | `scripts/spec_metadata.sh` | before naming the plan | advisory | date, branch, commit, and repository output |
| Plan structure | every produced plan | compare against `references/artifact-contract.md` | before finishing | blocking | frontmatter, required headings, and phase fields present; every obligation ID appears on a criterion |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

For a gate that does not apply, report `not_applicable` and the reason. Do not
replace a missing project-specific test command with a fabricated one.

## Escalation conditions

- Continue while research and writing remain inside the authority above.
- Pause for one focused decision when the target is ambiguous, two viable
  approaches have materially different product or architectural consequences,
  or required source material is inaccessible.
- If the request's premise conflicts with the repository, show the evidence
  and plan against the corrected current state only after the mismatch is
  resolved.
- If a complete actionable plan cannot be produced, do not publish a document
  that presents unresolved choices as settled work.
- If the change is small and understood well enough to implement and verify
  directly, say so before writing: a plan is for work that needs decisions
  recorded, not a toll on every edit. Write the compact plan anyway when the
  caller asked for the artifact.
