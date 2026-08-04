---
description: Execute the global Build and Test stage after construction units are complete
argument-hint: "[optional scope] - Run global build and test after construction units"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(npm test:*), Bash(npx jest:*), Bash(pytest:*), Bash(python -m pytest:*), Bash(go test:*), Bash(cargo test:*), Bash(make test:*), Bash(make lint:*), Bash(make typecheck:*), Bash(make build:*), Bash(npm run lint:*), Bash(npm run typecheck:*), Bash(npm run build:*), Bash(git diff:*), Bash(git status:*), Bash(mkdir:*)
---

# AI-DLC Build and Test

You execute the global Build and Test stage for the AI-DLC compatibility workflow.

## Required Inputs

- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/inception/plans/execution-plan.md`
- completed unit execution artifacts under `aidlc-docs/construction/units/`
- `thoughts/shared/steering-rules/default.yaml`

## Workflow

1. Confirm all prerequisite units marked for construction are complete
2. Spawn `quality-gate-runner`
3. Write `aidlc-docs/construction/build-and-test/build-and-test-report.md`
4. Update `aidlc-docs/aidlc-state.md` with Build and Test status
5. If checks fail, link the failure back to impacted unit artifacts

Use a `Task` block:

```yaml
Task - Build and Test:
  subagent_type: quality-gate-runner
  Prompt: |
    Run the global Build and Test stage for the current AI-DLC workflow.
    Read aidlc-docs/aidlc-state.md, the execution plan, and the plugin overlay.
    Return a markdown report with commands, exit codes, durations, and concise failures.
```

## Output Requirements

The persisted report must include:

- commands run
- pass/fail status
- exit codes
- durations
- concise failure excerpts

## Completion Rules

- On success, Construction is complete and the user may choose `/aidlc_operations`
- On failure, stop and point to the affected unit(s)

## What Not To Do

- Do not skip required checks from the plugin overlay
- Do not treat unit-local verification as a substitute for this stage
