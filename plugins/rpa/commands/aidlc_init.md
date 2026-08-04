---
description: Bootstrap the current repository for the AI-DLC compatibility workflow
argument-hint: "[--force-overlay] [--force-claude] - Optional bootstrap flags"
allowed-tools: Read, Glob, Grep, LS, Bash(pwd:*), Bash(git rev-parse:*), Bash(test:*), Bash(ls:*), Bash(bash:*), Bash(cat:*)
---

# AI-DLC Init

You bootstrap the current repository for the AI-DLC compatibility workflow.

## Goal

Run the tracked bootstrap script instead of manually creating `aidlc-docs/`, `.aidlc-rule-details/`, overlay files, and CLAUDE bootstrap text.

## Workflow

### Step 1: Resolve the Repository Root

- Determine the current repository root with `git rev-parse --show-toplevel`
- Treat that path as the bootstrap target

### Step 2: Resolve the Bootstrap Script

Prefer these locations in order:

1. `~/.claude/scripts/bootstrap_aidlc_project.sh`
2. `scripts/bootstrap_aidlc_project.sh` in the current repository

If neither exists, stop and tell the user to install or sync the RPA scripts first.

### Step 3: Run the Script

Run:

```bash
bash [resolved-script-path] [optional flags from $ARGUMENTS] "[repo-root]"
```

Supported pass-through flags:

- `--force-overlay`
- `--force-claude`

Do not invent extra flags.

### Step 4: Summarize the Result

After the script completes:

- confirm the canonical paths now exist:
  - `aidlc-docs/aidlc-state.md`
  - `aidlc-docs/audit.md`
  - `aidlc-docs/inception/plans/execution-plan.md`
  - `thoughts/shared/steering-rules/default.yaml`
- tell the user whether `CLAUDE.md` was created, preserved, or appended
- direct the user to review `thoughts/shared/steering-rules/default.yaml`

## Completion Rules

- On success, tell the user to run `/aidlc_start "<full request>"` next
- If bootstrap files already exist, treat the command as an idempotent refresh, not a failure

## What Not To Do

- Do not manually recreate bootstrap logic inline
- Do not overwrite `CLAUDE.md` unless the user passed `--force-claude`
- Do not skip reporting the generated overlay path
