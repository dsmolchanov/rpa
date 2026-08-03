# Test and verification plan — artifact contract

Single source of truth for `/create_test_plan` output. The artifact is a
feature-scoped blueprint consumed by `/tdd`; it is not a generated test suite.

## Path

`thoughts/shared/tests/YYYY-MM-DD-TEST-XXXX-short-description.md`

- Use the source ticket identifier in place of `XXXX` when one exists.
- When no ticket exists, use a stable short identifier derived from the source
  rather than the literal placeholder `XXXX`.
- Use the current local date and a short kebab-case description.

## Required body

```markdown
# [Feature Name] Test & Verification Plan

**Source**: `[implementation plan, ticket, PR, or code path]`
**Date**: `[YYYY-MM-DD]`
**Scope**: `[unit | integration | e2e | all applicable]`
**Constraints**: `[explicit constraints, or Not applicable — reason]`

## 0. Repository Reality

- **Detected test stack**: [framework/version and defining file]
- **Existing relevant tests**: [paths and covered behavior]
- **Conventions and utilities**: [fixtures/builders/helpers to reuse]
- **CI and local commands**: [exact commands and where defined]

## 1. Risk Model

| Risk | Likelihood | Impact | Consequence | Verification response |
|---|---|---|---|---|
| [failure mode] | [high/medium/low + reason] | [high/medium/low + reason] | [observable harm] | [test layers/cases] |

## 2. Requirements to Verification Mapping

| Requirement or invariant | Evidence source | Positive coverage | Negative coverage | Exclusion reason |
|---|---|---|---|---|
| [behavior] | [source section or file:line] | [case IDs] | [case IDs] | [blank or reason] |

## 3. Red-Phase Test Specification

### Unit Tests

**Location**: `path/to/test_file.ext`

| ID | Behavior | Setup / input | Expected observable result | Dependencies / fixtures |
|---|---|---|---|---|
| U-01 | [behavior] | [setup] | [exact assertion] | [real/mock and helper] |

### Integration Tests

**Location**: `path/to/integration_test.ext`

| ID | Boundary scenario | Setup / input | Expected observable result | Determinism / cleanup |
|---|---|---|---|---|
| I-01 | [scenario] | [setup] | [exact assertion] | [clock/network/data cleanup] |

### End-to-End Tests

**Location**: `path/to/e2e_test.ext`

| ID | Journey | Steps | Expected observable result | Flake controls |
|---|---|---|---|---|
| E-01 | [critical flow] | [steps] | [assertions] | [stable signals/stubs] |

For a test layer outside scope, replace its table with
`Not applicable — [reason]`.

## 4. Test Data and Environment

- **Fixtures/builders**: [existing and new]
- **Environment/configuration**: [requirements]
- **Identity/roles**: [accounts or permissions]
- **Determinism controls**: [time/randomness/network/IDs]
- **Isolation and cleanup**: [strategy]

## 5. Manual Exploratory Charter

- [Human-only scenario and observable result]
- [Or `Not applicable — all material behavior is deterministically covered`]

## 6. Quality Gates and Exit Criteria

### Automated

- [ ] `[exact repository command]` — [expected result]

### Manual

- [ ] [Human-only acceptance outcome, or `Not applicable — reason`]

## 7. Non-Functional Verification

- **Performance**: [check/threshold from requirements, or Not applicable]
- **Security/privacy**: [check, or Not applicable]
- **Reliability/observability**: [check, or Not applicable]

## 8. Execution Handoff

- **Recommended workflow**: `/tdd [this plan path]`
- **Case order**: [dependency/risk-ordered IDs]
- **Blocking setup**: [prerequisites, or None]

## References

- [Source artifact]
- [Relevant production code and existing tests with file:line references]
```

## Content rules

- Keep case IDs unique and stable within the document: `U-*`, `I-*`, `E-*`.
- Every case names an observable assertion, not merely “works” or “handles”.
- Every negative case maps to a real failure mode; do not add ceremonial sad
  paths for impossible conditions.
- Cite installed tooling and existing tests. New tooling is included only when
  the source explicitly authorizes that dependency change.
- Coverage and performance thresholds come from repository policy or source
  requirements. If neither defines one, specify what to measure and avoid an
  invented number.
- The plan may name test scaffolds but never creates them.
