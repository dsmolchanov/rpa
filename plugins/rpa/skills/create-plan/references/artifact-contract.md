# Implementation plan — artifact contract

Single source of truth for the `/create_plan` output shape. It preserves the
stable sections consumed by the plan iteration, enhancement, implementation,
and validation workflows while removing universal approval pauses and fake
verification commands.

A plan has two kinds of content, and the shape keeps them apart. **Obligations**
are the binding, checkable commitments an implementation is judged against.
Everything else — analysis, approach, file lists, phase narrative — is design
guidance that an implementer may adapt and must only record when they do.

## Path

`thoughts/shared/plans/YYYY-MM-DD-ENG-XXXX-description.md`

- `YYYY-MM-DD` — current local date.
- `ENG-XXXX` — ticket identifier when one exists; omit this segment when it
  does not.
- `description` — short kebab-case description.

Examples:

- `2025-01-08-ENG-1478-parent-child-tracking.md`
- `2025-01-08-improve-error-handling.md`

Use the installed `scripts/spec_metadata.sh` when available to obtain the date,
checkout, branch, and repository consistently.

## Frontmatter (YAML, required for new plans)

```yaml
---
date: [YYYY-MM-DD]
repository: [Repository name as the metadata script reports it]
git_commit: [Commit the plan was grounded in]
branch: [Branch name at that commit]
status: [approved | draft]
ticket: [Ticket identifier — omit the key when there is none]
research: [Paths of research documents the plan relies on — omit when none]
---
```

- `status: approved` — every decision is resolved and the plan is an agreed
  specification. `status: draft` — published with a decision still open,
  named under `## Decisions and Assumptions`; a draft binds nobody until that
  decision is settled.
- `repository` and `git_commit` let consumers detect a plan applied to the
  wrong repository or to code that has moved since it was written.
- Implementation progress is not tracked here; it lives in the plan's
  `## Implementation Record`.

Plans written before this section existed remain valid input to the consuming
workflows; do not rewrite them only to add frontmatter.

## Required body

```markdown
# [Feature or Task Name] Implementation Plan

## Overview

[What will change and why]

## Desired End State

[Observable end state and how to recognize it]

## Obligations

- **O-1** — [Observable behavior, contract, or constraint the change must satisfy] — verified by [phase criterion or test]
- **O-2** — [...]

## What We're NOT Doing

- [Explicit scope exclusion]

## Decisions and Assumptions

- **A-1** ([decided by user | derived from repository | assumed]) — [decision] — [evidence or reason]

## Current State Analysis

[Relevant behavior today, grounded in file:line references]

### Key Discoveries

- [Current implementation detail with file:line reference]
- [Pattern or invariant the implementation must preserve]

## Implementation Approach

[Selected strategy, important dependencies, and reasoning]

## Phase 1: [Outcome-oriented name]

### Overview

[What observable result this phase delivers and why it comes here]

### Changes Required

- `path/to/existing_file.ext` — `symbol`: [behavior or contract that changes]
- `path/to/new_file.ext` (new) — [what it provides]

**Interfaces**: [signature, schema, or data shape that another phase or caller depends on — omit when none]

### Success Criteria

#### Automated Verification

- [ ] [Exact repository command and expected outcome] (O-1)

---

## Testing Strategy

[Which test layers carry which obligations, and the commands that run them]

## Performance Considerations

[Relevant effects and checks, or `Not applicable — reason`]

## Migration and Rollback

[Data/deployment/compatibility steps, or `Not applicable — reason`]

## References

- [Original ticket or request]
- [Related research]
- [Representative implementation and tests with file:line references]

## Follow-up Issues

- [Independently shippable remainder cut from this plan — one entry per future plan]
```

Repeat the phase block for each dependency-ordered phase. Omit
`## Follow-up Issues` when nothing was cut. Do not put unresolved product or
architecture questions in the final artifact.

The sections from `## Overview` through `## Decisions and Assumptions` are the
plan's contract page: what will be true, what is out of scope, and what was
decided. Write them to be read alone — by a reviewer, a validator, or a later
planner — and keep them to about a page. Everything after them is working
material for the implementer.

The implementing workflow appends a `## Implementation Record` and the
enhancement workflow a `## Enhancement History`; both are defined by their
owning packages and are not written by the planner.

## Obligation rules

- An obligation states an outcome that can be observed and checked: a
  behavior, an interface contract, a data or security constraint, a
  compatibility guarantee. It does not state an approach, a name, an ordering,
  or a file layout — those are design guidance and belong in the phases.
- Every obligation names the criterion or test that demonstrates it, and that
  criterion carries the obligation's ID in parentheses at the end of its
  line. An obligation nothing verifies is a wish; a requirement the change
  must meet that appears only in narrative is unenforceable.
- Reviewers and validators may block on a violated obligation. They may not
  block on a mismatch with design guidance. Write an obligation only for what
  must hold for the change to be correct, because a preference phrased as a
  requirement becomes a merge blocker.
- `## What We're NOT Doing` is binding in the same way: work it excludes is
  out of scope for the implementation and for review of it.
- IDs are stable. Revising a plan retires an ID rather than reusing it.

## Changes Required rules

- The section locates the change and states the contract it must present:
  files, symbols, and the interface shapes other code depends on. It does not
  sequence the edits or draft them.
- An implementer reads it to find where to work; how to make the change is
  theirs to decide, and departing from the list is a recorded deviation, not
  a violation.
- An entry is one line. A change that needs a paragraph to describe is either
  an obligation that belongs on the contract page or a decision that belongs
  in the approach.

## Phase and size rules

- A phase is a vertical slice wherever the change allows: it ends with the
  repository's gates passing and something observable — a behavior, an
  endpoint, a test at a real boundary — not a finished layer waiting for the
  next one. Split by layer only when a real dependency forces it, and say so
  in the phase overview.
- A plan describes one reviewable change, normally one pull request. Phases
  structure the work; they do not make the diff smaller. When the caller or
  the repository states a review budget, size the plan to it. When honest
  scope exceeds one reviewable change, cut at an independently shippable
  boundary and list the remainder under `## Follow-up Issues`.
- Length follows the change. A small, well-understood change gets a compact
  plan in which inapplicable sections are one `Not applicable — reason` line.
  A plan longer than the diff it describes has written the code instead of
  deciding it.

## Verification rules

- An automated criterion is an exact repository command with its expected
  outcome. For new behavior, prefer a criterion that fails before the phase
  and passes after it.
- An outcome an agent can observe with the repository's own tools — a CLI
  run, an HTTP call, a rendered page — is an automated criterion with the
  procedure written out, not a manual one.
- Every phase has at least one automated criterion. A phase that cannot be
  checked by a command is usually part of another phase.
- Manual verification is optional and absent by default. Add a
  `#### Manual Verification` block with its own checkboxes to a phase only
  for an outcome that takes human judgment, and say who checks it and when
  (before merge, after deploy). A phase without one needs no explanation.
- No plan step waits for a human unless the plan says so: state explicitly
  when a later phase depends on a manual outcome, and prefer cutting the plan
  at that point into a follow-up issue.
- `## Testing Strategy` names layers and commands. When a test plan is
  written from this plan, the cases live there, keyed to the obligation IDs;
  do not enumerate them twice.
- Checkbox syntax appears only on success criteria. Progress, decisions, and
  follow-ups use plain bullets, so tooling that counts criteria stays
  accurate.

## Content rules

- Cite the current checkout, not remembered or historical behavior.
- Use exact repository commands discovered from its configuration; never copy
  the sample command shape as if it were a real gate.
- File lists and symbols must be precise enough for an implementer to locate
  the change. Mark a file as new when it does not yet exist.
- Code snippets are optional and reserved for a contract or interface shape
  that prose cannot describe unambiguously; the plan is not a speculative
  patch.
- Do not add approval gates, sign-off steps, or pauses between phases; the
  implementing workflow applies its own authority and interaction rules.
  Where manual verification exists it stays separate from automated criteria.
- `## Decisions and Assumptions` records how each material decision was
  settled: by the user, by repository evidence, or by assumption. A plan
  produced without a user to ask resolves every fork as a recorded assumption.
- Add sections for security, observability, deployment, or documentation when
  the requested change makes them material.
