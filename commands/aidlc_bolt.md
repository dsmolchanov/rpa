---
description: Execute one approved construction unit through the per-unit construction loop
argument-hint: "[unit-path|unit-id] - Execute a specific construction unit"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(npm test:*), Bash(npx jest:*), Bash(pytest:*), Bash(python -m pytest:*), Bash(go test:*), Bash(cargo test:*), Bash(make test:*), Bash(make build:*), Bash(npm run test:*), Bash(npm run build:*), Bash(mkdir:*)
model: opus
---

# AI-DLC Bolt

You execute one construction unit from the canonical AI-DLC artifacts.

## Required Inputs

- a unit path or unit ID
- `aidlc-docs/aidlc-state.md`
- approved unit artifacts under `aidlc-docs/inception/units/`

## Construction Loop

For the selected unit, execute only the work needed for that unit:

1. Functional Design when needed
2. NFR Requirements when needed
3. NFR Design when needed
4. Infrastructure Design when needed
5. Code Planning
6. Code Generation / implementation

## Artifact Rules

Create a unit execution directory when needed:

- `aidlc-docs/construction/units/[unit-id]/`

Write unit-scoped artifacts such as:

- `functional-design.md`
- `nfr-requirements.md`
- `nfr-design.md`
- `infrastructure-design.md`
- `code-plan.md`
- `execution.md`

Update unit checkboxes and status in the same interaction.

## Retry Rules

If a unit-level verification step fails, retry with the error context up to a bounded limit before giving up.

## State Updates

Update `aidlc-docs/aidlc-state.md` with the active unit and completion status.

## Important Constraint

Completing a bolt does not complete Construction. Global completion requires `/aidlc_build_test`.

## What Not To Do

- Do not silently expand scope beyond the selected unit
- Do not claim Construction is complete without the global Build and Test stage
