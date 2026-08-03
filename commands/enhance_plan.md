---
description: Synthesize multiple critiques into one evidence-backed implementation plan
argument-hint: "[plan-file] [feedback, opinions, or review sources]"
---

# Enhance Plan — Claude adapter

This command is the thin Claude compatibility wrapper for the plan-enhancement
kernel at `skills/enhance-plan/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

Proceed immediately when both the target plan and feedback are present. If one
is missing, ask one short question for only that input. Do not require a
separate approval of the synthesis when the supplied feedback and repository
evidence resolve it; stop only for the material forks defined by the kernel.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/enhance-plan/SKILL.md

@~/.claude/skills/enhance-plan/SKILL.md

Canonical plan artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/artifact-contract.md

@~/.claude/skills/create-plan/references/artifact-contract.md

Enhancement record contract:

@${CLAUDE_PLUGIN_ROOT}/skills/enhance-plan/references/enhancement-record.md

@~/.claude/skills/enhance-plan/references/enhancement-record.md

Optional planning research routing:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/research-routing.md

@~/.claude/skills/create-plan/references/research-routing.md

If no import resolves in a development checkout, read those files from
`skills/enhance-plan/` and `skills/create-plan/references/` in the project.

Platform wiring:

- Model: inherit the active Claude session.
- Subagents: use the shared research adapters only when the kernel's bounded
  research threshold is met; otherwise synthesize in the main context.
