---
name: implement-plan
description: >
  Execute an existing implementation plan from thoughts/shared/plans: carry
  out its phases in dependency order, run each phase's verification, and keep
  the plan's implementation record current so the work can be resumed and
  independently validated. Select when the user names a plan and asks to
  implement it, continue it, or run specific phases. Do NOT select to write or
  revise a plan, to drive a Red-Green-Refactor cycle from a test plan, to
  check a finished implementation against its plan, or to review a diff; use
  create-plan or iterate-plan, tdd, validate_plan, or the review workflow
  instead.
user-invocable: true
permission-class: "workspace_write (plan-scoped source, tests and configuration; criterion checkboxes and the Implementation Record of the named plan)"
invocation: "both"
---

# Implement Plan — kernel

## Intent

Turn an approved plan into working, verified changes, one phase at a time,
and leave a record accurate enough that a fresh session can resume the work
and a validator can check it without this conversation.

## Scope & authority

Read the named plan, the sources it cites, and the repository. Write the
source, tests, and configuration the plan's phases require.

In the plan file itself, write two things only: the checkboxes of criteria
this run satisfied, and the `## Implementation Record` section. Everything
else in the plan — obligations, phases, criterion text, exclusions — is the
specification the work is judged against. Changing it is the `iterate-plan`
workflow's job, done with the user; an implementation that edits its own
specification cannot be validated against it.

Stay inside the plan: no dependency, feature, fallback, or refactor it does
not call for. A defect found outside its scope is recorded, not fixed.
Preserve pre-existing uncommitted changes and unrelated failures.

Create one checkpoint commit per verified phase unless the caller keeps
commit authority — a controller-driven run, or a user who said they will
commit. Stage specific files and follow the repository's commit conventions.
Pushing, opening a pull request, amending, and rewriting history are outside
this workflow. Do not recover from a failed attempt with destructive git
commands; report the scoped diff of files this workflow touched instead.

## Artifact contracts

- Consume the plan shape from
  [`../create-plan/references/artifact-contract.md`](../create-plan/references/artifact-contract.md).
  Plans written before that contract gained frontmatter and obligations are
  still valid input: treat their success criteria as the obligations.
- Maintain the record defined by
  [`references/implementation-record.md`](references/implementation-record.md).
  Read it before the first edit.
- When the plan has a test plan with a `tdd` session log, that cycle is
  finished evidence. Build on its tests; do not re-run the cycle, edit the
  log or its receipts, or weaken what it wrote. If its result looks wrong,
  report that as a blocker.

## Process guidance

### Establish the starting state

1. Require a plan path; the scope defaults to every remaining phase and may
   be narrowed to named phases. Read the whole plan including any existing
   Implementation Record, the applicable repository instructions and their
   blocking invariants, and the files the plan cites for the phases in scope.
2. Before editing, inspect `git status` and compare `HEAD` with the plan's
   `git_commit`. Re-read any cited file that changed since the plan was
   written and handle differences as drift (below). Run the verification that
   should already pass — the plan's own baseline command, or the repository's
   standard gate at the narrowest scope that covers the phases — so
   pre-existing failures are known before the first edit. Record the base
   commit and the baseline outcome.
3. On resume, ticked boxes and record entries are claims about an earlier
   session. Re-run the last completed phase's automated verification before
   building on it, then continue from the first phase with an unsatisfied
   automated criterion.

### Execute phase by phase

4. Work the phases in plan order with a single writer in one checkout.
5. Before writing a phase's code, list the invariants it touches: the plan
   obligations this phase serves, the repository's blocking invariants
   (`AGENTS.md` and any repository invariants file it names), and any rule the
   change itself introduces. When the phase's code is written, read the
   finished diff against each one and record the outcome in one line. This
   order — invariants, then code, then code checked against the invariants —
   catches the defect classes the planned tests do not.
6. A phase is complete when every one of its automated criteria passes on a
   run made in this session after the last edit that could affect it. Then
   tick those boxes, update the record, and create the checkpoint commit. A
   criterion that cannot be run in this environment stays unticked with the
   reason recorded; a box is never ticked from an earlier run, from reading
   the code, or from a subset of the command.
7. A criterion passes because the behavior is right. Do not edit criterion
   text, weaken or delete a test, skip or stub a check, or special-case the
   verification input to turn a failure into a pass.

### When the plan and the repository disagree

Classify the mismatch before acting on it:

- **Drift** — a file moved, a symbol was renamed, line numbers shifted, an
  equivalent API replaced the cited one. `Changes Required` is a locator, not
  a script: adapt and record a deviation.
- **Approach divergence** — the plan's suggested approach or design note
  turns out wrong or clearly inferior, while every obligation and criterion
  can still be met. Take the sound approach and record the deviation with its
  reason.
- **Obligation conflict** — an obligation or criterion cannot be met as
  written, or meeting it needs a new dependency, wider scope, or authority
  that was not granted. Do not improvise past it. Finish the phases that do
  not depend on the conflict, then escalate.

An ambiguity that is not a conflict is resolved from the repository where
possible; otherwise take the narrowest reading that satisfies the stated
obligation and record it as an assumption.

### Manual verification

Most plans have no manual criteria, and none is required to finish a run.
Where a plan does carry them, they belong to a human and are ticked only on
that human's confirmation in this session. Pause at a phase boundary for a
manual check only when the plan says a later phase depends on its outcome.
Otherwise continue, and carry every manual item into the record and the
final report.

### Non-interactive runs

When the invocation says nobody will answer, or the run is controller-driven,
do not ask and do not wait. Assumptions are recorded and the work continues;
an obligation conflict ends the run with the record's status `blocked` once
the independent phases are done. The final message states the status first,
because a controller may read nothing else.

### Stopping a fix loop

When a phase's verification keeps failing and further attempts stop producing
new information — the same failure after different fixes, or failures that
cycle — stop iterating. Record the attempts and the evidence, and escalate.
Honor an attempt budget when the caller states one.

### Finish

After the last phase, re-run every automated criterion of the plan on the
final tree: a later phase can break an earlier one. Set the record's status
and report for a reader with no context — status, what changed, verification
outcome, deviations, assumptions, out-of-scope findings, and what awaits
human verification. Recommend `validate_plan` in a fresh session: the
implementing session's own account is not validation.

Delegation is optional and read-only: independent, sizeable exploration may
go to an analysis agent. Edits stay with one writer; parallel implementers on
one tree are not used. An orchestrator may run each phase in a fresh context,
provided the plan and its record are the only handoff.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for a phase decision, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The run is complete when:

1. Every phase in scope is complete, or the record names exactly which
   criterion is unmet and why.
2. Every ticked automated criterion passed on a run from this session after
   the last relevant edit, and a `complete` status rests on the final-tree
   run.
3. No manual criterion was ticked without the human's confirmation.
4. `git diff` of the plan file shows only checkbox ticks and the
   Implementation Record.
5. Every deviation, assumption, out-of-scope finding, and blocker is in the
   record; none lives only in the conversation.
6. Only plan-scoped files changed, and pre-existing changes are intact.
7. The final response states the status, links the plan, and lists what
   awaits human verification.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Baseline protection | every run | `git status --short` plus the baseline verification command | before the first edit | blocking | base commit and baseline outcome in the record |
| Phase verification | every phase in scope | that phase's Automated Verification commands | after the phase's last edit | blocking | ticked criteria and the phase's record entry |
| Final verification | runs that finish every phase | all Automated Verification commands of the plan | on the final tree | blocking | record status `complete` |
| Plan integrity | every run | `git diff -- <plan path>` | before finishing | blocking | only ticks and the record changed |
| Repository hooks | where the bundled or repository hooks are installed | the hook runner | on edit and on stop | per hook | hook outcome |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

For a gate that does not apply, report `not_applicable` and the reason. A
plan criterion with no runnable command in this repository is reported as
such; do not substitute an invented command.

## Escalation conditions

- Continue while actions remain within granted authority. Pause when the plan
  is missing or ambiguous about what to build, when materially new authority
  is required, or when a high-impact irreversible action was not explicitly
  authorized.
- A plan whose frontmatter says `status: draft` names a decision that is
  still open. That is an ambiguity about what to build, not a formality to
  confirm: when the request or the repository settles it, record that and
  proceed; otherwise ask that one question, or stop in a non-interactive run.
- Present an obligation conflict as what the plan says, what the repository
  shows, why it matters, and the options with a recommendation — one
  decision, not a survey. In a non-interactive run, record it and end
  `blocked`.
- Stop when the baseline shows the repository's gate already failing in the
  area the plan changes and the failure cannot be isolated from the work.
- Stop when a required command mutates state outside the checkout — a
  database, a deployment, a third-party service — and the plan did not
  authorize it.
