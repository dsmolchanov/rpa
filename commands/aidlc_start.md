---
description: Initialize or resume the AI-DLC compatibility workflow and write the execution plan
argument-hint: "[description or ticket path] - Describe the work to initialize"
allowed-tools: Read, Glob, Grep, LS, Edit, Write, TodoWrite, Bash(mkdir:*), Bash(date:*), Bash(git rev-parse:*), Bash(git branch:*), Bash(git status:*)
model: opus
---

# AI-DLC Start

You initialize or resume the AI-DLC compatibility workflow.

## Goals

1. Create or resume canonical state in `aidlc-docs/`
2. Resolve compatibility rules and plugin overlay settings
3. Classify the request
4. Write `aidlc-docs/inception/plans/execution-plan.md`
5. Emit file-based questions when clarification is required

## Workflow

### Step 1: Load Existing Context

- Read `aidlc-docs/aidlc-state.md` if it exists
- Read `aidlc-docs/audit.md`
- Read `.aidlc-rule-details/core-workflow.md`
- Read `.aidlc-rule-details/common/question-format-guide.md`
- Read `.aidlc-rule-details/common/depth-levels.md`
- Read `thoughts/shared/steering-rules/default.yaml`

### Step 2: Normalize Inputs

- If `$ARGUMENTS` references a file, read it fully
- If `$ARGUMENTS` is free text, treat it as the raw request
- Append the raw request to `aidlc-docs/audit.md` with timestamp and git context

### Step 3: Detect Workspace Type

Infer `greenfield` or `brownfield` from the repository contents.

### Step 4: Classify the Change

Use `thoughts/shared/steering-rules/default.yaml` heuristics to propose:

- change type: `hotfix|feature|refactor|migration`
- default depth: `minimal|standard|comprehensive`

If classification is ambiguous, create a question file instead of relying on chat-only confirmation.

### Step 5: Create Question Files When Needed

If clarification or approval is required, write markdown files under `aidlc-docs/inception/questions/`.

Use this format:

```markdown
# Question: [short title]

## Context
[why this answer is needed]

## Question
[question text]

## Options
- A. [option]
- B. [option]
- C. [option]

[Answer]:
```

If any required question is unanswered, stop after writing the question files and tell the user to answer them in-place.

### Step 6: Write the Execution Plan

Update `aidlc-docs/inception/plans/execution-plan.md` with stage rows that explicitly record:

- `EXECUTE` or `SKIP`
- depth for that stage
- rationale
- approval status

Do not use depth as a substitute for the `EXECUTE`/`SKIP` decision.

### Step 7: Update State

Update `aidlc-docs/aidlc-state.md` with:

- current request
- workspace type
- current stage
- current depth
- active extensions
- artifact pointers

## Completion Rules

- If questions are pending, stop after creating them
- If the execution plan is ready, direct the workflow to `/aidlc_inception`

## What Not To Do

- Do not depend on chat-only confirmation for required AI-DLC decisions
- Do not write canonical state to `thoughts/shared/`
