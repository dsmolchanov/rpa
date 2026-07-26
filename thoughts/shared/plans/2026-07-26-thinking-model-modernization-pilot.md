---
date: 2026-07-26
type: pilot-plan
scope: /research_codebase workflow family (Claude-side)
status: protocol draft — owner inputs confirmed 2026-07-26; revised same day per protocol review
depends_on: docs/conventions.md (v0.2)
baseline_plugin_sha: a7de5f6000225b57eeee1a5c6c0131fb02656d4d
---

# Pilot: modernize /research_codebase for reasoning-era models

Validate `docs/conventions.md` v0.2 on one workflow family with a
reproducible A/B experiment. No other files are rewritten until this pilot's
results are reviewed.

## What this pilot can and cannot conclude

**Can conclude:** whether the Claude-side contract-driven rewrite of the
research workflow beats the legacy version, on a pinned model, Claude Code
version, and effort setting, on the eval set below.

**Cannot conclude:** repo-wide adoption. That additionally requires
representative gates for the planning family, the TDD/refactoring family,
and a Codex skill runtime eval. Codex participation here is limited to PR
review via `codex-review-window`, which is **advisory** (its 480-second
timeout path lets a PR pass without a review) — it is not a runtime eval.

## Why /research_codebase

- Heaviest concentration of legacy patterns (incantations, scripted
  greeting, repeated rules, mandatory fan-out with hard barrier, dead
  references to nonexistent agents).
- Output is a self-contained artifact, so A/B comparison is clean.
- Its agent fleet is shared with the planning family, so a validated rewrite
  propagates naturally next.

## Scope and isolation

**Candidate implementation:**

- Kernel skill package `skills/research-codebase/` per conventions §1:
  `SKILL.md`, `references/artifact-contract.md`, `evals/`, `scripts/`.
- `commands/research_codebase.md` becomes a thin compatibility wrapper.
- **Temporary agent copies** `research-v2-locator`, `research-v2-analyzer`,
  `research-v2-pattern-finder`, `research-v2-thoughts-locator`,
  `research-v2-thoughts-analyzer`, `research-v2-web-researcher` — the
  existing shared agents are NOT modified. They are also callers'
  dependencies in `create_plan`, `iterate_plan`, `enhance_plan`,
  `enhance_research`, `tdd`, `create_test_plan`, `aidlc_inception`,
  `tech_debt_sweep`; changing them mid-pilot would silently alter
  out-of-scope frameworks.
- Before any post-pilot merge of v2 agents into the shared fleet: a
  **shared-agent impact matrix** (which caller uses which behavior) and
  smoke tests of every caller are mandatory.

**Artifact contract is unchanged**: candidate documents must remain
consumable by legacy `/create_plan` and `/enhance_research` (see
Compatibility below).

## Baseline

- The **entire plugin** frozen at `a7de5f6000225b57eeee1a5c6c0131fb02656d4d`
  (last commit before convention/pilot docs), not just the seven files.
- Baseline and candidate run from **separate plugin installations**, in
  fresh sessions, in disposable worktrees, against the **same target
  repo@SHA**.

## Runtime configuration (pinned, not merely recorded)

At candidate freeze, a single **shared runtime configuration** is
pre-registered and then held constant for **all** runs of all arms:

- exact model ID
- Claude Code version
- effort setting
- active hooks, MCP servers, permission mode
- resource ceilings (timeouts, token budget if set)

The **only permitted difference between arms is the plugin content** (frozen
baseline SHA vs candidate branch SHA vs minimal-skill variant). Every run
additionally captures the target repo + SHA and its own plugin SHA. If any
pinned value differs within a paired task's runs, the pair is invalid and is
rerun — deltas must reflect the workflow rewrite, not runtime drift.

## Eval set

Repos (owner-confirmed): **rpa** (small, markdown/plugin),
**livekit-voice-agent** (active production repo), **NeoMenu**.

**Development set (visible):** 4–5 tasks used while building the candidate.
**Sealed holdout:** 4–5 tasks authored in a **separate session** (not by the
candidate's author-context), with ground-truth notes, sealed until the
candidate implementation is frozen. This prevents fitting the rewrite to the
test. For the external-context archetype, the sealed package also contains
**frozen snapshots of the authoritative external sources** (the relevant
docs pages, captured at authoring time) so external claims can be verified
against a fixed reference.

Question archetypes across both sets:

| Archetype | Why |
|---|---|
| Subsystem end-to-end explanation (mid-size repo) | core use case |
| Same on the largest repo | stresses delegation criteria vs forced fan-out |
| Narrow "where is Y defined/configured" | measures over-orchestration waste |
| Answer spans code + prior `thoughts/` docs | exercises thoughts path |
| Requires external library/API context | exercises web-research path |
| Question with a known-wrong premise | measures escalation (surface, don't comply) |

**Run protocol:** randomized, interleaved order per task; **exactly 3 runs
per arm per holdout task**, pre-registered — no runs are added or discarded
after outcomes are observed. A timed-out/aborted run counts as a failed run
and is **not** replaced.

## Third arm (2–3 tasks)

On 2–3 holdout tasks, run a third variant: a **minimal skill** carrying only
the artifact contract and acceptance criteria — no specialized agent fleet.
This answers the strategic question the A/B alone cannot: is the value in
the contract, or do six standing research agents still earn their keep with
modern models?

## Metrics

1. **Quality** — blind rubric score (coverage, relevance, synthesis) against
   the ground-truth note, using the **frozen rubric** at
   `skills/research-codebase/evals/rubric.md` — dimensions, weights, score
   anchors, and scoring instructions — committed before the holdout is
   unsealed (prerequisite 5).
2. **Evidence accuracy** — a **separate evidence verifier** (read-only
   access to the frozen repo@SHA, no knowledge of arms) checks whether cited
   file:line references actually support the claims; % that do. For the
   external-context task the verifier also gets the frozen external-source
   snapshots from the holdout package and checks external claims and
   citations against them.
3. **Critical factual errors** — count (claims contradicted by the repo or
   by the frozen external sources).
4. **Cost** — tokens across the **entire agent tree**, reported as
   main-context and subagent subtotals.
5. **Tool calls** — same tree-wide accounting, main/subagent split.
6. **Latency** — wall-clock to finished document (median across runs).
7. **Subagents spawned.**
8. **User interventions** — stops/questions before the document exists;
   ritual stops (greeting-and-wait) counted separately.

## Pass bar (pre-registered — fixed before any baseline run)

Deltas below are computed by the pre-registered aggregation and pairing rule
in Scoring. Candidate passes iff, on the holdout set:

- quality delta ≥ **−0.25 / 10** vs baseline;
- evidence accuracy delta ≥ **−2 п.п.**;
- **zero** critical factual errors introduced;
- **zero** ritual stops;
- **≥20%** token savings **or** **≥15%** wall-time reduction, both as the
  aggregated holdout-level figures defined in Scoring;
- no timeout/abort failures in the candidate arm.

If quality regresses beyond the bar, the convention itself (not just the
rewrite) is revised before retry.

## Scoring

- **Blind scorer:** a separate model session with no access to this
  session's context; does not know which arm produced which document.
- **Every replicate is scored.** Every run of every arm produces a document,
  and every document is blind-scored independently (anonymized, randomized
  presentation order, one document per scoring call to avoid
  cross-anchoring). No post-hoc selection of a "best" run per arm.
- **Pre-registered aggregation and pairing:** per holdout task and arm, the
  arm's quality and evidence-accuracy values are the **median across its
  replicates**; the per-task delta is candidate median minus baseline
  median; the holdout-level delta compared against the pass bar is the
  **mean of per-task deltas**. A timed-out/aborted run produces no document
  and is excluded from the median, but any such run already fails the
  candidate arm via the pass bar. This rule is fixed here, before any
  baseline run.
- **Cost and latency aggregation (same pairing):** per task and arm, the
  **median total tokens** (tree-wide) and **median wall-clock** across
  replicates; the per-task delta is the percentage change of the candidate
  median vs the baseline median; the holdout-level figure compared against
  the pass bar is the **mean of per-task percentage deltas**. No pooling of
  runs across tasks.
- **Evidence verifier:** separate role from the scorer, read-only on the
  frozen repo (see Metrics #2); verifies references in **every** scored
  document, aggregated by the same rule.

## Artifact compatibility gate

Before candidate runs count:

- frozen frontmatter/headings fixture checked into `evals/`;
- schema validation of candidate documents against the fixture;
- legacy `/create_plan` and `/enhance_research` executed against a candidate
  document — must consume it without errors;
- follow-up semantics (`last_updated`, enhancement notes) and permalink
  conventions preserved.

## Privacy

livekit-voice-agent and NeoMenu are private. Raw outputs, ground-truth notes, real
paths, and code snippets from private repos are **not** committed to this
public repo. The public results doc carries only aggregated metrics and
sanitized examples; raw run artifacts stay in a private location.

## Prerequisites before baseline runs

1. CI validation job for this repo's markdown: frontmatter schema, internal
   links, plugin manifest (per conventions §4 — a silently no-op gate is a
   defect; today `ci.yml` barely exercises these files).
2. Pass bar registered (this document, committed before runs).
3. Holdout tasks authored in a separate session and sealed (including
   frozen external-source snapshots for the external-context task).
4. `skills/research-codebase/` skeleton + `research-v2-*` agent copies.
5. Complete quality rubric committed at
   `skills/research-codebase/evals/rubric.md` (dimensions, weights, score
   anchors, scoring instructions) — frozen before the holdout is unsealed.

## Sequence

1. Prerequisites 1–5.
2. Ground-truth notes for the dev set.
3. Dev-set runs (any arm, any order) — used to build and tune the candidate;
   **never counted toward the pass bar**.
4. **Candidate frozen** (commit SHA recorded) and shared runtime
   configuration pre-registered.
5. **Holdout unsealed only now.** All holdout runs — baseline, candidate,
   and third arm — executed under the pinned configuration in randomized,
   interleaved order (exactly 3 per arm per task).
6. Blind scoring + evidence verification.
7. Results doc in `thoughts/shared/research/` (aggregated, sanitized) with a
   go/no-go recommendation — scoped to the Claude-side research pattern.
   Extension to planning / TDD / refactoring families and the Codex skill
   adapter each get their own representative gate.

## Owner decisions (2026-07-26)

1. **Eval repos**: rpa, livekit-voice-agent (confirmed 2026-07-26, replacing
   the earlier Plaintalk option), NeoMenu.
2. **Push flow**: branches in `dsmolchanov/rpa`; the rewrite PR goes through
   the normal Codex review gate like any other PR (advisory, see above).
3. **Blind scorer**: separate model session (see Scoring).
