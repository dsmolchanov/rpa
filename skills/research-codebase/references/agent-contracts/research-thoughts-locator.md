# Contract: research thoughts-locator

Platform-neutral contract (conventions §3). Claude adapter:
`agents/research-v2-thoughts-locator.md`.

1. **Trigger** — the caller needs to know which documents in the
   `thoughts/` store (research, plans, tickets, PRs, handoffs, notes)
   touch a topic. *Not for*: extracting their content (thoughts-analyzer)
   or searching the code itself (locator).
2. **Bounded input** — the topic and its likely synonyms/identifiers
   (ticket numbers, component names).
3. **Tools & permissions** — content/filename search and directory
   listing under `thoughts/`, plus file reading strictly limited to
   loading this contract file. Document contents are never read —
   locating is not analyzing. No writes, no network.
4. **Authority** — read-only; writes nothing.
5. **Output contract** — matching documents grouped by type (research /
   plans / tickets / PRs / handoffs / notes), newest first, each with its
   title or one-line gist and its date where the filename carries one.
   **Path normalization is mandatory:** results found under
   `thoughts/searchable/` are reported with only the `searchable/`
   segment removed, all other structure preserved exactly (user
   directories stay user directories; `shared/` stays `shared/`).
6. **Budget** — a scannable listing; caller may bound it.
7. **Failure & escalation** — no matches: say so and name the variants
   tried. A `thoughts/` store that does not exist in this checkout is
   reported as absent, not simulated.
