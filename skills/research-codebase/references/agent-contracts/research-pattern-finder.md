# Contract: research pattern-finder

Platform-neutral contract (conventions §3). Claude adapter:
`agents/research-v2-pattern-finder.md`.

1. **Trigger** — the caller needs concrete existing examples of a named
   pattern/approach in this codebase (how do we do pagination, how are
   handlers registered), as evidence of current convention. *Not for*:
   locating a feature's files (locator), full component analysis
   (analyzer), or judging which of several patterns is better.
2. **Bounded input** — the pattern being sought and, optionally, where to
   look and how many examples are wanted.
3. **Tools & permissions** — content/filename search, directory listing,
   file reading. No writes, no network.
4. **Authority** — read-only over the target checkout; writes nothing.
5. **Output contract** — a small set of real examples, each with
   `file:line` location and a short excerpt (roughly 10–30 lines) showing
   the pattern in use, plus where each variant is conventionally applied.
   Excerpts are quotations of existing code — never invented or
   "improved" code.
6. **Budget** — a few best examples over an exhaustive census; caller may
   set a line budget.
7. **Failure & escalation** — pattern not present: say so explicitly
   (that absence is itself a finding) rather than inventing a plausible
   example. Multiple incompatible variants: show them and note where each
   is used, without ranking their quality.
