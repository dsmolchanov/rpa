---
description: Execute an evidence-bearing Red-Green-Refactor cycle from a test plan
argument-hint: "[test-plan-path] [phase: red|green|refactor|full]"
---

# TDD — Claude adapter

This command is the thin Claude compatibility wrapper for the TDD kernel at
`skills/tdd/SKILL.md`. Execute that kernel for `$ARGUMENTS`.

Read the named test plan fully and begin the requested phase immediately.
`full` is the default. If no plan path is supplied, ask for it in one short
sentence. Do not pause mechanically between Red, Green, and Refactor during a
full authorized run; use the kernel's evidence transitions and escalation
conditions.

Kernel (the two imports support plugin-root and Quick Install layouts):

@${CLAUDE_PLUGIN_ROOT}/skills/tdd/SKILL.md

@~/.claude/skills/tdd/SKILL.md

Consumed test-plan contract:

@${CLAUDE_PLUGIN_ROOT}/skills/create-test-plan/references/artifact-contract.md

@~/.claude/skills/create-test-plan/references/artifact-contract.md

Session-log contract:

@${CLAUDE_PLUGIN_ROOT}/skills/tdd/references/session-log-contract.md

@~/.claude/skills/tdd/references/session-log-contract.md

Testing patterns (fallback after repository-local conventions):

@${CLAUDE_PLUGIN_ROOT}/docs/testing-patterns.md

@~/.claude/docs/testing-patterns.md

If no import resolves in a development checkout, read the corresponding files
from `skills/tdd/`, `skills/create-test-plan/references/`, and `docs/` in the
project.

Platform wiring:

- Model: inherit the active Claude session.
- Analysis/generation adapters: use `test-analyzer`, `test-architect`,
  `test-generator`, `test-runner`, or `code-analyzer` only for independent,
  sizeable tracks that meet the kernel's delegation threshold.
- Shell permissions and repository policy bind the exact test commands. Never
  substitute the old universal 80% threshold for project configuration.
