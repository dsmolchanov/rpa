# Agent contracts

Platform-neutral contracts of the research agent fleet, per
`docs/conventions.md` §3: one file per agent covering trigger and
when-not-to-use, bounded input, tools, read/write authority, output
contract, budget, and failure/escalation behavior.

| Contract | Claude adapter |
|---|---|
| `research-locator.md` | `agents/codebase-locator.md` |
| `research-analyzer.md` | `agents/codebase-analyzer.md` |
| `research-pattern-finder.md` | `agents/codebase-pattern-finder.md` |
| `research-thoughts-locator.md` | `agents/thoughts-locator.md` |
| `research-thoughts-analyzer.md` | `agents/thoughts-analyzer.md` |
| `research-web-researcher.md` | `agents/web-search-researcher.md` |

The adapters are thin (tools, model policy, contract pointer). The two
locator adapters carry `Read` solely to load their own contract file —
an authority bound stated in the contracts themselves (repository and
document contents are never read; locating is not analyzing). These shared
adapters serve research, planning, testing, and AI-DLC callers from one
contract source. Historical `research-v2-*` adapters remain solely for
reproducing the frozen pilot installation.

Routing between agents (which to use when, Claude delegation calibration)
lives in `../fleet-routing.md`.
