---
description: Create a feature-scoped verification blueprint from real repository evidence
argument-hint: "[source-path] [scope: unit|integration|e2e|all] [constraints]"
---

# Create Test Plan — Claude adapter

This command is the thin Claude compatibility wrapper for the test-planning
kernel at `skills/create-test-plan/SKILL.md`. Execute that kernel for
`$ARGUMENTS`.

Begin immediately when a source path or unambiguous source target is present.
If no source of truth is supplied, ask for it in one short sentence. Scope
defaults to all applicable test layers; do not require confirmation of a
strategy already determined by the source and repository evidence.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/create-test-plan/SKILL.md

@~/.claude/skills/create-test-plan/SKILL.md

Artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/create-test-plan/references/artifact-contract.md

@~/.claude/skills/create-test-plan/references/artifact-contract.md

If no import resolves in a development checkout, read both files from the
project's `skills/create-test-plan/` directory before starting.

Platform wiring:

- Model: inherit the active Claude session.
- Read-only analysis adapters: use `test-analyzer` for a sizeable
  infrastructure inventory, `test-architect` for complex dependency
  boundaries, and the shared `codebase-*` agents for independent codebase
  tracks. Delegation is optional and bounded by the kernel.
- This command writes only the plan. It never invokes `test-generator` to
  create test files; execution belongs to `/tdd` or `/test_suite`.
