# Agent contracts

Platform-neutral contracts of the research agent fleet, per
`docs/conventions.md` §3: one file per agent covering trigger and
when-not-to-use, bounded input, tools, read/write authority, output
contract, budget, and failure/escalation behavior.

| Contract | Claude adapter |
|---|---|
| `research-locator.md` | `agents/research-v2-locator.md` |
| `research-analyzer.md` | `agents/research-v2-analyzer.md` |
| `research-pattern-finder.md` | `agents/research-v2-pattern-finder.md` |
| `research-thoughts-locator.md` | `agents/research-v2-thoughts-locator.md` |
| `research-thoughts-analyzer.md` | `agents/research-v2-thoughts-analyzer.md` |
| `research-web-researcher.md` | `agents/research-v2-web-researcher.md` |

The adapters are thin (tools, model policy, contract pointer). The two
locator adapters carry `Read` solely to load their own contract file —
an authority bound stated in the contracts themselves (repository and
document contents are never read; locating is not analyzing). The legacy
shared fleet (`agents/codebase-*.md`, `agents/thoughts-*.md`,
`agents/web-search-researcher.md`) is untouched during the pilot — it
serves the frozen baseline and the other command families; any post-pilot
merge of the v2 pattern into the shared fleet requires the shared-agent
impact matrix and caller smoke tests named in the pilot plan.

Routing between agents (which to use when, Claude delegation calibration)
lives in `../fleet-routing.md`; the fleet-ablation build of the pilot
removes that file and the `research-v2-*` adapters, leaving these
contracts as inert documentation.
