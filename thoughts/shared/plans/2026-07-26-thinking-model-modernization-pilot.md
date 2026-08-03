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
authorization —

1. `CLAUDE.md` imports `@AGENTS.md` (Claude Code does not read AGENTS.md
   natively; the import is the official interop path).
2. `thoughts/shared/research/2026-07-26-repo-ontology-sota.md` gains an
   evidence-scope note (the ETH/DeepMind result covers LLM-generated
   always-loaded context files, not all generated artifacts) — a
   bibliography correction requested in the same review; it changes no
   pilot-relevant conclusion.

On item 1: This is a
repo-wide instruction-loading change, explicitly requested by the owner
alongside the CI gate, and is not part of the pilot's evaluated surface.
Because the frozen `a7de5f6` tree predates the import, arm parity is
enforced by a **common overlay**: building the baseline installation
artifact applies the identical one-line `@AGENTS.md` import to its
`CLAUDE.md` as a recorded build step, so both arms' installation artifacts
— whose hashes the eval-runner verifies before every run (prerequisite 5)
— load repository instructions identically, and instruction loading cannot
be an arm difference. The same overlay policy covers **metadata tooling**
(recorded 2026-07-27, second candidate review): the baseline build also
receives the current `scripts/spec_metadata.sh` — whose detached-HEAD
branch fallback and numeric `%z` offset the artifact-compatibility gate
depends on — because metadata collection is shared infrastructure, not
evaluated workflow content; without it the frozen script's empty branch
line in detached eval worktrees would turn conforming baseline runs into
counted failures and corrupt the comparison.

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
doc. Seal-controlled paths that later enter operator argv are fixed generic
identifiers: `judge-prompts/{scorer,verifier}.md`,
`judge-schemas/{scorer,verifier}.json`, `quality-rubric.md`,
`coverage-matrix.json`, and `task-contexts/holdout-v2-N.md`; private task
semantics may not be encoded in those filenames.

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
   three installation artifacts before every run; records the effective
   model for every node of the agent tree and enforces the **registered
   effort policy** — effort is always pinned on the backend command line
   (a command without the pin is refused); nodes that report an effective
   effort are validated against the registered value (`per_node` capture);
   when the backend's stream schema exposes no per-node effort field (the
   current Claude headless schema does not), the run is accepted solely on
   the strength of the command-line pin and recorded as `command_pin`
   capture; partial reporting is broken capture and invalidates the run;
   the **real-backend preflight must additionally demonstrate that the
   pinned CLI applies the effort flag to the whole session tree (main
   context and subagents)** — if it cannot, the pilot is blocked until it
   can; runs in a clean profile with ambient personal skills/config
   excluded; distinguishes **infrastructure failure** (harness/environment
   fault — run invalidated and re-executed) from **workflow failure**
   (timeout/abort — counted per the failed-run rule, never replaced), with
   partial transcripts from timeouts/aborts validated for model/effort
   parity first (runtime drift invalidates instead of counting); collects
   tree-wide token/tool-call accounting; anonymizes documents before
   scoring; and launches scorer and verifier in fresh pinned sessions.

**Prerequisite status (2026-07-26):**

1. CI validation gate — **done** (merged with the v0.2.1 prerequisites PR;
   `docs-validate` green in CI).
2. Pass bar — **done** (registered in this document before any runs).
3. Atomic seal — **done** (2026-07-27, authored in a separate
   uncontaminated session per the protocol; only the package hash and
   task basenames returned to this context):
   `seal_package_sha256 =
   e611ada9427954e34b597e093d7da35acb278d534dbdf54dffef72700a5da95c`;
   sealed holdout tasks: `holdout-1.md`, `holdout-2.md`,
   `holdout-3.md`, `holdout-4.md`, `holdout-5.md`, `holdout-6.md`
   (six tasks, matching the archetype coverage design). The sealed
   package (manifest, ground truth, snapshots, rubric, judge
   configurations, designated third-arm tasks) lives in the private
   eval workspace; its content remains unseen by this implementation
   context and stays sealed until Sequence step 5.
4. Skeleton + `research-v2-*` copies — **done** (v0.2.1 prerequisites PR).
5. Eval-runner — harness landed at
   `skills/research-codebase/evals/public/` (`runner.py`, `mock_claude.py`,
   `preflight.py`); the synthetic preflight proves all capabilities against
   the deterministic mock backend (capability→proof map in
   `evals/public/README.md`). Per-node effort capture is bounded by the
   backend stream schema; the two-mode effort policy in prerequisite 5
   above is the authoritative requirement (revised 2026-07-26 in response
   to review). The **real-backend preflight** on the throwaway task —
   **done 2026-07-27** (see the formal-preflight record after the
   candidate-freeze section): one sandboxed real run per arm under the
   full pinned configuration, effort pinned on every backend command
   line with `command_pin` capture across the session tree.

**Candidate status (2026-07-27):** the behavioral rewrite landed on the
owner's instruction («продолжай по очереди все»): kernel `SKILL.md`
completed per §2 anatomy, six platform-neutral agent contracts extracted
to `references/agent-contracts/`, `research-v2-*` reduced to thin
adapters, `commands/research_codebase.md` reduced to the thin
compatibility wrapper (opus parity pin retained), fleet routing isolated
in `references/fleet-routing.md` for the ablation build, Quick Install
copies `skills/`, plugin version bumped. **Frozen 2026-07-27** after
dev-set tuning round 1 (see the freeze record before the Sequence
section); no holdout material has been seen by this implementation
context.

**Dev set status (Sequence step 2):** authored. Public tasks dev-3/dev-4
(target: this repo) live at `skills/research-codebase/evals/public/dev-set/`;
private tasks dev-1/dev-5 (livekit-voice-agent @ `9d65fff`) and dev-2
(neomenu @ `aa8b8d1`) were delivered to the owner for the private eval
workspace per the privacy rule and are not committed here.

**Dev-set tuning round 1 (Sequence step 3, recorded 2026-07-27, owner
instruction «запускай прогоны на dev-сете»; the sequencing exception for
running ahead of the seal and the formal preflight is documented in
Ordering note 2 below):** candidate (merged master,
opus/high, real backend, harness-enforced artifact gate) ran dev-3 and
dev-4 directly (dev config, nonstandard topology). Round 1: both runs
covered their full visible ground truth with zero subagents spawned
(dev-3's over-orchestration probe passed), but BOTH artifacts were
counted workflow failures on metadata discipline — dev-3 improvised
divergent prose for the detached-HEAD branch value in frontmatter vs
body; dev-4 inserted a checkout caveat paragraph inside the
title-adjacent metadata block. One kernel Process-guidance fix
(metadata collected once; `detached@<short-sha>` for detached
checkouts; byte-identical repetition across both placements; nothing
but the five lines in the block). Round 2 on the tuned kernel: both
tasks completed through the artifact gate with full ground-truth
coverage, zero subagents, and lower cost (dev-4: 43 tool calls / 359 s
vs 73 / 531 s in round 1). Private-target dev tasks (dev-1/2/5) run
from the private eval workspace; only aggregates come back here.

**Ordering note (explicit owner decision, 2026-07-26):** dev-set authoring
was executed together with prerequisite 5 on the owner's explicit
instruction ("продолжай с eval-runner и dev-set"), ahead of the atomic
seal (prerequisite 3) and the real-backend preflight. This revises the
nominal prerequisite→dev-set ordering for AUTHORING only: dev-set tasks
never count toward the pass bar, no baseline/candidate/holdout run has
been executed, and the atomic seal plus the real-backend preflight remain
hard blockers before any scored run. The sealed holdout is untouched by
this change and is still authored in a separate session.

**Ordering note 2 (explicit owner decision, 2026-07-27):** dev-set tuning
RUNS were likewise executed ahead of the atomic seal (prerequisite 3) and
the formal real-backend preflight, on the owner's explicit instruction
(«запускай прогоны на dev-сете»), issued immediately after a status
report that stated the seal was still pending owner-side and the formal
preflight deferred to candidate freeze — the ordering context was before
the owner when the instruction was given. Scope of this exception: the
public dev tasks only (dev-3/dev-4), on the candidate arm, as protocol
tuning evidence. It changes nothing about the pass bar: dev runs are
never counted toward it, no baseline or holdout run has been executed,
no holdout material has entered this context, and the atomic seal plus
the formal real-backend preflight on the pinned configuration remain
hard blockers before any scored run. (The 2026-07-27 mechanical CLI
shakedown validated the integration path — namespaced entrypoint, model
pin resolution, stream parsing — but does not substitute for the formal
preflight, which still stands.)

**Candidate freeze (Sequence step 4, recorded 2026-07-27, owner
instruction «давай, шаг 4»):**

- **Frozen candidate SHA:** `b731f06cdff5f38c0fa4c5aa64f93277d69e741d`
  (master merge of the dev-set tuning PR — the last behavioral change;
  later commits are protocol records only).
- **Installation artifacts** are built deterministically by
  `skills/research-codebase/evals/public/build_installs.py` (pinned
  SHAs inside; rebuild reproduces identical trees) and registered by
  the tree hashes the eval-runner verifies before every run:
  - baseline (frozen `a7de5f6` + recorded common overlay — `@AGENTS.md`
    import line, current `scripts/spec_metadata.sh`):
    `2762bf04e9ea82fec520906a0db0382eadff5c99cada5b44ba2f1c49a3e7b28c`
  - candidate (frozen tree verbatim):
    `5638b81633610a68192cc5d03dba4d1022175aa1980b27a209b3114d4c4d126c`
  - ablation (candidate minus the six `research-v2-*` adapters and
    `references/fleet-routing.md`; runner-enforced `forbid_subagents`):
    `a1d44b131ebd5d858756280454b9f7f33cb79a4f13d034b2004d5993b21e9b57`
- **Pre-registered shared runtime configuration** (identical across
  arms; installation content is the only arm difference):
  model `claude-opus-5` (the resolution of the command wrapper's
  `model: opus` pin, confirmed against the real CLI 2026-07-27; the
  pin overrides the CLI `--model`, so the registered value is the
  pin's resolution), effort `high` (pinned on the backend command
  line via `{effort}`), entrypoint `/rpa:research_codebase`,
  `backend_cmd = ["claude", "--model", "claude-opus-5", "--effort",
  "{effort}", "--plugin-dir", "{installation}", "--permission-mode",
  "acceptEdits", "--verbose"]`, backend version pinned at
  `2.1.220 (Claude Code)` (probed before every run),
  operator image pinned at
  `sha256:bbe9dbf152c933f4c3a69eae0809983cf698253a7a067fd6b73180ecc85c4975`
  (`linux/arm64`, deterministically rebuilt twice from the prior exact image
  plus a PyYAML wheel whose SHA-256 is
  `5d225db5a45f21e78dd9358e58a98702a0302f2659a3c6cd320564b75b86f47c`),
  artifact parser `pyyaml` version `6.0.2` (probed before any backend
  observation and bound into runtime identity),
  `timeout_seconds 3600`, `max_infra_retries 2`,
  `workflow_abort_exit_codes []` (any registration of real abort
  codes happens at the formal preflight, before any scored run);
  judge sessions mount-free with command selector `--model opus` and
  effective-model parity pinned as `judge_model claude-opus-5` /
  `judge_effort high`; live-source re-fetch command fixed as
  `drift_fetch_cmd = ["curl", "-q", "-fsSL", "--config", "-", "-o",
  "{dest}"]` (`-q` disables ambient curl configuration; the sealed URL is
  curl-config input on stdin and is absent from argv); 3 replicates per arm
  per task in randomized interleaved order (unchanged from the registered
  design);
  `sandbox_cmd = ["python3",
  "<orchestrating-checkout>/skills/research-codebase/evals/public/ns_sandbox.py",
  "--confine-to", "{workdir}", "--profile", "{profile}", "--"]` —
  `ns_sandbox.py` (committed alongside this record) confines every
  evaluated and judge session via util-linux `unshare` (user + mount
  namespaces) and a chroot assembled on a private tmpfs from an
  ALLOWLIST: read-write only the run's worktree and its clean profile
  (plus fresh private `/tmp` and `HOME` tmpfs); read-only only the
  OS/toolchain surface (`/usr /bin /sbin /lib* /etc /opt`), the git
  common directory backing the worktree (derived inside the wrapper
  from `workdir/.git`; needed by the metadata script's git calls), the
  environment's TLS-proxy CA bundle (`HOME/.ccr`), and the backend
  CLI's own credential directory (from
  `CLAUDE_SESSION_INGRESS_TOKEN_FILE`, when the host authenticates by
  file). Everything else on the host — other checkouts, sealed
  packages, ground truth, manifests, prior run outputs — is ABSENT
  from the session's mount tree, not merely read-only (revised in
  review: an earlier read-only rbind of `/` left host paths readable).
  The wrapper was validated at the formal real-backend preflight
  below; the sandbox script lives harness-side (the orchestrating
  checkout, like `runner.py`), not inside the frozen installation
  trees, so the registered hashes are unaffected.

**Formal real-backend preflight (recorded 2026-07-27, re-run after the
sandbox revision; the last gate before scored runs — now passed):** one
sandboxed real run per arm on the throwaway task (retargeted to the
frozen `b731f06`; never a dev or holdout task), under the full
pre-registered configuration above with the final allowlist wrapper.
Mechanics proven on all three arms: registered installation hashes
verified before each run, `ns_sandbox.py` wired around every session
(probes: writes outside the two rw surfaces fail; a sealed-package
stand-in next to the worktree, `/workspace`, and `/home/user` are
INVISIBLE from inside; git and `spec_metadata.sh` work in the confined
worktree; CLI auth works through the bound credential directory), model
parity `claude-opus-5` on every transcript node, effort pinned on the
command line with `command_pin` capture (the real stream schema carries
no per-node effort field — the registered two-mode policy), both stream
schemas parsed with full tree-wide token accounting, and the artifact
gate enforced uniformly. The wrapper's confinement was hardened seven
times in review (host paths absent rather than read-only; recursive
read-only covering child mounts such as container /etc file mounts
plus a fresh private /dev/shm hiding the host's shared tmpfs; a
private PID namespace — `unshare -rmpf --kill-child` — with a fresh
`/proc` that FAILS CLOSED rather than falling back to a host bind
that would re-expose sibling process cmdlines; credential FILES bound
individually instead of their parent directory, at every path the CLI
can name them under — the environment's possibly-symlinked path and
its resolved target; the operator clone's git directory replaced by a
PRIVATE pinned-closure repository — exactly the sealed commit fetched
into a fresh bare store, no refs or reflogs beyond it, so `git log
--all` / `git cat-file --batch-all-objects` cannot reach history
newer or more private than the pin; commits newer than the pin
resolve to `bad object`). The pinned store lives INSIDE the worktree
(`.pinned-git`, read-only via a namespace-local self-bind, excluded
from `git status`): the backend CLI's permission layer blocks git
metadata outside the session's allowed directories (the series-5 runs
surfaced exactly that — sessions reported git unavailable — and were
re-executed after the fix), and the runner's worktree removal cleans
the store with the run, so no repository content persists on the host
outside the run's own workspace. The pinned closure is bounded by the
operator clone's completeness: a partial/shallow operator clone
yields a correspondingly partial closure (never more). Per-arm runs
were re-executed after every revision. Final-wrapper outcomes (series
7): candidate **completed** (244 s) and ablation **completed** (297
s, **zero subagents**: the pre-registered no-subagent policy held);
baseline mechanics green (git metadata correct through the pinned
store), artifact gate-rejected on legacy formatting in this
replicate. **Recorded observation (six formatting-relevant baseline
replicates across the preflight series):** legacy formatting
discipline is VARIABLE — rejected / passed / rejected / passed /
rejected / rejected (backticked body metadata values, improvised
branch prose, dates without a time component) — so gate-failed
baseline replicates are a realistic holdout outcome (3 of 6 here). The gate is pre-registered and uniform across arms and is NOT
adjusted post-freeze; any protocol amendment (e.g. separate judging of
gate-failed artifacts' content) is an owner decision and would have to
be registered before Sequence step 5 unseals the holdout. No real
workflow-abort exit codes were observed; `workflow_abort_exit_codes`
stays `[]` as registered.

**Registered amendment — diagnostic content axis (owner decision
2026-07-28, registered BEFORE Sequence step 5; the holdout remains
sealed):** the owner selected option 2 of the recorded question, with
this scope:

- **The primary end-to-end outcome is unchanged.** An artifact-gate
  rejection stays a counted workflow failure — binary, per replicate,
  uniform across arms. No repairs, no re-runs.
- **A separate diagnostic axis scores CONTENT for every produced
  document.** The blind scorer judges the content of gate-passed and
  gate-failed documents alike, under the same sealed rubric and
  procedure; diagnostic results are reported alongside — never inside —
  the primary outcome, so the results can show whether the baseline
  loses on format discipline, on content, or on both.
- **Mechanism (harness, registered with this amendment):** a
  gate-failed replicate's anonymized document is preserved as
  `run-<id>-diag.md` with its digest recorded as `diagnostic_sha256`
  in the run record and manifest (verified against the immutable run
  record like the primary digest). Scoring gains a manifest-bound
  `--diagnostic-axis` batch — completed replicates' anonymized
  artifacts PLUS gate-failed replicates' diagnostic copies, each
  exactly once, digest-verified, task-context-routed, with every
  judge output labeled `axis: diagnostic`; the primary batch is
  unchanged and refuses diagnostic documents. Proven by the synthetic
  preflight (155/155) before any holdout run.

**Registered amendment — macOS sandbox wrapper (owner decision
«поправка для мак», 2026-07-28, registered before Sequence step 5; the
holdout remains sealed):** scored runs may execute on the operator's
macOS host with `sandbox_cmd = ["python3",
"<orchestrating-checkout>/skills/research-codebase/evals/public/macos_sandbox.py",
"--confine-to", "{workdir}", "--profile", "{profile}", "--"]` — the
same CLI contract and confinement goals as the registered Linux
wrapper: a deny-default `sandbox-exec` SBPL profile (host paths
UNREADABLE, not merely unwritable), read-write only the run's worktree,
its clean profile, and a fresh private TMPDIR/HOME created per session;
credential FILES allowed as literals (environment-variable auth passes
through untouched); and the same pinned-closure git store via the
shared builder in `ns_sandbox.py` — macOS has no mount namespaces, so
the session reaches the store through GIT_DIR/GIT_WORK_TREE in its
environment while the worktree's `.git` file stays UNTOUCHED (a real
rewrite could not be restored if the runner's timeout SIGKILLs the
wrapper's process group); the operator clone the file points at stays
denied by the profile, and the store itself is write-denied by an
explicit last-match rule, matching the Linux wrapper's read-only bind.
**Validation
boundary:** the Linux implementation context cannot execute
`sandbox-exec`, so before any scored run `macos_sandbox_check.py` MUST
pass on the operator host (probes mirror the Linux wrapper's validated
properties: rw surfaces writable, write-outside denied, a sealed
stand-in unreadable, fresh private HOME, pinned git with a
newer-than-pin commit resolving to `bad object`, a write into the pinned store denied, the backend CLI
starting under the wrapper) and its full PASS output is recorded with
the results. The Linux wrapper remains the registered default; the
backend version pin (`2.1.220 (Claude Code)`) applies unchanged on the
macOS host.

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
   **Execution (recorded 2026-07-28):** step 5 runs on the operator host
   that holds the sealed package and the target clones, driven by
   `skills/research-codebase/evals/public/step5_operator.py` — a
   mechanical restatement of this plan's freeze record that FAILS
   CLOSED before any scored run: it refuses a config whose arms,
   model/effort/entrypoint, installation hashes, seal hash, backend
   version pin, timeouts or retry policy differ from the registered
   values; it rebuilds the three installations and verifies them
   against both the registered hashes and the config's registrations;
   on macOS it requires the mandatory `macos_sandbox_check.py` to pass;
   it verifies the seal manifest and the six registered holdout task
   basenames; and only then writes the pre-registered schedule and
   executes it (resumable). The driver never reads or prints holdout
   task CONTENT — basenames and digests only — so operating it exposes
   no sealed prompts or ground truth. The **implementation context that
   authored the candidate does not execute step 5** and has still seen
   no holdout material.
6. Blind scoring + evidence verification.
7. Results doc in `thoughts/shared/research/` (aggregated, sanitized) with a
   go/no-go recommendation — scoped to the Claude-side research pattern.
   Extension to planning / TDD / refactoring families and the Codex skill
   adapter each get their own representative gate.

**Sequence step 7 status (2026-08-01): complete.** The sanitized results are
recorded in
`thoughts/shared/research/2026-08-01-thinking-model-modernization-pilot-results.md`.
The candidate's primary pass is **not established**: artifact-gate failures
and malformed judge responses leave the pre-registered quality, evidence,
and critical-error aggregates mathematically undefined, while the diagnostic
axis is explicitly barred from backfilling primary cells. The formal verdict
is therefore indeterminate and rollout remains an operational no-go pending a
protocol decision and fresh sealed round. A descriptive calculation that
includes all final gate-failed runs gives 20.169% mean token savings and
11.608% wall-time savings, but the binding efficiency verdict is also
indeterminate because that population treatment was not registered;
candidate ritual stops and timeout/abort failures are zero. The fleet-ablation
redundancy criterion is not satisfied because its clean T3 cell fails the
efficiency condition. No post-hoc imputation or judge-response repair was
applied.

## Protocol v2 amendment — fresh sealed round (registered 2026-08-01)

The owner authorized a fresh round after reviewing the indeterminate first
round. This amendment is prospective: it does not reinterpret, repair, or
reuse any task, artifact, judge response, or score from the completed round.
The original arm definitions, frozen candidate
`b731f06cdff5f38c0fa4c5aa64f93277d69e741d`, runtime pins, six-archetype
coverage, three replicates, random interleaving, pass thresholds, and two-task
ablation remain fixed unless this section expressly replaces a rule.

### Registered v2 population and failure rules

1. Each scheduled arm×task×replicate slot has exactly one final workflow
   outcome after the existing maximum of two infrastructure retries.
   Infrastructure retries replace only harness, backend-transport, runtime-
   parity, or environment failures. A timeout, registered abort, missing
   document, artifact-contract rejection, or ablation-policy violation is a
   workflow outcome and is never repaired or rerun.
2. Artifact compatibility is a **separate mandatory binary gate**, uniform
   across arms. A produced document passes only when the registered validator
   completes and reports no defects; the global legacy-consumer compatibility
   preflight remains a prerequisite for the frozen artifact format. Validator
   crash or indeterminate validator output is infrastructure failure, not a
   gate failure. Every candidate artifact must pass; one candidate rejection
   fails the candidate. An ablation rejection means fleet redundancy is not
   established. Baseline rejections remain observed baseline outcomes and do
   not erase their content/evidence observations.
3. A valid scheduled slot produces **exactly one nonempty** research Markdown
   document. An empty/whitespace-only fresh `.md` is a no-document outcome.
   More than one nonempty fresh document makes the round terminally invalid:
   the harness preserves byte-and-digest evidence and never selects a convenient
   winner post hoc. The one nonempty document is anonymized, digest-bound to its
   run, and judged exactly once by the blind content scorer and exactly once by
   the evidence verifier, whether the artifact gate passed or failed. Judges
   are not told the arm or gate result. V2 therefore has one all-documents
   content population per role, not separate primary and diagnostic judge
   calls. Gate-passed `-anon.md` and gate-failed `-diag.md` copies are mutually
   exclusive inputs selected from the immutable run manifest. Gate status is
   reported separately and may be used for a descriptive content-by-gate
   breakdown, never to delete or substitute a score.
4. The original no-document rules remain binding: a candidate timeout, abort,
   or missing document fails the candidate; the corresponding ablation
   outcome prevents a redundancy finding. A baseline timeout, abort, or
   missing document makes that task inconclusive and excludes it from every
   holdout aggregate. Fewer than three conclusive baseline tasks yields no
   verdict. No-document outcomes are not sent to judges and are never
   imputed.
5. Cost and latency use **all final scheduled workflow outcomes with complete
   runtime accounting**, including artifact-rejected outcomes. Superseded
   infrastructure attempts and source-drift-excluded tasks do not enter the
   binding population. Timeout/abort latency is the measured run-start to
   terminal-outcome interval under the registered ceiling; tokens are the
   observed tree-wide total. Missing or incomplete final-run accounting is an
   infrastructure fault, never a zero or an exclusion chosen after outcomes.
   The deadline and elapsed duration are measured from one monotonic clock;
   wall-clock adjustments cannot change the ceiling or latency telemetry.
   Every nonblank event in a timeout/abort transcript must be valid strict
   stream JSON and every model-bearing node must carry typed, nonnegative,
   nonzero model-token accounting. Because the workflow outcome has already
   been observed, incomplete/malformed accounting or runtime parity after a
   timeout/abort is a terminal operator block and is never infrastructure-
   retried.
6. Agent-tree parity precedes outcome classification: every observed Task
   launch must have model-bearing child accounting. In the no-subagent arm, a
   launch without that child evidence terminally blocks (the policy event was
   observed but cannot be costed or parity-validated). When a fully-accounted
   no-subagent-policy violation and timeout/abort occur in the same run,
   `subagent_policy` is the deterministic primary failure kind and the
   timeout/abort kind and detail are retained as secondary evidence. This
   preserves both observations while keeping the ablation gate internally
   consistent.
7. A materiality adjudication for changed external context is valid only for
   the exact live bytes it reviewed. Each changed sealed source therefore
   records `observed_sha256`, boolean `material`, and a nonempty `rationale`;
   the harness re-fetches the source itself and refuses a digest mismatch.
   Scorer and verifier re-fetch independently, preserve that digest in their
   immutable drift decision, and aggregation requires identical decisions.
   A source version change between the two role batches invalidates the round
   instead of silently reusing a verdict prepared for earlier bytes.

### Registered v2 judge contract

The runtime config and fresh seal both record `protocol_version: 2` and
`max_judge_attempts: 3`. The seal contains role-associated JSON Schema files,
their per-file hashes, the semantic rules below, and the fixed retry policy.
The schema version, retry bound, aggregation policy, judge command/model/
effort, and package digest are part of the schedule and scoring-batch identity.
Every judge invocation receives the sealed role prompt, quality rubric, exact
role schema, task context, and candidate document in that fixed order, followed
by the deterministic exact-key reminder derived from the same role contract;
prompt and rubric digests are recorded in batch, attempt, and result identity.
These bytes, all evaluated-task and continuation prompts, and every judge
document are transported only through the child process's UTF-8 stdin; `-p`
remains a flag in argv but no prompt bytes are process-list-visible. The sole
argv exception is the deterministic generic public structural schema supplied
by the harness through `--json-schema`; it contains no sealed prompt, task,
context, rubric, document, source URL, or ground truth, and the configured
judge command may not supply or override it. Likewise,
the credential-free sealed live-source URL reaches the fixed curl command only
as safely quoted curl-config stdin and is suppressed from harness error text.

All evaluated and judge processes use the fixed
`claude-cli-minimal-env-v1` environment policy: only the pinned Claude auth,
proxy/TLS, locale, HOME/PATH, and sandbox-wrapper variables cross the process
boundary. Arbitrary ambient cloud, source-control, and developer-tool
credentials are absent. This policy is implemented by the frozen public
harness and proven with a secret-canary preflight before sealing.

- A judge response is exactly one UTF-8 JSON object: no Markdown fence,
  wrapper prose, trailing value, duplicate key, unknown property, non-finite
  number, or tolerant repair. Resource bounds are 1 MiB UTF-8, nesting depth
  32, 2,000 aggregate array items, and 20,000 UTF-8 characters per string.
- The scorer object has exactly `coverage`, `relevance`, `synthesis`, `total`,
  and `summary`. Each component has exactly numeric `score` and a nonempty
  `rationale`; bounds are 0–4, 0–3, and 0–3 respectively, in quarter-point
  increments. `total` is 0–10 in quarter-point increments and must equal the
  exact integer-quarter sum of the components. `summary` is nonempty.
- The verifier object has exactly `verifiable_claims`, `supported_claims`,
  `unsupported_claims`, `unverifiable_claims`, `claim_ledger`,
  `critical_errors`, `critical_error_count`, and `summary`. Counts are
  nonnegative integers; `verifiable_claims` equals the other three claim
  counts' sum. There is exactly one ledger row per counted claim and ledger
  status counts reconcile with the counters. A supported row has at least one
  candidate citation and one evidence reference. Critical-error entries use
  the sealed category enum, contain evidence, and have unique normalized
  propositions within one response. The judge does **not** emit
  `evidence_accuracy`; the harness derives the exact ratio
  `supported_claims / verifiable_claims` (zero when the denominator is zero),
  and rounding is display-only.
- Each required record receives at most three total attempts. Every attempt is
  a fresh pinned, isolated session with identical prompt, document, context,
  settings, output contract, and limits; it sees neither prior output nor
  validation defects. The first schema-valid response is irrevocably accepted.
  Every raw attempt and validation result is retained. Invalid output is judge
  infrastructure, never a workflow score. If three attempts are exhausted,
  the entire round is protocol-invalid: no repair, fence stripping, score
  recovery, imputation, judge substitution, selective rejudge, partial median,
  or reuse of a prior-round response is permitted.
- Native structured generation is an output aid, not a replacement validator.
  The CLI's ordinary string `result` and object `structured_output` must each
  independently pass the existing full role validator and normalize to exactly
  the same object; neither view may repair the other. The registered harness
  policy is `claude-cli-json-schema-semantic-reminder-v2`; its unchanged
  public structural subset remains `claude-cli-json-schema-structural-v1`.
  The public structural-schema SHA-256 is
  `ec21f5722725501edf6d29741a85e93f0ed4611d443540452a3b907e382adcc7`
  for the scorer and
  `feba3d9047ff1aa9b2da959e8431e177bdf9e6117ed2ffed972772e2ebddebe0`
  for the verifier. The deterministic high-recency final-response contract
  SHA-256 is
  `6276198554f6a13544cb8a1f39102ddb290d16d6311a982a4ca9d3919c80c14c`
  for the scorer and
  `5db809fa94dd4027078f58bb5e51406963e6f57087b141927cb7112e9dd51505`
  for the verifier. Policy and both role digests bind the seal, runtime pins,
  schedule, batch, every attempt, terminal exhaustion, accepted result, and
  sanitized aggregate evidence; aggregation checks them independently.
- Attempt JSON, pending journals, and external raw-stream sidecars are an
  immutable association. Orphan sidecars, non-contiguous attempts, material
  after a valid attempt, and any symlink/directory/non-regular material at a
  registered attempt name durably invalidate the batch before launch. Evidence
  descriptors never follow unsafe paths, and deleting the offending path does
  not authorize another judge observation.

### Registered v2 aggregation and decisions

- Per task and arm, quality and evidence accuracy are the medians of the three
  all-document judge values. Candidate-minus-baseline task deltas and the mean
  across all conclusive tasks (six when none is excluded by the registered
  baseline/source-drift rules) use unrounded values. Cost and latency use the
  same median-then-mean-percentage pairing already registered, over the final-
  run population above. No cross-task pooling is permitted.
- Artifact success is reported as passed/final runs per arm and is an
  independent candidate gate; format failure does not numerically zero an
  otherwise judged content score. This is the registered resolution of the
  first round's missing-cell ambiguity.
- The critical-error gate is deliberately conservative and deterministic in
  v2: the candidate must have **zero verifier-reported critical-error
  occurrences across all candidate documents**. Baseline and ablation errors
  are reported but cannot excuse a candidate occurrence. This replaces the
  original cross-document “same distinct error” comparison, whose identity
  rule was not machine-defined.
- Candidate pass still requires quality delta ≥ −0.25/10, evidence delta ≥
  −2 percentage points, zero candidate critical errors, zero candidate
  artifact/workflow failures, zero ritual stops, and either ≥20% token savings
  or ≥15% wall-time reduction. These absolute candidate gates cover all six
  scheduled candidate tasks even when a baseline no-document outcome excludes
  one task from paired deltas; an exclusion cannot hide a candidate failure.
  All original thresholds are unchanged.
- The ablation still runs exactly the newly sealed archetype-1 and archetype-3
  tasks. Its quality, evidence, cost, and latency use these v2 populations and
  the original non-inferiority/efficiency bounds. “Fleet not earning its keep”
  is established only when both tasks satisfy every original conjunct and the
  ablation has no artifact, workflow, subagent-policy, or critical-error
  failure. Failure to establish redundancy is not evidence that the fleet is
  positively useful.

### V2 freeze, seal, execution, and proof

**Prospective execution registration (2026-08-01; recorded before schedule
creation and before any holdout outcome):** task basenames are fixed as
`holdout-v2-1.md`, `holdout-v2-2.md`, `holdout-v2-3.md`,
`holdout-v2-4.md`, `holdout-v2-5.md`, and `holdout-v2-6.md`; the ablation
designation remains exactly tasks 1 and 3. Randomization seeds are fixed as
`20260801` for the 42-run schedule, `20260802` for the all-document scorer,
and `20260803` for the all-document verifier. The runtime remains Claude Code
`2.1.220 (Claude Code)`, model `claude-opus-5`, effort `high`, two
infrastructure retries, three judge attempts, and timeout 3,600 seconds. The
operator must mechanically revalidate a real-backend throwaway preflight for
all three arms before it will create or execute the registered schedule.

The first uncontaminated package returned digest
`eeae650b905ff3ea84b7df77672dc9d51e702dfaab77676ea85a32b8f50161c0`,
but it was withdrawn unused before schedule creation when the prelaunch audit
found that materiality decisions were not bound to the exact re-fetched live
bytes. No holdout outcome was observed. The frozen operator intentionally
keeps its all-zero seal sentinel until the same clean sealing boundary updates
the package policy with `observed_sha256` binding and returns the replacement
digest; only that replacement may be registered or executed.

The replacement uncontaminated package was atomically promoted and registered
before schedule creation with digest
`8812c97a59aa16d5c4c023d81798819cbff40b290d84406c7f2551ba7d63b2ed`.
Its only disclosed task identifiers are the six prospective basenames above;
no holdout outcome was observed before this registration.

That package was subsequently withdrawn after seven terminal run records had
been produced, before judging or aggregation. A read-only operator process
inspection unexpectedly exposed one sealed task prompt in the implementation
context, violating the rule that only the package digest and task basenames
return there. No run document or judge result was inspected. The process was
stopped, the complete namespace was preserved as invalid evidence, and no
selective rerun is permitted: execution requires another fresh seal and a new
complete randomized schedule. The operator registration is reset to its
all-zero sentinel until that replacement is registered.

After the argv/stdin privacy hardening was frozen, a third uncontaminated
package was newly authored, atomically promoted, and registered before any
new schedule or outcome with digest
`2b57a466e5168533cc1972d6459e4fc592e5c04af90cccf4f04f655895987077`.
Its disclosed identifiers remain only the six prospective basenames; the
clean sealing boundary also verified canonical internal paths and exact
target-pin availability before promotion.

That third package was withdrawn before schedule creation after its throwaway
real-backend preflight exposed an unbound validator-environment dependency.
The first arm's immutable document was accepted by the registered full YAML
parser but rejected by the dependency-free fallback solely because a legal
plain scalar contained parentheses. No holdout task, document, or outcome was
observed. The complete blocked preflight namespace is preserved; no workflow
retry or selective arm rerun is permitted. The operator image now pins
PyYAML `6.0.2`, and the image/parser identity is fail-closed before model
launch and bound into the config and gate receipt. Conservatively, the seal is
reset to the all-zero sentinel until a new uncontaminated package is authored
after this runtime amendment.

After the parser/image amendment was committed and the pinned container
passed the expanded 257-capability preflight, a fourth uncontaminated package
was authored from scratch, atomically promoted, and independently verified on
both the host and exact operator image before schedule creation. Its digest is
`233987beac8d0da7c819fc159674638c3fab18a69a7d486243b63721f21be162`;
the only disclosed task identifiers remain the six prospective basenames.
The clean boundary also verified canonical internal paths, six distinct task
digests, exact ablation scope, and target-pin availability.

That fourth package and its complete 42-slot execution round were withdrawn
on 2026-08-02 after the all-document scorer exhausted the registered three
attempts for one required record. The strict response validator rejected all
three responses, the scorer batch remained incomplete, and the registered
terminal marker made resume impossible. The verifier and aggregate were not
launched, no partial score or verdict is reported, and the rollout decision
remains indeterminate. All run and judge-attempt evidence is preserved
unchanged in the private workspace. No task, document, response, score, or
schedule from this round may be repaired, selectively rejudged, or reused.
The public operator registration is reset to the all-zero sentinel.

Before another seal is authored, the judge output contract is prospectively
hardened without widening the accepted response language: an exact-key
reminder follows the untrusted candidate document, a deterministic public
structural schema constrains native CLI structured output, and the existing
full semantic validator remains authoritative. The generic public structural
schema is the sole exception to the stdin-only argv rule; it contains no
sealed prompt, task, context, rubric, document, source URL, or ground truth.
Its version and digest are bound into the runtime, schedule, attempt, and
batch identities. Both the CLI string result and native structured object are
strictly validated and required to be equal. This amendment does not add a
fourth harness attempt or authorize any hidden harness-level repair. Before
the next seal is authored, one public synthetic live-backend probe for each
judge role must exercise the exact structured schema, dual-output validation,
model/effort pins, sandbox, and CLI version and persist a digest-verified
receipt. The probe has no operator-selected output path: it derives the sole
`judge-live-probe/` namespace beside the prospective
`holdout-v2-round6/package/`, and namespace creation is an irreversible launch
claim. Its full registered execution identity, canonical receipt digest, and
version are registered before sealing and bound into the package, runtime
config digest, and every standard-v2 seal check; pending, missing, drifted, or
tampered proof blocks direct runner and step-5 entry points. After the
probe registration, every path-free production pin (arms and installation
hashes, model/effort/entrypoint, backend and judge commands/version, retry and
deadline policy, parser/image identity, seeds, and exact sandbox wrapper
bytes) is represented by one public standard-v2 runtime-registration digest.
The atomic seal embeds that digest, and the direct runner, seal verifier, and
step-5 operator all consume the same authority before reading a task, creating
run output, or launching a backend. The explicit
`nonstandard_config: true` marker remains the only dev path and cannot
reconstruct a standard schedule. After the hardening passes the synthetic and
real-backend preflights,
a fresh uncontaminated package with six genuinely new tasks and a completely
new 42-slot schedule is required.

The canonical round-5 live probe completed on 2026-08-02 before any replacement
holdout was authored. It made exactly one public synthetic scorer call and one
public synthetic verifier call in the pinned operator runtime; both roles
passed model/effort parity, the role-specific structural grammar, independent
full validation of `result` and `structured_output`, and exact equality of the
two normalized objects. A no-model replay revalidated both immutable raw
streams. The registered receipt SHA-256 is
`718588743e2199e1c254e59cf51b77328d71d7c98b4dc6d92e54db986d4fd5a8` and
the registered execution SHA-256 is
`d5369a04f841202818476a5afa5c63e48a672a7e8432ae18c3202be285c6b6e8`.
The probe used no holdout task, context, document, ground truth, or snapshot.

The subsequent round-5 seal launch passed its prelaunch controls but ended
without a conclusive final response and without an atomically promoted
package. That launch is therefore protocol-invalid. Its complete namespace is
preserved unchanged as invalid evidence and may never be resumed, repaired,
or reused. No package digest, holdout task content, or holdout outcome was
returned to the implementation context. The public live-probe receipt,
live-probe execution, and seal registrations are reset to their exact
all-zero pending sentinels. The next attempt uses the fresh
`holdout-v2-round6` namespace and requires a new one-shot public live probe,
new atomic seal, and new complete 42-slot schedule; the frozen candidate,
three arms and installation hashes, runtime pins, seeds, six prospective task
basenames, ablation scope, and run design remain unchanged.

The canonical round-6 live probe completed on 2026-08-02 before any round-6
holdout authoring. Its receipt revalidated without another model call. The
registered receipt SHA-256 is
`1e2453bb948abc369fd4e9b9c0bdb1bc29be48d6059bdbce37794dfc150f51aa` and
the registered execution SHA-256 is
`bba66fbd8f7e1d624ff0c1995fe8137d08ace68ebe8a49c533e449a8f732a58d`.
The probe used only synthetic public material and no holdout task, context,
document, ground truth, or snapshot.

The fresh round-6 holdout package was authored in the separately confined
one-shot session after that live-probe registration and atomically promoted
only after its complete manifest, target pins, and package topology passed the
clean-boundary checks. Its registered package SHA-256 is
`2e0aef16a6ce9bc91b8c1865a695e1550c0788ca6ef6aa559b9506c36ea0296f`.
The only returned identifiers were `holdout-v2-1.md` through
`holdout-v2-6.md`; no task, context, ground truth, snapshot, judge prompt, or
holdout outcome returned to the implementation context before registration.

Round 6 then completed its new 42-slot randomized schedule and the complete
all-document scorer batch. The separately isolated verifier accepted four
records, but one required record exhausted all three fixed attempts. Every
attempt carried valid runtime/accounting evidence and no transport defect; all
three independently failed the already-registered semantic reconciliation of
claim counters with the claim ledger. The incomplete verifier manifest and
terminal exhaustion record make the entire round permanently indeterminate.
The aggregate was not launched and no diagnostic outcome was published. All round-6 seal,
schedule, run, scorer, verifier, and raw-attempt evidence remains immutable in
the private workspace and none of it may be repaired, selectively rejudged,
or reused in a later outcome.

Before any new holdout authoring, the output contract is prospectively
hardened without changing the accepted response language or the fixed
three-attempt/no-repair rule. Every already-enforced role semantic invariant
is repeated once in the deterministic final prompt tail; the exact UTF-8 tail
digests above are independently registered and propagated through runtime,
live-probe, batch, attempt/result, exhaustion, and aggregate evidence. The
live-probe policy is now `public-live-dual-output-v2`. Because the public code,
prompt bytes, output policy, runtime-registration digest, and probe execution
identity changed, the round-6 probe and seal cannot authorize another launch:
all live-probe and seal registrations are reset to their exact all-zero
sentinels. The replacement must use a new `holdout-v2-round7` one-shot probe,
six genuinely new tasks, a new atomic seal, and a complete new 42-slot
schedule before scorer, verifier, sanitized reporting, or aggregation.

The canonical round-7 public live probe then completed before any round-7
holdout authoring. It made exactly one synthetic scorer call and one synthetic
verifier call in the pinned operator image at frozen public operator commit
`9a12bc43bd9faf8c03e0549062f7e30bc127a836`, and a no-model replay revalidated
the immutable streams and receipt. The registered receipt SHA-256 is
`fe834f3f72dbc9d9772245aba1e3a0ced7a2568029e231a5c195793b545d81a6`; the
registered execution SHA-256 is
`ff6daec061bd2b15914610fbb5c99bbc4a75538a20856a9065a9937e2710ac38`.
The probe used only public synthetic material. The seal registration remains
the exact all-zero sentinel until a separate one-shot session atomically
authors and promotes the genuinely new round-7 package.

The subsequent round-7 seal launch failed closed before any authoring prompt
or Codex model launch. The private launcher correctly observed that its
duplicated expected probe-version literal still named
`public-live-dual-output-v1`, while the frozen public registration required
`public-live-dual-output-v2`. The clean root had already been exclusively
created, so the one-shot namespace remains invalid and is preserved; the
canonical package placeholder is still empty. No round-7 holdout task,
context, ground truth, snapshot, judge material, package digest, or outcome
was authored or observed. Nevertheless, neither the probe nor any part of the
claimed round-7 namespace may be reused.

Prospectively, the replacement launcher exposes one explicit expected public
probe-version pin and verifies the imported registration against it, instead
of carrying a hidden function-local legacy literal. The public live-probe and
seal registrations are reset to their exact all-zero sentinels. The next
attempt uses the fresh `holdout-v2-round8` namespace and requires a new
one-shot public probe, a new atomic seal, and a complete new schedule.

The canonical round-8 public live probe completed before any round-8 holdout
authoring. It made exactly one public synthetic call per judge role in the
pinned operator image and its immutable receipt revalidated without another
model call. The registered receipt SHA-256 is
`3119b47299f78eba6ca6c718a6f3f28e8b15370f7b1f68a1334ba3aab9331e1c`;
the registered execution SHA-256 is
`876781f01ca42115088190167b67ad6289f6d3e0463dc2e4ab03999bfbebe041`.
No holdout material existed during the probe; seal authority remains the
exact all-zero sentinel until the round-8 one-shot boundary succeeds.

The corrected round-8 one-shot boundary subsequently completed in a separate
clean session and the package independently reverified in the pinned operator
image. Its registered SHA-256 is
`b14a554c558a02349a3c55626de6492aab2cc13d27f3250c9eceb2370f25b4ce` and
the only returned task identifiers are `holdout-v2-1.md` through
`holdout-v2-6.md`. No task, context, ground-truth, snapshot, rubric, or judge
content returned to the implementation context. This digest now authorizes
only the fresh round-8 real-backend preflight, 42-slot schedule, complete
scorer/verifier batches, and independent aggregate described below.

Round 8 then passed the pinned all-arm real-backend preflight and completed
its entire fresh 42-slot randomized schedule. Before either judge role was
launched, the mandatory source-drift fetch found one changed sealed source.
Two independent clean adjudication sessions could not reproduce the exact
bytes bound by that first fetch: repeated registered fetches produced
different SHA-256 values, so no digest-bound materiality decision could be
validly authored. The private binding-failure receipt SHA-256 is
`b94ad804addc1f8eae375b8c84f828bca8efd239a43623be0663b1d3288f1b65`.
No scorer, verifier, or aggregate call was launched, no score or verdict is
reported, and the complete round-8 namespace remains immutable evidence. The
round is indeterminate and neither its probe, seal, schedule, tasks, nor run
documents may authorize or enter a later outcome.

Prospectively, the replacement uses the fresh `holdout-v2-round9` namespace
with live-probe and seal registrations reset to their exact all-zero
sentinels. The clean one-shot sealer must independently fetch every staged
external source three times through the registered URL-over-stdin transport
before manifest creation or atomic promotion. All three raw byte streams must
be identical to one another and to the staged snapshot; a timeout, fetch
error, or mismatch permanently stops that one-shot namespace. This
pre-seal stability control does not canonicalize source bytes and does not
replace the independent pre-score source-drift gate. Round 9 still requires a
new public live probe, six genuinely new tasks, a new atomic seal, and a new
complete schedule before either judge role can run.

The canonical round-9 public live probe completed before any round-9 holdout
authoring at frozen operator commit
`31d62d537d2cdaa7bdb82c39b3e595061ddfa04e`. It made exactly one synthetic
call per judge role in the pinned operator image, and a no-model replay
revalidated both immutable streams. The registered receipt SHA-256 is
`ef437f1ede9ebfa2ae1094780259d3947c9385bd70caf606b579c5449df582db`;
the registered execution SHA-256 is
`1f36a722dc7937b78e3724a096151b9c6f75391ce03eac7ee9f5a90dd6b78fd5`.
The probe used only public synthetic material. Round-9 seal authority remains
the exact all-zero sentinel until the clean one-shot stability gate and
atomic package build succeed.

The round-9 clean one-shot boundary then completed in a separate
uncontaminated session. Before atomic promotion, the private launcher fetched
the single staged external source three times through the registered
URL-over-stdin transport; all three raw digests were identical and matched
the staged snapshot. The read-only stability receipt SHA-256 is
`bdf2a719370c4c17aaf9a6b51f3cc2bae3e5a620a9c2c8c9820641e80ec41c4c`,
and its authorization is bound to the launcher, manifest, and promoted seal.
The package independently reverified in the pinned operator image at
registered SHA-256
`5626d795f0e7a39457ce74ccabdc3e7a0e7372c9f2f64c2f651bf2a9626f1e67`;
only `holdout-v2-1.md` through `holdout-v2-6.md` returned to this context.
No private holdout content returned. This seal authorizes only the fresh
round-9 preflight, complete schedule, drift gate, judge batches, and aggregate.

Round 9 then began its fresh randomized schedule. The first 28 schedule slots
reached terminal workflow outcomes: 17 completed with a passing artifact gate,
and 11 ended as `workflow_failure` with `failure_kind: artifact_contract` and a
failed artifact gate. At zero-based schedule index 28 (the twenty-ninth slot),
the initial infrastructure attempt and both registered retries each observed a
model-bearing subagent node with effective model `claude-sonnet-5`, differing
from the registered `claude-opus-5`. The driver therefore stopped fail-closed
with `infrastructure_retries_exhausted`. Its private terminal receipt SHA-256 is
`1ad6c7f7ef63213381ed53f40108e805403916881c5a1562134951c4d6d1500c`.
No source-drift gate, scorer, verifier, or aggregate was launched. Under the
prospectively registered exhausted-infrastructure rule, the entire round is
indeterminate: its probe, seal, schedule, 28 final outcomes, three superseded
infrastructure attempts, tasks, and documents remain immutable evidence and
may not be resumed, repaired, selectively rerun, or reused.

The post-hoc parity gate behaved correctly, but the failure exposed a
prelaunch control gap: the main-session model pin did not itself constrain
subagent model resolution. Prospectively, the replacement uses the fresh
`holdout-v2-round10` namespace and resets the judge live-probe registration,
the new subagent-model live-probe registration, and seal authority to their
exact all-zero sentinels. Before any round-10 holdout authoring, the harness
must construct, rather than inherit,
`CLAUDE_CODE_SUBAGENT_MODEL=claude-opus-5`; the exact variable name, source
policy, and registered session-model value are bound into the versioned
environment policy, standard runtime registration, probe identities, config
identity, and seal. A separate public one-shot proof must deliberately launch
a model-bearing child whose public agent definition requests `model: sonnet`
and accept only an exact one-parent/one-child lineage in which both report
effective model `claude-opus-5`. Missing, drifted, incomplete, or tampered
judge or subagent-model proof blocks sealing. Round 10 then requires six
genuinely new tasks, a new atomic seal, all-arm real-backend preflight, and a
completely new 42-slot schedule.

1. Implement strict role validation, bounded crash-safe judge attempts,
   all-document role coverage, immutable policy bindings, and deterministic
   aggregation in `skills/research-codebase/evals/public/`.
2. The synthetic preflight must prove valid scorer/verifier acceptance,
   malformed/extra/duplicate/inconsistent response rejection, invalid→valid
   retry, retry exhaustion, crash-safe attempt adoption, scorer+verifier
   coverage of gate-failed documents, exclusive run/judge launch claims under
   concurrent resumes, persistent duplicate-outcome invalidation, telemetry
   populations, and aggregation rejection of incomplete, mixed, or foreign-
   batch inputs.
3. Freeze and commit the public harness while leaving the candidate and three
   registered installation hashes unchanged. A separate uncontaminated
   session then creates **one fresh atomic package** with six genuinely new
   holdout tasks, new ground truth and snapshots, updated quality rubric and
   coverage matrix, updated judge prompts, role schemas,
   semantic/retry/aggregation policies, the explicit `ablation_tasks`
   designation, and per-file hashes. Only its package SHA-256 and task
   basenames return to the implementation context.
4. Register that package hash, run the real-backend preflight on the sealed
   v2 configuration, then execute one fresh 42-run randomized schedule and
   its two all-document judge batches. Any material source-drift exclusion,
   exhausted run/judge infrastructure, or ambiguous post-launch run/judge
   journal makes the round indeterminate and requires another fresh seal and
   complete schedule; deleting a journal never authorizes another observation,
   and no cell- or result-selective rerun is allowed.
5. A deterministic aggregation manifest records protocol/policy IDs and
   SHA-256 digests of the run manifest, accepted judge records, and seal. The
   public results update contains only sanitized aggregates and the go/no-go
   recommendation; old and new private holdout contents remain outside this
   repository.

## Owner decisions (2026-07-26)

1. **Eval repos**: rpa, livekit-voice-agent (confirmed 2026-07-26, replacing
   the earlier Plaintalk option), NeoMenu.
2. **Push flow**: branches in `dsmolchanov/rpa`; the rewrite PR goes through
   the normal Codex review gate like any other PR (advisory, see above).
3. **Blind scorer**: separate model session (see Scoring).
