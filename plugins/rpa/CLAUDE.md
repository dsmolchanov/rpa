# AI-DLC Compatibility Bootstrap

This repository includes an AWS AI-DLC-compatible compatibility layer for the `/aidlc_*` command family.

## Canonical Sources

- Canonical workflow artifacts live in `aidlc-docs/`
- Persistent session state lives in `aidlc-docs/aidlc-state.md`
- Audit history lives in `aidlc-docs/audit.md`
- Stage execution decisions live in `aidlc-docs/inception/plans/execution-plan.md`

## Rule Loading Order

When working with `/aidlc_*` commands:

1. Load the pinned compatibility rule details in `.aidlc-rule-details/`
2. Apply any repo-local overrides in `.aidlc-rule-details/`
3. Load enabled extension files from `extensions/`
4. Read `thoughts/shared/steering-rules/default.yaml` for plugin-local conventions only

## Interaction Model

- Required clarifications must be written to markdown files under `aidlc-docs/inception/questions/`
- Question files must use `[Answer]:` tags for user responses
- Chat-only confirmations are not the primary approval mechanism for AI-DLC flows

## Experimental Extensions

- `/aidlc_operations` is a plugin extension beyond the current upstream core workflow
- `/aidlc_feedback` is a plugin extension beyond the current upstream core workflow
