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
  specification. `status: draft` — published for the user's review with a
  decision still theirs to make; a draft binds nobody and is not implemented
  as-is.
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

## Current State Analysis

[Relevant behavior today, grounded in file:line references]

## Desired End State

[Observable end state and how to recognize it]

### Key Discoveries

- [Current implementation detail with file:line reference]
- [Pattern or invariant the implementation must preserve]

## Obligations

- **O-1** — [Observable behavior, contract, or constraint the change must satisfy] — verified by [phase criterion or test]
- **O-2** — [...]

## What We're NOT Doing

- [Explicit scope exclusion]

## Implementation Approach

[Selected strategy, important dependencies, and reasoning]

## Phase 1: [Outcome-oriented name]

### Overview

[What observable result this phase delivers and why it comes here]

### Changes Required

#### 1. [Component or file group]

**Files**: `path/to/existing-or-new-file.ext`

**Changes**:

- [Specific symbol, behavior, contract, or data-flow change]
- [Compatibility, migration, or rollback handling when applicable]

### Success Criteria

#### Automated Verification

- [ ] [Exact repository command and expected outcome] (O-1)

#### Manual Verification

- [ ] [Outcome only a human can judge — who checks it and when] (O-2)

---

## Testing Strategy

### Unit Tests

- [Behavior and edge cases]

### Integration Tests

- [Cross-component scenarios, or `Not applicable — reason`]

### Manual Testing

- [Human-only scenario, or `Not applicable — reason`]

## Performance Considerations

[Relevant effects and checks, or `Not applicable — reason`]

## Migration and Rollback

[Data/deployment/compatibility steps, or `Not applicable — reason`]

## Decisions and Assumptions

- **A-1** ([decided by user | derived from repository | assumed]) — [decision] — [evidence or reason]

## References

- [Original ticket or request]
- [Related research]
- [Representative implementation and tests with file:line references]

## Follow-up Issues

- [Independently shippable remainder cut from this plan — one entry per future plan]
```

Repeat the phase block for each dependency-ordered phase. Omit an empty
verification category inside a phase only when the phase clearly states why
it does not apply. Omit `## Follow-up Issues` when nothing was cut. Do not put
unresolved product or architecture questions in the final artifact.

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
- A manual criterion is reserved for human judgment. It says who checks it
  and when (before merge, after deploy), and states explicitly when a later
  phase depends on its outcome; without that statement the implementing
  workflow does not pause for it.
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
- Automated and manual verification remain separate. Do not add a universal
  human pause between phases; the implementing workflow applies its own
  authority and interaction rules.
- `## Decisions and Assumptions` records how each material decision was
  settled: by the user, by repository evidence, or by assumption. A plan
  produced without a user to ask resolves every fork as a recorded assumption.
- Add sections for security, observability, deployment, or documentation when
  the requested change makes them material.
