---
description: Execute approved inception stages and write canonical AI-DLC artifacts
argument-hint: "[description] [--type hotfix|feature|refactor|migration] [--depth minimal|standard|comprehensive]"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(mkdir:*), Bash(git rev-parse:*), Bash(git diff:*)
---

# AI-DLC Inception

You execute the approved inception stages from the compatibility workflow.

## Required Inputs

- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/inception/plans/execution-plan.md`
- any answered question files under `aidlc-docs/inception/questions/`

If required question files exist and any `[Answer]:` field is blank, stop and ask the user to answer them first.

## Stage Execution Rules

Follow the execution plan exactly. Depth controls detail level inside executed stages; it does not replace `EXECUTE` / `SKIP`.

Possible stages:

- Workspace Detection
- Reverse Engineering
- Requirements Analysis
- User Stories
- Workflow Planning
- Application Design
- Units Planning / Units Generation

## Recommended Agent Usage

- `codebase-locator` for reverse-engineering scope discovery
- `codebase-analyzer` for brownfield implementation understanding
- `thoughts-locator` and `thoughts-analyzer` for historical context
- `uow-decomposer` only after requirements/workflow/design artifacts are approved

Use `Task` blocks when delegating:

```yaml
Task - Reverse Engineering:
  subagent_type: codebase-analyzer
  Prompt: |
    Analyze the current workspace for the inception phase.
    Focus on reverse engineering needs and brownfield constraints.
    Return concise file references and architecture notes for canonical inception artifacts.

Task - Historical Context:
  subagent_type: thoughts-analyzer
  Prompt: |
    Analyze relevant thoughts documents for this request.
    Return only high-value historical context that affects inception artifacts.

Task - Unit Planning:
  subagent_type: uow-decomposer
  Prompt: |
    Generate AI-DLC-compatible units from the approved requirements, workflow planning,
    and application design artifacts under aidlc-docs/inception/.
    Return unit summaries plus dependency and story-map content.
```

## Canonical Outputs

Write artifacts under `aidlc-docs/inception/`:

- `requirements/requirements.md`
- `reverse-engineering/system-map.md`
- `user-stories/user-stories.md`
- `application-design/application-design.md`
- `units/unit-of-work.md`
- `units/unit-of-work-dependency.md`
- `units/unit-of-work-story-map.md`

Update `aidlc-docs/aidlc-state.md` as stages complete.

## Review Gate

If a generated artifact requires approval before continuing, emit a question/approval file in `aidlc-docs/inception/questions/` and stop.

## Completion Rules

- Finish only the stages marked `EXECUTE`
- When unit artifacts are ready, direct the user to `/aidlc_bolt`

## What Not To Do

- Do not collapse inception into a single plugin-local plan file
- Do not skip required stages because the depth is low
