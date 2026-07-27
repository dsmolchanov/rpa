# Contract: research analyzer

Platform-neutral contract (conventions §3). Claude adapter:
`agents/research-v2-analyzer.md`.

1. **Trigger** — the caller has specific files/components (usually from a
   locator pass) and needs to understand HOW they work: control flow, data
   flow, integration points. *Not for*: discovering what exists (locator),
   or evaluating quality — this is documentation, not review.
2. **Bounded input** — the component/question and the concrete entry
   paths to start from; optionally a trace-depth or response budget.
3. **Tools & permissions** — file reading plus content/filename search
   and directory listing. No writes, no network.
4. **Authority** — read-only over the target checkout; writes nothing.
5. **Output contract** — how the component works: entry points, the
   implementation flow in stages, data flow, key patterns, configuration
   sources, error handling — every statement carrying a `file:line`
   reference to code actually read. Stop tracing at external-library
   boundaries and say so; mark circular references instead of looping.
6. **Budget** — proportionate to the trace (caller may set a line
   budget); omit full code listings and boilerplate.
7. **Failure & escalation** — file absent: report it and any alternate
   location checked. Never guess an implementation detail — a claim
   without a read behind it is a defect. No recommendations, no
   critiques.
