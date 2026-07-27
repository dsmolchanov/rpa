---
description: Document codebase as-is with thoughts directory for historical context
argument-hint: "[research question or files to read]"
model: opus
---

# Research Codebase — Claude adapter

This command is the thin compatibility wrapper for the research workflow
kernel at `skills/research-codebase/SKILL.md` (conventions §1: workflow
substance lives in the kernel once; this file carries platform wiring
only).

Execute the **research-codebase** skill on the user's request. If
`$ARGUMENTS` contains the research question (or files to read), begin the
research immediately — no greeting, no confirmation. Only when the
invocation carries no question at all, ask for one in a single short
sentence.

The kernel defines intent, scope and authority (documentarian: describe
what exists, never critique or propose), the artifact contract, process
guidance, delegation policy (the `research-v2-*` fleet), acceptance
criteria, verification gates, and escalation conditions — follow it as
written there.

Platform wiring:

- **Model pin `opus`** — pilot-only parity control: the frozen baseline
  command pins `model: opus`, and the pilot's registered runtime
  configuration requires both arms to resolve to the same model
  (`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`,
  Runtime configuration). Re-evaluate against conventions §5 (default: no
  pin) when the pilot concludes.
- Subagents: the kernel's fleet is adapted by `agents/research-v2-*.md`;
  the legacy shared fleet stays reserved for the frozen baseline and the
  other command families.
