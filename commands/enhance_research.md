---
description: Verify feedback and improve an existing codebase research document
argument-hint: "[research-file] [feedback, corrections, or opinions]"
---

# Enhance Research — Claude adapter

This command is the thin Claude compatibility wrapper for the research-
enhancement kernel at `skills/enhance-research/SKILL.md`. Execute that kernel
for `$ARGUMENTS`.

Proceed immediately when both the research path and feedback are present. If
one is missing, ask one short question for only that input. Explicitly supplied
corrections do not require a ritual confirmation; verify them against the code
and apply the kernel's escalation rules.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/enhance-research/SKILL.md

@~/.claude/skills/enhance-research/SKILL.md

Research artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references/artifact-contract.md

@~/.claude/skills/research-codebase/references/artifact-contract.md

Enhancement record contract:

@${CLAUDE_PLUGIN_ROOT}/skills/enhance-research/references/enhancement-record.md

@~/.claude/skills/enhance-research/references/enhancement-record.md

Shared research fleet routing:

@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references/fleet-routing.md

@~/.claude/skills/research-codebase/references/fleet-routing.md

If no import resolves in a development checkout, read the same files from
`skills/enhance-research/` and `skills/research-codebase/references/` in the
project.

Platform wiring:

- Model: inherit the active Claude session.
- Subagents: use the shared research fleet only when the kernel's bounded
  delegation threshold is met; otherwise work in the main context.
