---
description: Execute or resume approved AI-DLC inception stages and canonical artifacts
argument-hint: "[description] [--type hotfix|feature|refactor|migration] [--depth minimal|standard|comprehensive]"
---

# AI-DLC Inception — Claude adapter

This command is the thin Claude compatibility wrapper for the inception kernel
at `skills/aidlc-inception/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

Durable state, the execution plan, pinned rules, and answered question files
are authoritative. Arguments provide matching context only; they never silently
override stage or depth decisions. Begin or resume immediately when durable
inputs are ready. On a pending decision, write/use the canonical question file
and stop there.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/aidlc-inception/SKILL.md

@~/.claude/skills/aidlc-inception/SKILL.md

Artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/aidlc-inception/references/artifact-contract.md

@~/.claude/skills/aidlc-inception/references/artifact-contract.md

If no import resolves in a development checkout, read both files from the
project's `skills/aidlc-inception/` directory before starting. Always load the
project's `.aidlc-rule-details/` files named by the kernel; the bootstrap script
installs those pinned compatibility rules into AI-DLC-enabled projects.

Platform wiring:

- Model: inherit the active Claude session.
- Brownfield analysis: use shared `codebase-locator`, `codebase-analyzer`,
  `thoughts-locator`, and `thoughts-analyzer` adapters only for independent,
  sizeable tracks.
- Unit decomposition: use `uow-decomposer` only after the kernel's prerequisite
  and approval gates pass. The orchestrator owns canonical artifact writes and
  state transitions.
