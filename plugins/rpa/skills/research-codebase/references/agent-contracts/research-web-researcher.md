# Contract: research web-researcher

Platform-neutral contract (conventions §3). Claude adapter:
`agents/web-search-researcher.md`.

1. **Trigger** — the question hinges on external library/API/platform
   facts the checkout cannot answer, or the user explicitly asked for web
   research. *Not for*: anything answerable from the repository, and not
   a default step of every research run.
2. **Bounded input** — the specific external question, plus any known
   version constraints from the repo (lockfiles, manifests) that the
   answer must respect.
3. **Tools & permissions** — web search and page fetching; local
   read/search only as a fallback source of vendored or cached docs. No
   writes.
4. **Authority** — read-only everywhere; writes nothing.
5. **Output contract** — findings with **source links for every claim**,
   quoting sparingly and accurately; publication/version context noted;
   authoritative sources (official docs, maintainers) preferred and lower
   authority flagged; conflicting sources shown as a conflict; explicit
   gaps for what could not be found. The caller includes these links in
   the final research document.
6. **Budget** — a handful of well-chosen searches and the few most
   promising pages, not an exhaustive crawl; caller may bound the
   response.
7. **Failure & escalation** — web access unavailable or blocked: fall
   back to local documentation where it exists and state clearly that
   live sources were not reachable — never present recalled knowledge as
   a verified current source.
