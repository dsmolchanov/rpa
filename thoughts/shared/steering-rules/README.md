# Plugin Overlay

This directory contains plugin-local AI-DLC overlay settings.

## Canonical vs Overlay

- `aidlc-docs/` is the canonical source of workflow truth
- `thoughts/shared/steering-rules/default.yaml` is a plugin overlay for local conventions and default commands

## What Belongs Here

- change type heuristics
- default command mappings
- team naming conventions
- experimental extension toggles

## What Does Not Belong Here

- stage `EXECUTE` / `SKIP` decisions
- canonical workflow state
- question answers

Those belong in:
- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/inception/plans/execution-plan.md`
- `aidlc-docs/inception/questions/`

## Depth Values

The overlay uses:
- `minimal`
- `standard`
- `comprehensive`
