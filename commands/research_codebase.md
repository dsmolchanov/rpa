---
description: Document codebase as-is with thoughts directory for historical context
argument-hint: "[research question or files to read]"
---

# Research Codebase — Claude adapter

This command is the thin compatibility wrapper for the research workflow
kernel at `skills/research-codebase/SKILL.md` (conventions §1: workflow
substance lives in the kernel once; this file carries platform wiring
only).

Execute the research workflow kernel, included below verbatim, on the
user's request. If `$ARGUMENTS` contains the research question (or files
to read), begin the research immediately — no greeting, no confirmation.
Only when the invocation carries no question at all, ask for one in a
single short sentence.

The kernel defines intent, scope and authority (documentarian: describe
what exists, never critique or propose), the artifact contract, process
guidance, delegation policy (the shared research fleet), acceptance
criteria, verification gates, and escalation conditions — follow it as
written. The artifact contract is also included below: emit its
frontmatter schema and body template exactly.

Kernel (single source: `skills/research-codebase/SKILL.md`; the two
imports below cover the two install layouts — the plugin root when
`${CLAUDE_PLUGIN_ROOT}` is set, the Quick Install copy under
`~/.claude` otherwise. Exactly one resolves per layout; an unresolved
or duplicate import is inert, the content is identical):

@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/SKILL.md

@~/.claude/skills/research-codebase/SKILL.md

Artifact contract (single source:
`skills/research-codebase/references/artifact-contract.md`, same
dual-layout imports):

@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references/artifact-contract.md

@~/.claude/skills/research-codebase/references/artifact-contract.md

(If neither import resolved above — a checkout without either install —
read the same two files from the project's
`skills/research-codebase/` directory before starting.)

Platform wiring:

- Model: inherited from the active Claude session; the pilot-only Opus pin
  ended with the pilot.
- Subagents: the kernel routes through the shared `codebase-*`, `thoughts-*`,
  and `web-search-researcher` adapters. Historical `research-v2-*` aliases
  remain only so frozen pilot installations can be reproduced.
