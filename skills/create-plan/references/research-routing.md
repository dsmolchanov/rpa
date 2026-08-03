# Planning research routing

Use the shared research fleet only for genuinely independent, sizeable tracks.
Its owning contracts live under
`skills/research-codebase/references/agent-contracts/`; the corresponding
`agents/*.md` files provide platform wiring.

## Routes

| Need | Adapter | Expected result |
|---|---|---|
| Locate affected files without explaining them | `codebase-locator` | paths grouped by role |
| Trace how current behavior works | `codebase-analyzer` | data/control flow with `file:line` evidence |
| Find an established implementation to mirror | `codebase-pattern-finder` | concrete examples and applicability limits |
| Locate prior plans, research, or decisions | `thoughts-locator` | relevant artifact paths and why they matter |
| Extract decisions from a known thoughts document | `thoughts-analyzer` | concise findings with source locations |
| Verify current third-party APIs or behavior | `web-search-researcher` | authoritative links and version/date context |

## Boundaries

- The main planner reads user-named inputs and repository orientation files
  before delegation.
- Give every delegated task a bounded question, paths or directory scope, and
  required evidence shape. Do not rely on unstated conversation context.
- Parallelize only tracks that do not depend on each other's findings. Wait at
  a synthesis boundary only when later planning needs all results.
- Treat agent output as leads. Read load-bearing source files in the main
  context and reconcile conflicting findings before they enter the plan.
- If the fleet is unavailable, research in the main context; do not substitute
  unrelated agents to preserve a delegation pattern.
