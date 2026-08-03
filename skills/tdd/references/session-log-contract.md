# TDD session log — artifact contract

## Path

`thoughts/shared/tests/YYYY-MM-DD-TDD-SESSION-description.md`

Use the current local date and a short kebab-case description matching the test
plan. Resume the same log for continuation of the same cycle; do not create one
log per command retry.

## Required body

```markdown
# TDD Session: [Feature Name]

**Date**: [ISO date/time with timezone]
**Test Plan**: `[path]`
**Requested Phase**: `[red | green | refactor | full]`
**Repository State**: `[branch and commit at start]`

## Baseline

- **Pre-existing worktree changes**: [paths, or None]
- **Relevant implementation state**: [existing/partial/absent with evidence]
- **Test command(s)**: `[exact commands discovered in repo]`
- **Pre-existing relevant failures**: [evidence, or None observed]

## Case Dispositions

| Case ID | Layer | Disposition | Evidence |
|---|---|---|---|
| [U-01] | [unit] | [valid Red / Green / refactored-green / already covered / blocked / not_applicable] | [command, exit, salient assertion] |

## Red Phase

- **Files changed**: [paths]
- **Commands and exits**:
  - `[command]` → `[exit]`: [expected failure signal]
- **Deviations**: [plan drift/duplicate/blocked case, or None]

## Green Phase

- **Files changed**: [paths]
- **Commands and exits**:
  - `[command]` → `[exit]`: [test summary]
- **Deviations**: [or Not run — reason]

## Refactor Phase

- **Refactorings applied**: [behavior-preserving changes, or Not applicable — reason]
- **Commands and exits**:
  - `[command]` → `[exit]`: [test summary]

## Final Verification

- **Focused suite**: `[command]` → `[exit and summary]`
- **Relevant surrounding suite**: `[command]` → `[exit and summary]`
- **Coverage policy**: [measured result and configured threshold, or Not applicable — reason]
- **Manual verification**: [outcome, pending authority, or Not applicable — reason]

## Summary

- **Achieved phase**: [Red / Green / Refactored Green / Blocked]
- **Source files changed**: [paths]
- **Test files changed**: [paths]
- **Remaining blockers or follow-ups**: [items, or None]
```

## Evidence rules

- Record actual command strings and exit statuses; concise salient output is
  enough. Link a retained log when output is too large.
- Do not claim every test failed in Red when only new target assertions needed
  to fail. Record each planned case's actual disposition.
- Do not estimate duration, LOC, test ratios, coverage, or flake rate. Include
  them only when measured by a named command or timestamp source.
- Preserve prior evidence when resuming. Append new attempts or update a case's
  disposition with both the prior and current evidence; do not erase a failed
  transition.
- A skipped phase is explicit (`Not run — reason`), not silently omitted.
