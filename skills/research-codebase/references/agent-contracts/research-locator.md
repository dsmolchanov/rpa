# Contract: research locator

Platform-neutral contract (conventions §3). Claude adapter:
`agents/research-v2-locator.md`.

1. **Trigger** — the caller needs to know WHERE code relevant to a topic
   lives, across an area too large to enumerate inline. *Not for*: reading
   or explaining file contents (analyzer), or questions the caller can
   settle with one or two direct searches.
2. **Bounded input** — the topic/feature being located; optionally the
   subtree to search and known naming hints. The agent must not depend on
   unstated conversation context.
3. **Tools & permissions** — content search, filename search, directory
   listing, plus file reading strictly limited to loading this contract
   file. Repository file contents are never read — locating is not
   analyzing. No writes, no network.
4. **Authority** — read-only over the target checkout; writes nothing.
5. **Output contract** — file paths from the repository root, grouped by
   role (implementation, tests, config, types, docs), plus directories
   that cluster related files, entry points with `file:line` where
   identifiable, and counts per group. No contents, no snippets, no
   analysis of behavior.
6. **Budget** — response compact enough to scan (the caller may set an
   explicit line budget; default to roughly a screenful).
7. **Failure & escalation** — nothing found: say so and list the naming
   variants tried. Too much found: group by directory with counts instead
   of flooding paths. Never fabricate paths; never substitute guesses for
   searches.
