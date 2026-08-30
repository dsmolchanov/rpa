---
description: "Deprecated 2.x alias for the test-suite skill: create, update, and maintain test suites (canonical: /rpa:test-suite)"
argument-hint: "[audit|adopt|init|update|gaps|run|ci|standardize] [options]"
allowed-tools: Read, Glob, Grep, LS, Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*)
---

# /test_suite — deprecated alias

This command is a thin compatibility alias kept through the 2.x line. The
canonical workflow is the `test-suite` skill; invoke it as
`/rpa:test-suite` going forward.

Forward `$ARGUMENTS` unchanged to the test-suite kernel. Resolve the kernel
from the first readable location:

1. `${CLAUDE_PLUGIN_ROOT}/skills/test-suite/SKILL.md`
2. `~/.claude/skills/test-suite/SKILL.md`
3. `plugins/rpa/skills/test-suite/SKILL.md` in the project checkout
4. `skills/test-suite/SKILL.md` when the working directory is the plugin
   root

Follow the kernel exactly — the mode grammar, authority matrix, artifact
contracts, and escalation rules live there and are not restated here.

Intentional differences from the pre-2.3 command, applied by the kernel:

- `init --force` is retired; overwrites go through a reviewed init plan
  and `init apply`.
- This alias preapproves only read/discovery tools and read-only git;
  artifact writes, applies, and test execution use the ordinary permission
  flow.

If no location resolves, report that the test-suite skill package is not
installed instead of improvising the workflow.
