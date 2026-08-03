---
description: Create an implementation-ready plan grounded in the current repository
argument-hint: "[ticket/research file or task description]"
---

# Create Plan — Claude adapter

This command is the thin Claude compatibility wrapper for the planning kernel
at `skills/create-plan/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

If the arguments identify the task, ticket, research document, or relevant
files, begin immediately. If they do not identify a planning target, ask for
it in one short sentence. Do not require ritual approval of an outline when
the user's request and repository evidence already settle the approach.

The kernel defines intent, write authority, research depth, planning quality,
acceptance criteria, verification, and escalation. The artifact contract
defines the persistent plan shape. Load both before writing.

Kernel (the two imports support plugin-root and Quick Install layouts; exactly
one resolves in a normal installation):

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/SKILL.md

@~/.claude/skills/create-plan/SKILL.md

Artifact contract:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/artifact-contract.md

@~/.claude/skills/create-plan/references/artifact-contract.md

Planning research routing:

@${CLAUDE_PLUGIN_ROOT}/skills/create-plan/references/research-routing.md

@~/.claude/skills/create-plan/references/research-routing.md

If no import resolves in a development checkout, read the same three files
from the project's `skills/create-plan/` directory before starting.

Platform wiring:

- Model: inherit the active Claude session.
- Subagents: when the kernel's delegation threshold is met, use the shared
  `codebase-*`, `thoughts-*`, and `web-search-researcher` adapters named in the
  routing reference. Otherwise research in the main context.
