---
description: Apply focused, evidence-backed changes to an existing implementation plan
argument-hint: "[plan-file] [requested changes]"
---

# Iterate Plan — Claude adapter

This command is the thin Claude compatibility wrapper for the plan-iteration
kernel at `skills/iterate-plan/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

Proceed immediately when both a plan path and requested changes are present.
If one is missing, ask one short question for only that input. Explicitly
requested, in-scope edits do not require a separate confirmation ritual.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/iterate-plan/SKILL.md

@~/.claude/skills/iterate-plan/SKILL.md

Canonical plan artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/artifact-contract.md

@~/.claude/skills/create-plan/references/artifact-contract.md

Optional planning research routing:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/research-routing.md

@~/.claude/skills/create-plan/references/research-routing.md

If no import resolves in a development checkout, read those files from
`skills/iterate-plan/` and `skills/create-plan/references/` in the project.

Platform wiring:

- Model: inherit the active Claude session.
- Subagents: use the shared research adapters only when the kernel's
  proportional-research threshold is met; otherwise work in the main context.
