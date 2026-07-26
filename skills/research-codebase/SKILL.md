---
name: research-codebase
description: >
  STRUCTURAL SKELETON — not yet executable; never select this skill for
  research requests. The working implementation remains the
  /research_codebase command (frozen baseline) until the modernization
  pilot's behavioral rewrite lands here. This package currently carries
  only the artifact contract and package layout.
disable-model-invocation: true
permission-class: "read_only (target repo) + workspace_write (thoughts/shared/research/ only)"
invocation: "none"
---

# Research Codebase — kernel (structural skeleton, v0.2.1)

Status: **skeleton only.** This package is the kernel carrier for the
`/research_codebase` workflow per `docs/conventions.md` §1. The behavioral
rewrite lands in the pilot's candidate phase
(`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`);
until then the authoritative behavior remains
`commands/research_codebase.md` (the frozen baseline).

Discovery & invocation (conventions §2.0) is declared in the frontmatter
above (`permission-class`, `invocation` — kernel fields; platform adapters
map them to their harness's supported fields). The skeleton is deliberately
**non-invocable in both directions**: `invocation: none` declares it closed
to user invocation as well, `disable-model-invocation: true` keeps it out
of automatic skill selection, and the description warns against selection —
so fresh plugin installs cannot route research requests here before the
rewrite; the working entry point remains `/research_codebase`. The
trigger-rich production description and real invocation modes arrive at
candidate freeze.

Kernel sections to be completed in the rewrite, in the §2 anatomy order:
intent · scope & authority · artifact contract
(`references/artifact-contract.md`, already extracted) · process guidance ·
acceptance criteria & evidence · deterministic verification profile ·
escalation conditions.

Package layout:

- `references/artifact-contract.md` — the research-document contract
  (single source; extracted verbatim from the baseline command).
- `references/agent-contracts/` — platform-neutral contracts of the
  research agent fleet (extracted during the rewrite; see its README).
- `evals/public/` — non-sensitive eval harness assets only.
- `scripts/` — deterministic operations (populated during the rewrite; see
  its README).
