---
date: 2026-07-26
type: pilot-plan
scope: /research_codebase workflow family (Claude-side)
status: protocol draft — owner inputs confirmed 2026-07-26; revised per protocol review; v0.2.1 amendments same day (atomic seal, fleet ablation, eval-runner, exact task counts)
depends_on: docs/conventions.md (v0.2.1)
baseline_plugin_sha: a7de5f6000225b57eeee1a5c6c0131fb02656d4d
---

# Pilot: modernize /research_codebase for reasoning-era models

Validate `docs/conventions.md` v0.2.1 on one workflow family with a
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
  existing shared agents are NOT modified. The initial copies are
  byte-identical to the originals **except the frontmatter `name:` field**
  (a documented single-line deviation required for harness registration).
  During the rewrite, the platform-neutral contract of each agent is
  extracted to `skills/research-codebase/references/agent-contracts/`
  (conventions §3) and the `research-v2-*` files become thin adapters
  (tools, model/effort, permissions, contract pointer). They are also callers'
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

**Packaging:** the rewrite PR updates README Quick Install to copy the
skill directory as well (`mkdir -p ~/.claude/skills && cp -R skills/*
~/.claude/skills/`), so non-plugin installs receive the workflow kernel;
plugin installs pick it up automatically. The rewrite PR also bumps the
version in `.claude-plugin/plugin.json` at candidate release — with an
explicitly set version, installations do not pick up changes without a
bump. This **explicitly supersedes**
roadmap item 18 ("defer skills migration",
`thoughts/shared/plans/2026-06-10-plugin-improvement-roadmap.md`) for the
research workflow family only — a supersession note is recorded in that
roadmap. Other command families stay on the deferred decision until their
own gates.

**Owner-approved repository integration fixes (2026-07-26, second review):**
landed with the prerequisite PR and recorded here as the authoritative
authorization — `CLAUDE.md` imports `@AGENTS.md` (Claude Code does not read
AGENTS.md natively; the import is the official interop path). This is a
repo-wide instruction-loading change, explicitly requested by the owner
alongside the CI gate, and is not part of the pilot's evaluated surface.
Because the frozen `a7de5f6` tree predates the import, arm parity is
enforced by a **common overlay**: building the baseline installation
artifact applies the identical one-line `@AGENTS.md` import to its
`CLAUDE.md` as a recorded build step, so both arms' installation artifacts
— whose hashes the eval-runner verifies before every run (prerequisite 5)
— load repository instructions identically, and instruction loading cannot
be an arm difference.

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
baseline SHA vs candidate branch SHA vs fleet-ablation variant). Every run
additionally captures the target repo + SHA and its own plugin SHA. If any
pinned value differs within a paired task's runs, the pair is invalid and is
rerun — deltas must reflect the workflow rewrite, not runtime drift.

**Effective-model parity:** the frozen baseline command carries
`model: opus`; to prevent the arms resolving to different models, the
candidate wrapper (and the fleet-ablation arm) carry the **same explicit
model pin** as the baseline for the duration of the pilot — a pilot-only
parity control that supersedes conventions §5 until adoption. Every run's
harness-reported effective model is validated against the registered model;
a mismatch invalidates the run.

## Eval set

Repos (owner-confirmed): **rpa** (small, markdown/plugin),
**livekit-voice-agent** (active production repo), **NeoMenu**.

**Development set (visible): exactly 5 tasks** used while building the
candidate.
**Sealed holdout: exactly 6 tasks — one per archetype below**, spread so
each of the three repos hosts at least one holdout task (the coverage
matrix is part of the sealed package). Authored in a **separate session**
(not by the candidate's author-context), sealed until the candidate
implementation is frozen. This prevents fitting the rewrite to the test.
For the external-context archetype, the sealed package also contains
**frozen snapshots of the authoritative external sources** (the relevant
docs pages, captured at authoring time) so external claims can be verified
against a fixed reference.

**Atomic seal.** The sealed package is created in **one sealing operation**
(no later additions) and contains: the exact task prompts with per-task
target repo@SHA; ground-truth notes; frozen external-source snapshots; the
complete quality rubric; scorer and verifier prompts and session
configurations; the archetype×repo coverage matrix (including the two
designated third-arm tasks); and a manifest listing every file with
per-file hashes, sealed under a single package SHA-256 recorded at sealing
time. Any change after sealing means re-sealing, recorded in the results
doc.

**The sealed package lives outside every evaluated plugin installation**
(private eval workspace, not in any arm's installed plugin — the plugin's
`evals/public/` carries only non-sensitive harness assets, conventions §1).
An evaluated run receives only the task prompt — never the ground-truth
notes, snapshots, rubric, or judge prompts.

**Source-drift gate (external-context task):** before scoring, the evidence
verifier re-fetches the live authoritative sources and diffs them against
the frozen snapshots. If any section relevant to a ground-truth claim has
materially changed since sealing, the external-context task is declared
**inconclusive** (handled by the failed-run rule: excluded from aggregates,
reported) and is re-sealed with fresh snapshots for a subsequent round —
arms researching live docs are never scored against a stale snapshot.

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
each for the baseline and candidate arms on every holdout task**,
pre-registered — no runs are added or discarded after outcomes are
observed. The fleet-ablation third arm runs **only its two designated tasks**
(see Third arm), 3 replicates each. A timed-out/aborted run counts as a
failed run and is **not** replaced.

**Driver script (pre-registered):** runs are driven by an automated harness,
not a human. The first message is the task prompt. If an arm stops to greet,
ask for the query, or request confirmation before the document exists (the
frozen baseline's scripted greeting does exactly this), the driver
immediately replies with the fixed continuation: *"Proceed with the research
as specified; no additional constraints."* Driver replies add zero
think-time, so wall-clock reflects agent work, not evaluator behavior; each
such stop is still counted under the interventions metric.

## Third arm (2–3 tasks)

A third variant — a **fleet ablation of the candidate** — runs on **exactly
two designated holdout tasks**: the mid-size subsystem-explanation task
(archetype 1) and the narrow where-is task (archetype 3), named as such in
the sealed package at authoring time; 3 replicates each, same pinned
configuration. The ablation is identical to the candidate in every
component — SKILL.md text, artifact contract, acceptance criteria, scripts,
model pin — except: (a) the `research-v2-*` agents are absent, (b) the
fleet-routing guidance is removed, and (c) a pre-registered subagent policy
applies: the ablation arm must not spawn subagents of any type. Any
difference in results is therefore attributable to the agent fleet alone. This answers the strategic question the A/B alone cannot: is
the value in the contract, or do six standing research agents still earn
their keep with modern models?

**Pre-registered third-arm decision rule:** the third arm uses the same
replicate, median, and pairing rules as the A/B arms on its two tasks, and
the same scorer/verifier. The fleet is judged **not earning its keep on the
tested archetypes** iff, on **both** designated tasks, the fleet-ablation
arm's quality median is **no more than 0.5/10 below** the candidate's and
its evidence accuracy **no more than 2 п.п. below** (one-sided
non-inferiority bounds — an ablation arm that matches *or beats* the
candidate satisfies them), while saving **≥30%** tokens or **≥20%**
wall-time (per-task medians). This verdict is advisory — it shapes
the next-phase design, not this pilot's pass/fail — but the criterion is
fixed before the holdout is unsealed.

## Metrics

1. **Quality** — blind rubric score (coverage, relevance, synthesis) against
   the ground-truth note, using the **frozen rubric** from the sealed eval
   package — dimensions, weights, score anchors, and scoring instructions —
   fixed at sealing time (prerequisite 3, atomic seal).
2. **Evidence accuracy** — a **separate evidence verifier** (read-only
   access to the frozen repo@SHA, no knowledge of arms) identifies every
   **verifiable claim** in the document. A claim counts as supported only if
   it both carries a citation (file:line; external citation for the
   external-context task) **and** the cited source actually supports it.
   Evidence accuracy = supported claims / **all** verifiable claims — an
   uncited verifiable claim counts as a failure, so omitting citations
   lowers the score rather than raising it. For the external-context task
   the verifier also gets the frozen external-source snapshots from the
   holdout package and checks external claims and citations against them.
3. **Critical factual errors** — claims contradicted by the frozen repo or
   the frozen external sources, classified by the **evidence verifier**
   using the error definition fixed in the sealed rubric (see the
   critical-error gate in Scoring).
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
- **zero** critical factual errors introduced (per the critical-error gate
  in Scoring);
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
  **mean of per-task deltas**. This rule is fixed here, before any baseline
  run.
- **Failed-run rule:** a timed-out/aborted **candidate or third-arm** run
  fails that arm outright (pass bar). A timed-out/aborted **baseline** run
  renders that task **inconclusive**: the task is excluded from every
  holdout-level aggregate and the exclusion is reported in the results doc.
  If fewer than 3 holdout tasks remain conclusive, the experiment yields no
  verdict and is re-run with a fresh sealed holdout — the pass calculation
  never proceeds on partial baselines.
- **Critical-error gate (pre-registered):** the evidence verifier classifies
  critical errors using the definition fixed in the sealed rubric. For each
  distinct critical error and each task, occurrences are **counted** across
  that arm's 3 replicates. The candidate fails if any error's candidate
  occurrence count **exceeds** its baseline count on the same task — this
  covers both introduced errors (baseline count 0, candidate ≥1) and
  frequency regressions of pre-existing errors (e.g. 1/3 baseline vs 3/3
  candidate). Errors whose candidate count is ≤ the baseline count are
  recorded in the results doc but do not fail the arm.
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
   links, plugin manifest. The job must **fail when zero target files are
   found** and ship positive/negative fixtures proving it catches breakage
   (per conventions §4 — a silently no-op gate is a defect; the existing
   `ci.yml` jobs are effectively silent no-ops on this repo). Registered
   dependencies for this gate, both pinned in the CI job: **PyYAML
   `6.0.2`** (real YAML parsing for the frontmatter schema check) and
   **markdown-it-py `3.0.0`** (the CommonMark reference parser for link and
   anchor extraction — hand-rolled Markdown parsing is exactly the
   reinvented mechanism conventions §4 warns against). No other new
   dependencies are authorized by this plan.
2. Pass bar registered (this document, committed before runs).
3. **Atomic seal** (see Eval set): one sealing operation producing the
   complete sealed package — tasks + repo@SHA, ground truth, external
   snapshots, rubric, scorer/verifier prompts and configurations, coverage
   matrix, manifest, single package SHA-256 — authored in a separate
   session.
4. `skills/research-codebase/` skeleton + `research-v2-*` agent copies
   (byte-identical except `name:`).
5. **Eval-runner harness**, proven by a synthetic preflight run on a
   throwaway task (not the dev set), that: verifies the hash of each of the
   three installation artifacts before every run; records model and effort
   for every node of the agent tree; runs in a clean profile with ambient
   personal skills/config excluded; distinguishes **infrastructure
   failure** (harness/environment fault — run invalidated and re-executed)
   from **workflow failure** (timeout/abort — counted per the failed-run
   rule, never replaced); collects tree-wide token/tool-call accounting;
   anonymizes documents before scoring; and launches scorer and verifier in
   fresh pinned sessions.

## Sequence

1. Prerequisites 1–5.
2. Ground-truth notes for the dev set.
3. Dev-set runs (any arm, any order) — used to build and tune the candidate;
   **never counted toward the pass bar**.
4. **Candidate frozen** (commit SHA recorded) and shared runtime
   configuration pre-registered.
5. **Holdout unsealed only now.** All holdout runs executed under the
   pinned configuration in randomized, interleaved order: baseline and
   candidate on every holdout task, the third arm on its two designated
   tasks — exactly 3 replicates per arm per task.
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
