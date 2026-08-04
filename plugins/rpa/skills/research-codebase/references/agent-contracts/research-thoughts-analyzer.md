# Contract: research thoughts-analyzer

Platform-neutral contract (conventions §3). Claude adapter:
`agents/thoughts-analyzer.md`.

1. **Trigger** — the caller has identified a specific `thoughts/`
   document (usually via the thoughts-locator) and needs its load-bearing
   content: decisions, constraints, specifications, lessons. *Not for*:
   discovering documents, or treating old notes as current truth.
2. **Bounded input** — the document path(s) — at most a handful — and
   the question the extraction should serve.
3. **Tools & permissions** — file reading plus search/listing for
   cross-checking sibling documents. No writes, no network.
4. **Authority** — read-only; writes nothing.
5. **Output contract** — the decisions made, trade-offs recorded,
   constraints stated, and concrete specifications, each attributed to
   its document (path with `searchable/` stripped). Filter hard: skip
   exploration that reached no conclusion, rejected options, and
   superseded workarounds. Date and staleness are part of the report:
   note document age, flag likely-outdated content, and prefer newer or
   more specific documents when they conflict — surfacing the conflict
   rather than resolving it silently.
6. **Budget** — the distilled substance, not a summary of everything;
   caller may bound it.
7. **Failure & escalation** — document missing or unreadable: report it.
   Content contradicts the live code: report the discrepancy as history
   vs present — the code is the source of truth for the present.
