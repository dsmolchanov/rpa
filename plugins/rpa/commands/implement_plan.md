---
description: "Deprecated 2.x alias for the implement-plan skill: execute a plan from thoughts/shared/plans with per-phase verification (canonical: /rpa:implement-plan)"
argument-hint: "[plan-file] [phases]"
---

# /implement_plan — deprecated alias

This command is a thin compatibility alias kept through the 2.x line. The
canonical workflow is the `implement-plan` skill; invoke it as
`/rpa:implement-plan` going forward.

Forward `$ARGUMENTS` unchanged to the implement-plan kernel. Resolve the
kernel from the first readable location:

1. `${CLAUDE_PLUGIN_ROOT}/skills/implement-plan/SKILL.md`
2. `~/.claude/skills/implement-plan/SKILL.md`
3. `plugins/rpa/skills/implement-plan/SKILL.md` in the project checkout
4. `skills/implement-plan/SKILL.md` when the working directory is the plugin
   root

Follow the kernel exactly — authority, the implementation record, mismatch
handling, and escalation rules live there and are not restated here.

Intentional differences from the pre-2.4 command, applied by the kernel:

- No pause after every phase. The run stops for a manual check only when the
  plan says a later phase depends on its outcome; all other manual items are
  carried to the final report.
- The plan's body is read-only during implementation. Progress, deviations,
  and assumptions go into the plan's `## Implementation Record`.
- On resume, earlier checkmarks are re-verified before new work builds on
  them.

If no location resolves, report that the implement-plan skill package is not
installed instead of improvising the workflow.
