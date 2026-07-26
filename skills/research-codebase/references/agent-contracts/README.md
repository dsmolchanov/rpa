# Agent contracts (pending extraction)

Platform-neutral contracts of the research agent fleet, per
`docs/conventions.md` §3: one file per agent covering trigger and
when-not-to-use, bounded input, read/write authority, output contract,
evidence requirements, budget, and failure/escalation behavior.

Planned files (extracted during the pilot's rewrite phase):

- `locator.md` — from `agents/codebase-locator.md`
- `analyzer.md` — from `agents/codebase-analyzer.md`
- `pattern-finder.md` — from `agents/codebase-pattern-finder.md`
- `thoughts-locator.md` — from `agents/thoughts-locator.md`
- `thoughts-analyzer.md` — from `agents/thoughts-analyzer.md`
- `web-researcher.md` — from `agents/web-search-researcher.md`

Until extraction, the authoritative definitions remain the adapter files in
`agents/` (baseline) and `agents/research-v2-*.md` (pilot copies). After
extraction, `research-v2-*` files become thin adapters: tools, model/effort,
permissions, and a pointer to their contract here.
