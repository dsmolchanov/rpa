# Implementation plan — artifact contract

Single source of truth for the `/create_plan` output shape. It preserves the
stable sections consumed by the plan iteration, enhancement, implementation,
and validation workflows while removing universal approval pauses and fake
verification commands.

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
checkout, branch, and repository consistently. A plan does not require YAML
frontmatter; repository-specific conventions may add it without changing the
body contract.

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

## What We're NOT Doing

- [Explicit scope exclusion]

## Implementation Approach

[Selected strategy, important dependencies, and reasoning]

## Phase 1: [Outcome-oriented name]

### Overview

[What this phase accomplishes and why it comes here]

### Changes Required

#### 1. [Component or file group]

**Files**: `path/to/existing-or-new-file.ext`

**Changes**:

- [Specific symbol, behavior, contract, or data-flow change]
- [Compatibility, migration, or rollback handling when applicable]

### Success Criteria

#### Automated Verification

- [ ] [Exact repository command and expected outcome]

#### Manual Verification

- [ ] [Only an outcome that genuinely requires a human]

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

## References

- [Original ticket or request]
- [Related research]
- [Representative implementation and tests with file:line references]
```

Repeat the phase block for each dependency-ordered phase. Omit an empty
verification category inside a phase only when the phase clearly states why
it does not apply. Do not put unresolved product or architecture questions in
the final artifact.

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
- Add sections for security, observability, deployment, or documentation when
  the requested change makes them material.
