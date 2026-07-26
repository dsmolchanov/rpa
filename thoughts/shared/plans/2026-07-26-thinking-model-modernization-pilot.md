---
date: 2026-07-26
type: pilot-plan
scope: /research_codebase + its research agents
status: approved by owner 2026-07-26 (repos, push flow, blind scorer) — ground-truth notes pending
depends_on: docs/conventions.md (v0.1)
---

# Pilot: modernize /research_codebase for reasoning-era models

Validate `docs/conventions.md` v0.1 on one command family before any
repo-wide rewrite. No other files are touched until this pilot's results are
reviewed.

## Why /research_codebase

- Heaviest concentration of legacy patterns: `ultrathink` incantation,
  scripted greeting, 4 restatements of the documentarian rule, mandatory
  fan-out of 5+ subagents with a hard barrier, dead references
  (`linear-ticket-reader`, `linear-searcher`).
- Output is a self-contained artifact (research doc), so A/B comparison is
  clean: same question in, two documents out.
- Its agent fleet (`codebase-locator`, `codebase-analyzer`,
  `codebase-pattern-finder`, `thoughts-locator`, `thoughts-analyzer`,
  `web-search-researcher`) is shared with `/create_plan` — a validated
  rewrite propagates naturally to the planning family next.

## Scope

**In:** `commands/research_codebase.md` + the six agents above, rewritten to
the v0.1 anatomy (intent / scope & authority / artifact contract / process
guidance / acceptance criteria / escalation conditions).

**Out (this pilot):** all other commands; hooks; AI-DLC; any change to the
artifact contract itself — the new command must emit documents that
`/create_plan` and `/enhance_research` can still consume unchanged.

## Baseline

- Freeze current `research_codebase.md` + agent files at the current commit
  (tag or record SHA in the results doc).
- Baseline runs use the frozen files verbatim, same harness, same model,
  same effort as the candidate runs.

## Eval set

5–10 real research questions across three repos of varying size and stack,
confirmed by the owner 2026-07-26:

- **rpa** (this repo) — small, pure-markdown/plugin case
- **Plaintalk** — production application repo
- **neo.menu** — production application repo (second stack)

Question archetypes:

| # | Question archetype | Why it's in the set |
|---|---|---|
| 1 | "How does subsystem X work end-to-end?" on a mid-size repo | Core use case; tests synthesis + evidence quality |
| 2 | Same archetype on a large/monorepo codebase | Stresses delegation policy (old: forced fan-out; new: criteria-based) |
| 3 | Narrow "where is Y configured / defined?" | Old version over-orchestrates this; measures waste |
| 4 | Question whose answer spans code + prior docs in `thoughts/` | Exercises thoughts-locator/analyzer path |
| 5 | Question requiring external library/API context | Exercises web-search path and its call-quota removal |
| 6 | Question with a known-wrong premise | Measures escalation behavior (should surface the mismatch, not comply) |
| 7–10 | Repeats of 1–3 on the second stack | Controls for stack monoculture |

Each task ships with a short ground-truth note (key files, key facts a correct
answer must contain) written before running either version.

## Metrics (recorded per run, both versions)

1. **Quality** — rubric score against the ground-truth note: coverage of key
   facts, correctness of claims, synthesis quality (blind-scored on the
   documents, scorer does not know which version produced which).
2. **Evidence accuracy** — spot-check N file:line references per doc; % that
   resolve to what's claimed.
3. **Cost** — total tokens (main context + subagents).
4. **Latency** — wall-clock to finished document.
5. **Tool calls** — count, main context.
6. **Subagents** — count spawned.
7. **User interventions** — number of stops/questions before the document
   exists (old version has a mandatory greeting stop; new version should stop
   only per §5 of conventions).

Pass bar: quality and evidence accuracy **not worse** than baseline, with
material improvement in at least two of cost / latency / interventions.
If quality regresses, the convention (not just the rewrite) is revised before
retry.

## Platforms

- Primary A/B: Claude Code on the current Opus-class model, thinking on,
  default effort; one repeat of tasks 1–3 at low effort to check the effort
  lever claim.
- Codex: the Codex adapter (AGENTS.md-level conventions) does not yet carry
  `/research_codebase`; Codex participation in this pilot is limited to
  reviewing the rewritten files via the existing `codex-review-window` PR
  flow. A full Codex-side A/B becomes possible once the kernel/adapter split
  produces a Codex-consumable research skill (phase 2, out of scope here).

## Sequence

1. Owner confirms eval repos + questions; ground-truth notes written.
2. Baseline runs recorded.
3. Rewrite `research_codebase.md` + 6 agents per conventions v0.1 (separate
   branch/PR; artifact contract unchanged).
4. Candidate runs recorded; blind scoring.
5. Results doc in `thoughts/shared/research/` with the numbers and a
   go/no-go recommendation for extending the pattern to the planning family
   (`/create_plan`, `/iterate_plan`+`/enhance_plan` merge), then TDD and
   refactoring clusters.

## Owner decisions (2026-07-26)

1. **Eval repos**: rpa, Plaintalk, neo.menu.
2. **Push flow**: work is pushed to branches in `dsmolchanov/rpa`; the rewrite
   PR goes through the normal Codex review gate (`codex-review-window`) like
   any other PR.
3. **Blind scorer**: a separate model session, given only the two anonymized
   documents and the ground-truth note — no access to this session's context
   or knowledge of which version produced which document.
