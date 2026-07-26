---
name: research-codebase
description: >
  Produce a durable research document explaining how part of a codebase
  works, with file:line evidence, saved to thoughts/shared/research/.
  Trigger for "research / document / explain how X works" requests that
  should yield a persistent artifact. Do NOT trigger for quick ad-hoc
  lookups (plain search or an Explore agent is cheaper) or for
  planning/implementation work (/create_plan, /implement_plan).
permission-class: "read_only (target repo) + workspace_write (thoughts/shared/research/ only)"
invocation: "user, model"
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
map them to their harness's supported fields, e.g. Claude Code
`allowed-tools` / `disable-model-invocation`).

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
