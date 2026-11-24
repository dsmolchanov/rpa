# Implementation record — artifact contract

Single source of truth for the section the `implement-plan` workflow maintains
inside the plan it executes. The record is the handoff between sessions and
the input to `/validate_plan`: it says what was done, what differs from the
plan, and what is still owed. It is a set of claims — validation and CI
re-run the commands; the record does not replace them.

## Placement

One `## Implementation Record` section at the end of the plan file, after
`## References` and after `## Enhancement History` when that exists. Create
it on the first run and update it in place on later runs; never add a second
one.

The record uses plain bullets and tables. Checkbox syntax is reserved for the
plan's success criteria, which are the only lines tooling counts.

## Shape

```markdown
## Implementation Record

**Status**: [in_progress | complete | blocked]
**Base**: `[commit the work started from]` on `[branch]`
**Baseline**: [command and outcome, including pre-existing failures — or `Not run — reason`]
**Last updated**: [YYYY-MM-DD]

### Phases

| Phase | State | Invariant pass | Commit |
|---|---|---|---|
| [N: name] | [complete / partial / blocked / not started] | [invariants checked and outcome, or `None touched`] | [`short sha`, or `Not committed — reason`] |

### Deviations

| ID | Phase | Plan says | Done instead | Reason | Obligation affected |
|---|---|---|---|---|---|
| D-1 | [N] | [quoted or cited plan text] | [what was implemented] | [evidence-backed reason] | [`O-n`, or `None`] |

### Assumptions

- (Phase [N]) [ambiguity] → [narrowest reading taken] — [why]

### Out-of-scope Findings

- [Defect or risk noticed outside the plan's scope, with `file:line`; not fixed]

### Awaiting Human Verification

- [Manual criterion, quoted from the plan, with its phase]

### Blockers

- [Criterion or obligation that cannot be met, the evidence, and what would unblock it]
```

## Rules

- **Status** is `complete` only when every automated criterion of every phase
  passed on the final tree. Unticked manual criteria do not prevent
  `complete`; they are listed under Awaiting Human Verification. `blocked`
  means an obligation conflict or an exhausted fix loop stopped the run;
  `in_progress` is every other unfinished state.
- **Phases** has one row per phase the run touched or was asked to run.
- A **deviation** is any difference between the plan's text and what was
  implemented, including harmless drift. Recording it is what lets a reviewer
  tell an adaptation from an omission; a deviation whose last column names an
  obligation is the kind a reviewer may block on.
- Keep a subsection whose content is empty as the single line `None`. Do not
  drop the heading: its presence is how a reader knows the question was
  considered.
- Entries cite `file:line`, commits, or commands. Do not paste command output
  or diffs; state the outcome and where it can be reproduced.
- When TDD receipts exist for a criterion, cite the receipt reference instead
  of restating the run.
- A later session appends rows and entries and updates Status, Baseline, and
  Last updated. It does not rewrite earlier entries except to correct a
  demonstrable error, and says so when it does.
