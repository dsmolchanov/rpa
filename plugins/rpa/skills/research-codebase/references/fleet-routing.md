# Research fleet — routing (Claude adapter calibration)

This file is the delegation adapter for the research workflow: it tunes
*how strongly* to delegate on Claude, while the kernel (`SKILL.md`,
Delegation) states *when* delegation is warranted at all.

## The fleet

Six agents, each with a platform-neutral contract under
`agent-contracts/` and a thin shared Claude adapter in `agents/`:

| Agent | Use for | Not for |
|---|---|---|
| `codebase-locator` | finding WHERE code lives — paths grouped by role | reading or explaining contents |
| `codebase-analyzer` | how a SPECIFIC, already-located component works | broad discovery; use the locator first |
| `codebase-pattern-finder` | concrete existing examples of a named pattern | judging which pattern is better |
| `thoughts-locator` | discovering which `thoughts/` documents exist on a topic | deep-reading them |
| `thoughts-analyzer` | extracting decisions/constraints from a SPECIFIC document | surveys; use the thoughts locator first |
| `web-search-researcher` | external library/API facts the repo cannot answer, or when the user asks for web research | anything answerable from the checkout |

## Calibration (Claude)

Current Opus-class models delegate readily — the cap here is a
*restraint*, not a prod:

- Delegate a track only when it is independent of your other tracks and
  big enough that doing it inline would crowd out synthesis. A narrow
  "where is Y" question is usually a couple of Grep/Glob calls — answer
  it directly.
- **Cap: at most 6 fleet-agent spawns per research run, at most 4 running
  concurrently.** The cap is a budget,
  not a target — typical runs use fewer; exceeding it is a defect, not a
  judgment call. Follow-up rounds on the same document count against the
  same run's cap.
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
