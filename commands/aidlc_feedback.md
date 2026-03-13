---
description: Collect structured retrospective feedback as an experimental AI-DLC extension
argument-hint: "[operations-path] - Capture structured retrospective feedback"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(mkdir:*), Bash(date:*)
model: opus
---

# AI-DLC Feedback (Experimental)

You collect retrospective feedback as an experimental extension to the compatibility workflow.

## Required Inputs

- `aidlc-docs/aidlc-state.md`
- an operations artifact under `aidlc-docs/operations/`

## Workflow

1. Read the operations artifact and canonical construction state
2. If structured feedback is missing, create a markdown question file under `aidlc-docs/operations/` that uses `[Answer]:`
3. If required answers are still missing, stop after writing the question file
4. Spawn `feedback-collector`
5. Write a retrospective artifact under `aidlc-docs/operations/feedback-*.md`
6. Suggest overlay or extension changes without editing them directly

Use a `Task` block:

```yaml
Task - Experimental Feedback Summary:
  subagent_type: feedback-collector
  Prompt: |
    Generate a retrospective feedback artifact from the current AI-DLC state,
    experimental operations artifact, build-and-test report, and any answered feedback question files.
    Link observations back to canonical aidlc-docs artifacts.
```

## Question Template

```markdown
# Feedback Questions

## What Went Well?
[Answer]:

## What Did Not Go Well?
[Answer]:

## Unexpected Behavior
[Answer]:

## Follow-up Needed
[Answer]:
```

## What Not To Do

- Do not collect required feedback only through chat
- Do not mutate overlay or extension files directly
