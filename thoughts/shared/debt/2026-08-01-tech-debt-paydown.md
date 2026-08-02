---
date: 2026-08-01T20:58:27+02:00
type: tech-debt-paydown
source_sweep: thoughts/shared/debt/2026-08-01-tech-debt-sweep.md
estimated_effort: 4-6d
auto_fixable_count: 7
---

# Technical Debt Paydown Plan

## Completed safely in this branch

- [x] Restrict protocol-v2 model sessions to the fixed minimal environment
  allowlist and prove unrelated-secret exclusion with a canary.
- [x] Remove `rpa-judge-*` and `rpa-refetch-*` creation leaks from all new
  paths; isolated preflight leaves zero temporary roots.
- [x] Reject query- or fragment-bearing sealed source URLs.
- [x] Correct the effective model and frozen backend command in the config
  example.
- [x] Complete and correct the v2 README/CLI help examples.
- [x] Remove three E741 lint defects and the vague `hacky` debt marker.
- [x] Remove the aggregation-only dependency on caller task ordering.

## Before the scored v2 round

- [x] Preserve the terminally exhausted round unchanged, publish only a
  sanitized invalid-round record, and reset the public seal registration to
  the all-zero sentinel.
- [x] Add policy-bound exact-key prompting and native public structural-output
  guidance while retaining the full strict semantic validator and exactly
  three harness attempts.
- [x] Centralize the complete path-free standard-v2 pilot registration and
  enforce it at direct-runner, atomic-seal, and step-5 boundaries before any
  task read, output mutation, or backend launch.
- [ ] Prove schema parity, malformed-output rejection, retry bounds, argv
  privacy, and stream parser parity in synthetic and real-backend preflights.
  The synthetic side now also proves exact-pin rejection before launch,
  canonical one-shot probe state, pending/tampered receipt refusal, and
  seal/config proof binding. The one-shot real scorer + verifier transport
  probe passed and its receipt/execution digests are registered; the post-seal
  all-arm real-backend preflight remains.
- [ ] Create a replacement seal in an uncontaminated session and return only its
  SHA-256 and six task basenames.
- [ ] Register that exact seal in `step5_operator.py`; replace v1
  primary/diagnostic output with two v2 all-doc batches plus deterministic
  aggregation.
- [ ] Rebuild all three arm installations in the pinned operator image and
  verify the registered hashes.
- [ ] Run the real-backend preflight with an unrelated environment canary and
  verify it is absent inside evaluated and judge processes.
- [ ] Execute a completely new 42-slot randomized schedule; then run scorer,
  verifier, and aggregate sequentially. Reuse nothing from an invalid round.
- [x] Move legacy harness temp roots to a dated folder under the user's Trash
  after validating every exact target; keep the cleanup recoverable.

Estimated effort: 1–2 hours excluding model run time.

## First post-pilot refactor

These steps are intentionally not interleaved with the frozen scored round.

1. Use `api-snapshotter` on `runner.py`; capture direct consumers and CLI
   behavior.
2. Add characterization fixtures for run records, judge attempt chains,
   source drift, and sanitized aggregation.
3. Extract shared errors and pure protocol/config primitives while preserving
   runner re-exports.
4. Extract snapshot verification and judge-attempt validation so
   `aggregate_results.py` no longer imports private runner symbols.
5. Split runner execution, schedule persistence, and judge batching behind a
   compatibility façade.
6. Split preflight into capability-focused modules with a thin
   `run_preflight()` coordinator.
7. Run `refactor-validator`, the full preflight, docs validation, and the
   pinned installation hash reproduction after every phase.

Estimated effort: 3–4 days.

## Next sprint

- [ ] Add a machine-readable operator dependency/toolchain manifest: Python,
  util-linux, git, curl, and exact package/action revisions.
- [ ] Pin GitHub Actions by immutable commit and remove dormant unpinned
  `ruff`/`pytest-cov` template installs.
- [ ] Register separate version-probe and live-source-fetch timeouts in config
  identity.
- [ ] Replace protocol-v2 public CLI exception text with stable error codes and
  a private mode-0600 audit log.
- [ ] Add docstrings to the highest-consumption public functions.
- [ ] Document the ownership boundary between centralized pilot-execution
  pins and policy constants intentionally duplicated by independent
  verifiers.

Estimated effort: 1–2 days.

## Out of scope for the frozen pilot

- Structural decomposition before the scored round.
- Dependency major-version upgrades.
- Retrospective changes to protocol-v1 records or verdicts.
- Any change to the frozen candidate SHA or registered installation trees.
