---
date: 2026-08-01T20:58:27+02:00
type: tech-debt-sweep
commit: 77ab918
branch: codex/pilot-protocol-v2
previous_sweep: null
metrics:
  total_items: 13
  critical_items: 0
  quick_wins: 7
  resolved_during_sweep: 7
  debt_density: 0.87
  suppression_ratio: 0.0
  doc_coverage: 50
  config_health: 71
  dependency_health: 40
  god_modules_count: 2
  god_modules_severe: 0
  god_modules_high: 0
  god_modules_worst_score: 57.8
---

# Technical Debt Sweep Report

**Date:** 2026-08-01 20:58:27 CEST
**Commit inspected:** `77ab91877a6c0324ea90f014451ff37c6ad118a1` plus the
uncommitted protocol-v2 harness
**Branch:** `codex/pilot-protocol-v2`
**Scope:** the public eval harness and its directly used repository tooling;
the private eval workspace and sealed material were not inspected.

## Executive summary

The scan found one release-blocking configuration defect: protocol-v2 child
processes inherited the operator's complete environment and could therefore
receive unrelated credentials. It was fixed during the sweep with the
`claude-cli-minimal-env-v1` allowlist and a secret-canary preflight. Six other
safe issues were removed at the same time: temporary-directory leaks, a
credential-bearing snapshot-URL shape, three ambiguous lint variables, a
vague debt marker, and protocol-v2 config/documentation drift.

There are 13 consolidated open items after deduplicating overlapping scanner
findings. None blocks the v2 seal once the seal-specific operator registration
is added. The main residual debt is structural: `runner.py`, `preflight.py`,
and `aggregate_results.py` are too large to refactor safely between harness
freeze and the scored round. Their paydown is deliberately sequenced after
the pilot with API snapshots and characterization tests.

Metrics use 14,867 executable Python/shell LOC in scope. Debt density is open
consolidated items per 1,000 LOC. Documentation coverage is 57 documented out
of 114 public-by-naming-convention functions. Suppression ratio counts
whole-file disables (there are none; ten localized suppressions remain).
Configuration health is five passing checks out of seven, and dependency
health is two reproducibility checks out of five; both formulas are recorded
here so future sweeps can compare like with like.

### Pilot-execution follow-up

The pre-schedule real-backend preflight later proved that the artifact parser
was not part of runtime identity: a valid document could pass PyYAML on one
host and fail the stricter dependency-free fallback in the operator image.
The pilot now pins PyYAML `6.0.2`, its wheel SHA-256, and an exact,
deterministically rebuilt `linux/arm64` operator-image digest; config identity
and the fail-before-model gate bind those pins. The failed namespace remains
immutable and a fresh seal is required, so the correction cannot select or
repair an observed holdout outcome. This closes the immediate execution
blocker; publishing the complete operator-image build manifest in-repo stays
as post-pilot dependency-governance work.

## Debt by category

### Dependencies

- No application dependency manifest or lockfile exists. That is acceptable
  for a skills/documentation repository, but the executable tooling still
  relies on undeclared host capabilities.
- The deterministic docs gate pins `pyyaml==6.0.2` and
  `markdown-it-py==3.0.0`, but does not lock hashes or a Python runtime.
- Template CI branches still contain unpinned `ruff` and `pytest-cov`
  installs (`.github/workflows/ci.yml:24,72`). Those branches are dormant in
  this repository because no `pyproject.toml` exists, but they are risky when
  the template is reused.
- `actions/checkout@v4` is a mutable major tag rather than an immutable action
  commit (`.github/workflows/ci.yml`).
- The production harness depends on `git`, util-linux namespace tools, and
  `curl`; readiness is tested, but the dependency set is not represented by a
  machine-readable operator image manifest in this repository.

Recommended verification after dependency policy is introduced:
`pip-audit`, `python3 -m pip list --outdated`, and an immutable-action pin
check. There was no manifest against which a meaningful unused-dependency or
CVE audit could be run during this sweep.

### Code quality

- `runner.score()` (`skills/research-codebase/evals/public/runner.py:3921`)
  is over 1,500 lines with transport, persistence, retry, validation, drift,
  and orchestration responsibilities.
- `preflight.run_preflight()`
  (`skills/research-codebase/evals/public/preflight.py:816`) is over 4,600
  lines and should become capability-focused test groups.
- `aggregate_results.aggregate()`
  (`skills/research-codebase/evals/public/aggregate_results.py:1244`) is
  about 600 lines; `_verify_judge_manifest()` is about 470 lines.
- `runner._validate_v2_attempt_record()` and
  `runner.spawn_judge_session_capped()` remain high-complexity security and
  persistence boundaries. They have strong preflight coverage but need
  smaller pure validators.
- Pre-existing hot spots remain in `validate_artifact.validate()` and
  `step5_operator.validate_config()`.
- There are no actionable TODO/FIXME markers, commented-out production code,
  debugger calls, or whole-file lint disables. The only vague `hacky` marker
  and the three E741 variable names were removed during this sweep.

### Architecture

- `aggregate_results.py` imports 18 `runner` symbols, including private
  `_sealed_snapshot_items` and `_validate_v2_attempt_record`. The deterministic
  domain layer is therefore coupled to a CLI/orchestration module.
- `runner.py` owns config validation, git/worktree and process execution,
  scheduling, judge batching, and CLI dispatch. It grew from roughly 2,983 to
  5,700 lines in protocol v2 and is the principal architecture risk.
- `judge_contract.py` and `seal_package.py` are loaded dynamically by
  `runner.py` but normally by sibling modules, creating duplicate module and
  exception-class identities. Current catches are local, so no active defect
  was found.
- Protocol/retry/aggregation constants are deliberately duplicated across
  runner, seal builder, and aggregator for independent fail-closed checking.
  The ownership rationale should be documented before any centralization.
- The import graph is acyclic; no suspected cycle or >50% dependency magnet
  was found.

### Documentation

Fixed during the sweep:

- The config example now uses effective model `claude-opus-5` on every arm and
  the frozen backend command shape.
- README v2 scorer/verifier commands now include tasks, contexts, seal,
  evidence mappings, all six schedule tasks, and the all-doc selection rule.
- CLI help now identifies diagnostic scoring as v1-only and documents the
  actual drift-report, `--repos`, and multi-mode `--tasks` contracts.
- Aggregate validation now treats the six sealed tasks as a set, so caller
  ordering is no longer an undocumented correctness constraint.

Open documentation debt:

- `step5_operator.py` still represents the completed v1 round. It must be
  registered with the new seal hash and emit the two v2 all-doc judge batches
  after sealing; doing that earlier would require a fake hash.
- 57 of 114 public-by-name functions lack docstrings. Priority targets are
  `runner.run_task`, `build_installs.build`, and
  `validate_artifact.validate`; exhaustive docstring work is not a pilot
  blocker.

### Configuration and security

Fixed during the sweep:

- Protocol-v2 evaluated and judge sessions no longer inherit arbitrary
  ambient environment variables. Required Claude auth, proxy/TLS, locale,
  HOME/PATH, and sandbox inputs are explicit; unrelated canaries are absent.
- Sealed live-source URLs now reject userinfo, query strings, and fragments,
  preventing token-like material from entering seals or error text.
- The config example and plan now record the effective model and environment
  policy consistently.

Open items:

- Version probes, live-source fetches, and model sessions use fragmented
  timeout rules. Dedicated, identity-bound probe/fetch timeouts should replace
  the current 60-second/whole-run mixture.
- Protocol-v2 CLI failures may include private paths in detailed error text.
  A future split should write a mode-0600 private audit record and expose only
  stable public error codes.
- Linux staging assumes writable `/dev/shm`; readiness currently proves it,
  but a validated alternate tmpfs staging root would improve portability.

### God modules

The skill's script-weighted scoring found two candidates. `ns_sandbox.py`
scored 56.0 but was excluded as a cohesive security boundary whose external
commands and OS paths are intrinsic.

| Rank | File | Score | Severity | Recommended split |
|---:|---|---:|---|---|
| 1 | `skills/research-codebase/evals/public/preflight.py` | 57.8 | MEDIUM | fixtures and capability-focused suites behind one coordinator |
| 2 | `skills/research-codebase/evals/public/runner.py` | 51.2 | LOW | config/protocol, execution, scheduling, judge batching; stable façade |

`aggregate_results.py` scores below 40 under script weights but remains an
architecture watchlist item because its verification functions are large.

## Trends

This is the first structured sweep, so no historical comparison is possible.
It establishes the metric baseline for `tech-debt-trends`.

## Top actions

1. Register the v2 seal in `step5_operator.py`, prove the sanitized environment
   on the real backend, and run the frozen pilot.
2. After the pilot, snapshot the runner API and characterize immutable record
   validation before extracting modules.
3. Pin CI/toolchain dependencies and introduce dedicated timeout policy in a
   separately reviewed protocol revision.
