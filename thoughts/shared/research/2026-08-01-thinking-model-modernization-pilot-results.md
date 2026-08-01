---
date: 2026-08-01
type: pilot-results
scope: /research_codebase workflow family (Claude-side)
status: primary verdict indeterminate; operational no-go pending protocol decision
plan: thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md
seal_package_sha256: e611ada9427954e34b597e093d7da35acb278d534dbdf54dffef72700a5da95c
---

# `/research_codebase` reasoning-era modernization pilot — results

## Executive verdict

The candidate's pre-registered **primary pass is not established**. The
formal pass/fail verdict is **indeterminate**, and rollout remains an
operational **no-go** until the protocol gap below is resolved.

The execution itself is complete and auditable: 42 final runs, 25 primary
scorer records, 25 primary verifier records, and 42 diagnostic scorer
records. The blocker is not missing execution data. It is that artifact-gate
failures removed 17 documents from the primary scoring population, while
malformed judge responses made many of the remaining scores unusable. The
pre-registered protocol defines neither score imputation nor medians from
fewer than three replicates, and expressly forbids diagnostic scores from
backfilling the primary outcome.

The table separates binding findings from a descriptive efficiency scenario:

| Criterion | Result | Status |
|---|---:|---|
| Mean task-level token change | −20.169% | descriptive; population treatment undefined |
| Mean task-level wall-time change | −11.608% | descriptive; population treatment undefined |
| Efficiency OR clause | token threshold met under inclusive-run scenario | indeterminate |
| Candidate ritual stops | 0 | pass |
| Candidate timeout/abort failures | 0 | pass |
| Holdout quality delta | not computable | indeterminate |
| Holdout evidence-accuracy delta | not computable | indeterminate |
| Critical-error occurrence gate | not computable | indeterminate |

The fleet-ablation result does **not** establish that the agent fleet is
redundant. Its clean T3 cell fails the efficiency condition by itself; T1 is
descriptive because its ablation cell contains an artifact-gate failure. The
quality/evidence non-inferiority cells are also incomplete.

## Protocol and privacy boundary

This report applies only to the Claude-side `/research_codebase` pattern on
the pinned model, CLI, effort, repositories, and sealed holdout registered in
the plan. It does not authorize repo-wide rollout, planning/TDD/refactoring
rewrites, or a Codex adapter.

Only aggregated and sanitized results are reported. Holdout prompts,
ground-truth notes, judge prompts, raw documents, judge prose, private
repository paths, code snippets, run IDs, and session IDs remain private.
The aliases `T1`–`T6` below identify holdout cells without revealing task
content.

## Run population and integrity

- Final scheduled runs: **42** — baseline 18, candidate 18, ablation 6.
- Superseded infrastructure attempts: **6**, excluded from every metric.
- Source-drift exclusions: **0**.
- Timeout/abort failures: **0** in every arm.
- Every judging-manifest entry has an exact individual judge record; no
  record is missing or mismatched.
- All six ablation runs record zero subagent launches, children, spawned
  agents, subagent tokens, and subagent tool calls.

| Arm | Final runs | Artifact-gate passed | Artifact-gate failed |
|---|---:|---:|---:|
| Baseline | 18 | 4 | 14 |
| Candidate | 18 | 16 | 2 |
| Ablation | 6 | 5 | 1 |
| **Total** | **42** | **25** | **17** |

Primary-document availability by task explains why the registered medians
cannot be reconstructed:

| Task | Baseline | Candidate | Ablation |
|---|---:|---:|---:|
| T1 | 0/3 | 3/3 | 2/3 |
| T2 | 1/3 | 3/3 | — |
| T3 | 0/3 | 3/3 | 3/3 |
| T4 | 0/3 | 3/3 | — |
| T5 | 0/3 | 1/3 | — |
| T6 | 3/3 | 3/3 | — |

Only T6 has complete A/B primary documents. The registered quality and
evidence rule nevertheless requires three usable judge values for each arm,
not merely three documents.

## Judge-output validity

Judge responses were parsed as strict JSON. No fence stripping, prose
removal, brace completion, score recovery, or other post-outcome repair was
performed.

| Batch | Records | Strict JSON | Conservative usable | Invalidity |
|---|---:|---:|---:|---|
| Primary quality scorer | 25 | 14 | 14 | 11 truncated/unbalanced objects at EOF |
| Primary evidence verifier | 25 | 23 | 23 | 1 fenced wrapper; 1 non-strict prose/fenced response |
| Diagnostic quality scorer | 42 | 30 | 29 | 12 truncated/unbalanced objects at EOF; 1 internally inconsistent total |

The internally inconsistent diagnostic response reports components summing
to 6.75 while its `total` field says 8.5. Excluding it is a conservative
**post-hoc sensitivity rule**, not a pre-registered decision; retaining either
number would still leave that cell below three usable replicates and would not
create a paired A/B diagnostic triplet. Verifier responses also use different
decimal rounding. Evidence accuracy in this report is computed from the
registered formula `supported_claims / verifiable_claims`, not from a rounded
display field.

## Primary score availability

`n/3` is the number of usable judge records. A median is shown only for a
complete triplet.

| Task | Arm | Primary quality | Primary evidence |
|---|---|---:|---:|
| T1 | Baseline | 0/3 | 0/3 |
| T1 | Candidate | 2/3 | 3/3 — 95.556% |
| T1 | Ablation | 2/3 | 2/3 |
| T2 | Baseline | 1/3 | 0/3 |
| T2 | Candidate | 1/3 | 3/3 — 96.774% |
| T3 | Baseline | 0/3 | 0/3 |
| T3 | Candidate | 2/3 | 2/3 |
| T3 | Ablation | 2/3 | 3/3 — 93.651% |
| T4 | Baseline | 0/3 | 0/3 |
| T4 | Candidate | 0/3 | 3/3 — 97.059% |
| T5 | Baseline | 0/3 | 0/3 |
| T5 | Candidate | 1/3 | 1/3 |
| T6 | Baseline | 2/3 | 3/3 — 95.833% |
| T6 | Candidate | 1/3 | 3/3 — 93.750% |

No arm/task cell has a complete primary-quality triplet. T6 provides the
only complete paired evidence observation: candidate minus baseline is
−2.083 percentage points. That single task is not the registered holdout
mean and cannot decide the evidence pass bar.

Among the 23 usable verifier responses, 20 report zero critical errors and
three report one occurrence each: candidate T1, candidate T2, and ablation
T1. T6 has complete A/B verifier triplets and zero errors in both arms. The
remaining baseline cells are incomplete; their missing records cannot be
treated as zero occurrences, so the cross-task critical-error gate is not
computable.

## Descriptive efficiency scenario and execution telemetry

The median-and-mean formula is pre-registered, but the protocol does not say
whether telemetry from an artifact-gate-failed final run enters the primary
population. The table therefore applies one transparent **descriptive
scenario**: include all 42 final runs because failed records preserve their
accounting, and exclude the six superseded infrastructure attempts. It is not
a binding pass-bar result.

| Task | Token change | Wall-time change |
|---|---:|---:|
| T1 | −54.650% | −27.339% |
| T2 | −51.935% | −11.751% |
| T3 | +66.436% | −9.180% |
| T4 | −48.952% | −28.848% |
| T5 | −36.178% | +1.697% |
| T6 | +4.266% | +5.775% |
| **Mean** | **−20.169%** | **−11.608%** |

Under this scenario, token savings clear the 20% threshold by 0.169 percentage
points, while wall-time savings miss the 15% threshold. Because the population
rule is unregistered, the binding efficiency verdict remains indeterminate.

The table below is sanitized execution telemetry. Tokens and tool calls are
tree-wide medians; `main/sub` are separately computed median subtotals. Wall
time is the task/arm median. Spawned agents and stops are cell totals.

| Task | Arm | Median tokens (main / subagent) | Median wall | Median tools | Spawned | Stops |
|---|---|---:|---:|---:|---:|---:|
| T1 | Baseline | 23,821,120 (10,454,352 / 9,541,343) | 612.904 s | 145 | 17 | 0 |
| T1 | Candidate | 10,802,811 (10,802,811 / 0) | 445.341 s | 66 | 3 | 0 |
| T1 | Ablation | 10,591,264 (10,591,264 / 0) | 505.954 s | 65 | 0 | 0 |
| T2 | Baseline | 32,534,203 (6,258,131 / 22,434,545) | 607.948 s | 264 | 20 | 0 |
| T2 | Candidate | 15,637,545 (15,637,545 / 0) | 536.510 s | 75 | 3 | 0 |
| T3 | Baseline | 1,385,242 (1,087,568 / 348,964) | 216.767 s | 45 | 5 | 1 |
| T3 | Candidate | 2,305,541 (2,305,541 / 0) | 196.867 s | 34 | 0 | 0 |
| T3 | Ablation | 3,568,498 (3,568,498 / 0) | 285.200 s | 47 | 0 | 0 |
| T4 | Baseline | 12,417,083 (6,760,639 / 5,656,444) | 458.755 s | 121 | 11 | 0 |
| T4 | Candidate | 6,338,661 (6,338,661 / 0) | 326.415 s | 48 | 1 | 0 |
| T5 | Baseline | 15,032,803 (7,580,688 / 7,452,115) | 472.678 s | 151 | 14 | 0 |
| T5 | Candidate | 9,594,243 (9,471,336 / 0) | 480.698 s | 63 | 2 | 0 |
| T6 | Baseline | 4,431,323 (4,188,140 / 0) | 319.657 s | 46 | 3 | 0 |
| T6 | Candidate | 4,620,350 (4,620,350 / 0) | 338.117 s | 48 | 0 | 0 |

The single stop was a non-ritual baseline statement on T3. The candidate has
zero ritual stops, satisfying that pass-bar criterion.

## Diagnostic content axis

Diagnostic scores remain descriptive and separate from the primary outcome.
No task has complete usable A/B diagnostic triplets, so no registered paired
diagnostic holdout delta exists.

Complete single-arm diagnostic medians under the conservative post-hoc filter
are:

| Task | Arm | Diagnostic median |
|---|---|---:|
| T1 | Ablation | 9.25 |
| T2 | Baseline | 9.00 |
| T3 | Ablation | 8.50 |
| T4 | Candidate | 9.00 |
| T5 | Candidate | 6.75 |

These isolated cells cannot be compared across arms and do not repair any
primary cell. Keeping the internally inconsistent response under either of
its reported values would not create a complete paired A/B cell, so this
sensitivity choice does not change that conclusion.

## Fleet-ablation advisory result

The pre-registered advisory statement "the fleet is not earning its keep"
requires non-inferior quality and evidence plus the efficiency threshold on
**both** designated tasks. T3's complete gate-passed telemetry cell already
fails the condition; T1 is shown only as the inclusive-run descriptive
scenario because one ablation replicate failed the artifact gate:

| Task | Ablation vs candidate tokens | Ablation vs candidate wall time | Status |
|---|---:|---:|---|
| T1 | −1.958% | +13.610% | descriptive; includes one gate-failed run |
| T3 | +54.779% | +44.869% | complete gate-passed cell |

T3 uses more tokens and is slower, so the both-tasks requirement cannot be
satisfied regardless of T1. The experiment therefore does not establish that
the fleet is redundant.
This is not equivalent to proving that the fleet positively earns its keep,
because the quality/evidence non-inferiority cells are incomplete.

## Protocol gap and required decision

The following choices were not pre-registered and cannot be made after
observing outcomes without being labeled post hoc:

1. Whether any candidate or ablation artifact-gate failure is an outright
   arm failure, or whether a separate binary threshold applies.
2. How artifact-gate failures affect task medians and baseline task
   conclusiveness.
3. Whether telemetry from gate-failed final runs belongs in primary
   cost/latency medians. This report follows the existing failed-run
   accounting mechanism but exposes the assumption explicitly.
4. How malformed judge JSON is treated: invalidation, re-judging, or a
   fixed tolerant parser policy.
5. How an internally inconsistent score is treated.
6. Whether a separate diagnostic aggregation rule is wanted. Diagnostic
   values cannot enter the primary pass bar under the registered amendment.

The binding statement for this round is therefore:

> Primary pass not established; formal verdict indeterminate; rollout held.

A clean pass/fail requires the handling rules to be registered before a
fresh sealed holdout round. The current exposed holdout must not be tuned
against or selectively re-run.

## Recommendation

1. Do not roll the candidate out based on this round.
2. Keep the candidate and frozen artifacts unchanged as evidence.
3. Register artifact-failure, judge-schema, and aggregation semantics.
4. Add fail-closed judge-response validation to the future protocol and
   synthetic preflight; do not retrofit it into this round's verdict.
5. Create a fresh atomic seal and rerun the complete schedule after the
   protocol revision.
6. Retain the fleet for the next round: the clean T3 comparison fails the
   ablation efficiency criterion, so the registered both-tasks redundancy
   rule cannot be satisfied.
7. Do not extend the convention to planning, TDD/refactoring, or Codex
   adapters until this pilot produces a valid primary verdict and those
   families pass their own representative gates.

## Reproducibility ledger

| Artifact | SHA-256 |
|---|---|
| Sealed package | `e611ada9427954e34b597e093d7da35acb278d534dbdf54dffef72700a5da95c` |
| Pre-results registered plan snapshot | `71ccede2ea7a8598f56c40b61a4098c001c0920cafa2e1e22419b84804b007ee` |
| Schedule | `810fd3ca96d70ccb4b5a0f813ad212fa155d997a594485873d3f092488b0dc09` |
| Schedule manifest | `b36833a8889f89e031245e36c93c6c4170b84cdfcd60e4738c511b6b14a8e353` |
| Combined 48-record run set | `a54d7c8215a289582f5492e2356d407b0bad6f5dd11fb272494b3730c5674108` |
| Primary scorer manifest | `4677f6c55abf820dea7ca533b1c8ec85a6dda88db6c5e78fc56021613e5e0c72` |
| Primary verifier manifest | `eb5e3346be109a3732d4f41c43d524fe794a38dc060b7b33c156ee24fe5478e7` |
| Diagnostic scorer manifest | `362c18fecbe84b2a60a9549160c841d1f7d076d737b7bca25a7045621ed1d36c` |
| Ordered primary-scorer record set | `639578d867e3234854de2753381f9be4e5e602ee355eee2073b3652fdf8be65e` |
| Ordered primary-verifier record set | `4a95c6d8ea7abba352ab977707e13c05d1cd50ab5e05c024083babb0cc6fcdea` |
| Ordered diagnostic-scorer record set | `6e18ca70ce86bae9a23d9a834d54f891f00e8c06c737b254461cea3d20b401c9` |
| Final runtime lock | `8fa194cc337193f4804b292b0bd3c8fdd4eb333cc82982273492b22e46846e2c` |

Combined-set hashes are SHA-256 over concatenated raw-file SHA-256 digests in
deterministic filename or presentation order. The 48-record run-set hash
includes all 42 final run records plus the six explicitly excluded superseded
infrastructure attempts.

## Post-run harness status

The scoring-transport compatibility hardening is kept separate from the
frozen evaluated runtime. The public harness now adds the CLI-required
`--verbose` flag to the backend command before sandbox wrapping, tests wrapper
flag collisions and idempotence, and documents the actual mock contract. Its
synthetic preflight passes **160/160** capabilities, the documentation
self-test catches all 50 negative fixtures, and full documentation validation
passes.

One newly exposed protocol debt remains intentionally unpatched in this
round: judge responses were accepted when non-empty but not validated against
a pre-registered machine-readable response schema. Adding such a schema is a
future protocol change, not a permissible post-outcome repair.
