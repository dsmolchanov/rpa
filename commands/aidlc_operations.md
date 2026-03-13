---
description: Generate experimental operations artifacts beyond the current upstream AI-DLC core
argument-hint: "[build-test-report-path] - Generate experimental operations artifacts"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(mkdir:*)
model: opus
---

# AI-DLC Operations (Experimental)

You generate experimental operations artifacts after core Construction is complete.

## Required Inputs

- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/construction/build-and-test/build-and-test-report.md`
- canonical inception and construction artifacts under `aidlc-docs/`

If the Build and Test stage is incomplete or failed, stop.

## Workflow

1. Read canonical state and recent construction outputs
2. Spawn `operations-planner`
3. Spawn `steering-rules-checker`
4. Write an operations artifact under `aidlc-docs/operations/`
5. Label the output clearly as an experimental plugin extension

Use `Task` blocks:

```yaml
Task - Experimental Operations Plan:
  subagent_type: operations-planner
  Prompt: |
    Generate an experimental operations artifact from canonical aidlc-docs inception and construction outputs.
    Include deployment, monitoring, rollback, and MANUAL REVIEW REQUIRED markers where confidence is low.

Task - Compatibility Compliance:
  subagent_type: steering-rules-checker
  Prompt: |
    Validate the current AI-DLC state against the active compatibility rules, enabled extensions,
    and plugin overlay. Return a concise compliance summary suitable for the operations artifact.
```

## Output Expectations

The operations artifact should include:

- deployment checklist
- monitoring guidance
- rollback plan
- compliance summary
- `MANUAL REVIEW REQUIRED` markers where confidence is limited

## What Not To Do

- Do not present this as upstream-core parity
- Do not fabricate infrastructure details
