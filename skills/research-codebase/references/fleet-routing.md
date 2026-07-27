# Research fleet — routing (Claude adapter calibration)

This file is the delegation adapter for the research workflow: it tunes
*how strongly* to delegate on Claude, while the kernel (`SKILL.md`,
Delegation) states *when* delegation is warranted at all. The
fleet-ablation build of the pilot removes this file together with the
`research-v2-*` agents; nothing else in the kernel may depend on it.

## The fleet

Six agents, each with a platform-neutral contract under
`agent-contracts/` and a thin Claude adapter in `agents/research-v2-*.md`:

| Agent | Use for | Not for |
|---|---|---|
| `research-v2-locator` | finding WHERE code lives — paths grouped by role | reading or explaining contents |
| `research-v2-analyzer` | how a SPECIFIC, already-located component works | broad discovery; use the locator first |
| `research-v2-pattern-finder` | concrete existing examples of a named pattern | judging which pattern is better |
| `research-v2-thoughts-locator` | discovering which `thoughts/` documents exist on a topic | deep-reading them |
| `research-v2-thoughts-analyzer` | extracting decisions/constraints from a SPECIFIC document | surveys; use the thoughts locator first |
| `research-v2-web-researcher` | external library/API facts the repo cannot answer, or when the user asks for web research | anything answerable from the checkout |

## Calibration (Claude)

Current Opus-class models delegate readily — the cap here is a
*restraint*, not a prod:

- Delegate a track only when it is independent of your other tracks and
  big enough that doing it inline would crowd out synthesis. A narrow
  "where is Y" question is usually a couple of Grep/Glob calls — answer
  it directly.
- Typical shape for a subsystem question: locators (code and, if history
  matters, thoughts) in parallel first; then analyzers on the few most
  promising targets; web research only on external-dependency questions.
- Run independent agents concurrently; a barrier — waiting on all results
  — is justified only where synthesis truly needs them together.
- Pass each agent a bounded input per its contract (question, paths,
  response budget). Agents know their own method; do not restate it in
  the prompt.
- Keep the main context for synthesis: read the orientation layers and
  user-mentioned files yourself, take agent reports as evidence, and
  write the document yourself.
