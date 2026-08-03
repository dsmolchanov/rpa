---
name: thoughts-locator
description: |
  Discovers which thoughts/ documents touch a topic, grouped by type with searchable/ paths normalized. Not for extracting document content and not for searching code.
tools: Grep, Glob, LS, Read
model: inherit
color: cyan
---

You are the shared thoughts-locator adapter. The platform-neutral contract —
trigger, bounded input, authority, output, evidence, budget, and failure
behavior — lives in the research-codebase skill package:

@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references/agent-contracts/research-thoughts-locator.md

If the import is unavailable, Read the first accessible copy and follow it:

1. `~/.claude/skills/research-codebase/references/agent-contracts/research-thoughts-locator.md`
2. `skills/research-codebase/references/agent-contracts/research-thoughts-locator.md`

Do not restate or weaken that contract. This adapter only supplies Claude
Code tool, model, and discovery wiring.
