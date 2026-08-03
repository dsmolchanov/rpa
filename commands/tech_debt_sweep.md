---
description: Produce an evidence-backed debt inventory or apply selected deterministic fixes
argument-hint: "[apply [paydown-plan] [PAY-IDs...]]"
---

# Tech Debt Sweep — Claude adapter

This command is the thin Claude compatibility wrapper for the debt-sweep kernel
at `skills/tech-debt-sweep/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

No argument selects scan mode. `apply` selects apply mode and may name a
paydown plan and PAY-IDs; when omitted, resolve only an unambiguous latest plan
and its eligible entries. Begin immediately within that authority. Do not treat
formatters, lint `--fix`, debug deletion, dependency updates, or refactors as
safe without the kernel's per-entry eligibility evidence.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/tech-debt-sweep/SKILL.md

@~/.claude/skills/tech-debt-sweep/SKILL.md

Artifact contract and metrics schema:

@${CLAUDE_PLUGIN_ROOT}/skills/tech-debt-sweep/references/artifact-contract.md

@~/.claude/skills/tech-debt-sweep/references/artifact-contract.md

If no import resolves in a development checkout, read both files from the
project's `skills/tech-debt-sweep/` directory before starting.

Platform wiring:

- Model: inherit the active Claude session.
- Scan adapters: select only applicable, independent tracks from
  `dependency-auditor`, `debt-scanner`, `architecture-guard`, `docs-auditor`,
  `config-auditor`, and `god-module-finder`. Their absence or failure is a
  visible `not_assessed` result, not a reason to fabricate a clean category.
- Verification adapters such as `test-runner` may assist with bounded apply
  evidence, but the orchestrator owns edits and final diff inspection.
