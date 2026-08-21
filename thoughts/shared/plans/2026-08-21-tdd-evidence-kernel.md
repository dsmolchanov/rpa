---
date: 2026-08-21
type: implementation-plan
scope: /tdd workflow family — evidence kernel (predict → run → grade → persist), bounded recovery capsules, session-log validator, CI wiring
status: ready for implementation
depends_on: docs/conventions.md (v0.2.1) §1, §4, §6, §9
baseline: origin/master 923c6953a13d2b1b7c778c183c9a77bf0b51d985 (PR-A merged; branch feat/tdd-evidence-kernel)
delivery: two PRs — PR-A = Phase 0 (prerequisite, merged first); PR-B = Phases 1–3 rebased on PR-A
---

# TDD Evidence Kernel Implementation Plan

## Overview

Add a narrow, deterministic **evidence kernel** to the `tdd` skill so that every
load-bearing test run in a TDD session is preceded by at least one typed,
falsifiable expectation, executed without a shell, graded claim-by-claim,
persisted with a content-derived receipt id, and bound to the repository
state, TDD phase, and test case it is valid for — before **and** after the
command runs. The session log cites receipts instead of hand-transcribed
commands, and a validator rejects a log whose receipts do not resolve, do not
recompute, do not form a Red → Green → Refactor causal chain per case, whose
export omits or mispairs any attempt, whose dispositions do not cover exactly
the planned cases, or whose cycle state disagrees with the ledger. The same
ledger also generates a bounded, ledger-bound recovery capsule and immutable
snapshot at every TDD phase boundary, so a resumed or compacted session can
recover verified facts, open assumptions, changed state, and the next safe
action without treating a hand-written note as evidence. One evidence run
spans the whole Red → Green → Refactor cycle for a test plan, across sessions
if needed, under a worktree-wide execution lease. A prerequisite PR repairs
the fail-open research preflight and makes the repository's own Python tests
run inside CI jobs that branch protection actually requires.

Origin of the design: the ARC-AGI-3 `arc-skill` harness (predict-before-act,
graded claims, append-only receipts, stale-plan rejection) as reconciled in this
session's three-way critique. The transplanted unit is the **operation
contract**, not the game doctrine:

> Before a significant verification, record the state it is valid for, the
> expected effect, and the invariants that must hold; afterwards persist exact
> evidence; continue only while reality matches the contract.

## Current State Analysis

- The TDD kernel already states the right requirements but leaves enforcement
  and recording to the model:
  - Red must fail for the specified behavior, and infrastructure failures are
    not Red — `plugins/rpa/skills/tdd/SKILL.md:65-73`.
  - Green requires valid Red evidence "either from this session or an
    auditable prior phase" — `plugins/rpa/skills/tdd/SKILL.md:77-78`; the
    workflow accepts explicit `red`, `green`, `refactor` phases
    (`SKILL.md:50-51`), so a cycle legitimately spans sessions.
  - Refactor "may legitimately be `not_applicable`" (`SKILL.md:92-95`), so a
    cycle can complete at Green.
  - The verification profile's `Red causality` and `Green regression` rows name
    a prose runner ("narrow repository test command") and prose evidence
    ("non-zero exit and expected assertion failure") —
    `plugins/rpa/skills/tdd/SKILL.md:144-149`. The `Session artifact` row's
    runner is "compare with `references/session-log-contract.md`" — not
    executable.
  - Scope & authority (`SKILL.md:26-31`) limits writes to "source, tests,
    fixtures, and session artifact" and forbids commit/push unless separately
    authorized; acceptance criterion 5 (`SKILL.md:131-132`) says "Only
    plan-scoped files and the session log are changed".
- The TDD skill's write authority is `workspace_write (plan-scoped source,
  tests, and thoughts/shared/tests session log)` —
  `plugins/rpa/skills/tdd/SKILL.md:12`; `validate_docs.py` enforces the
  `permission-class` grammar (`scripts/validate_docs.py:91-93`, `:226-259`). No
  location under `.git/` is in that authority, and the Codex CLI
  `workspace-write` sandbox (README.md:68-76 documents Codex as a supported
  install) keeps `.git/` read-only, so a store under `git-dir` would force an
  escalation on every evidence run.
- The session log contract fixes the path
  `thoughts/shared/tests/YYYY-MM-DD-TDD-SESSION-description.md`
  (`plugins/rpa/skills/tdd/references/session-log-contract.md:5`), carries a
  `**Test Plan**: `[path]`` header (`:17`), and asks for hand-entered commands
  and exits (`:30-32`, `:37-57`, evidence rules `:69-80`); nothing checks that
  those strings correspond to a run that happened, or that the run happened
  against the state the log describes. The test plan contract's path is
  `thoughts/shared/tests/YYYY-MM-DD-TEST-description.md` with case ids `U-*`,
  `I-*`, `E-*` (`create-test-plan/references/artifact-contract.md:114`).
  `thoughts/shared/tests/` does not exist in this repository at the baseline
  commit, so there are no legacy session logs here to grandfather.
- The TDD kernel has explicit Baseline, Red, Green, Refactor, and Completion
  boundaries (`plugins/rpa/skills/tdd/SKILL.md:48-111`), while the session log
  is one continuing artifact (`session-log-contract.md:5-9`, "Resume the same
  log for continuation of the same cycle"). Neither contract produces a
  bounded recovery view at those boundaries; after context compaction the
  agent must reconstruct verified facts, invalidated assumptions, and the next
  action from prose plus command history.
- The test plan contract's Red-phase tables carry a prose "Expected observable
  result" column (`plugins/rpa/skills/create-test-plan/references/artifact-contract.md:50-68`);
  there is no typed expectation a tool can grade.
- `docs/conventions.md` §4 (`docs/conventions.md:128-143`) requires every gate
  to have an executable runner that returns `passed|failed|not_applicable`
  with evidence, and §1 (`docs/conventions.md:34`) places deterministic
  operations under `skills/<workflow>/scripts/`. §9 (`docs/conventions.md:206-213`)
  requires each grammar/schema to be defined once.
- An executable-gate binding pattern already exists: `scripts/validate_docs.py:484-603`
  (`check_artifact_validator`) runs the research artifact validator against
  positive/negative fixtures so that a validator that accepts everything fails
  the docs gate; `validate()` wires checks at `scripts/validate_docs.py:605-613`.
  It binds the validator to **fixtures only** — it does not discover and
  validate real artifacts, so a committed artifact that was never validated is
  invisible to CI. The self-test (`scripts/validate_docs.py:614-652`) runs
  `validate()` on `tests/fixtures/docs-validate/positive` (must be clean) and
  on each `negative/<case>/` (must produce an error containing the case's
  `EXPECTED` text); fixture roots hold `agents/ commands/ skills/` at their
  root and `plugin_root()` falls back to the root (`:72-74`). Any check that
  returns not-applicable in every fixture root has no permanent test.
- The hook gate runner's tests are plain `unittest` driven by `subprocess`
  (`plugins/rpa/hooks/test_run_gate.py:1-40`, `76-77`); they are documented as
  `python3 hooks/test_run_gate.py` (`plugins/rpa/hooks/README.md:34-38`).
- CI (`.github/workflows/ci.yml`) runs template jobs keyed on `package.json` /
  `pyproject.toml`; the repo root has neither, so `lint`/`unit`/`integration`/
  `e2e`/`coverage` are effective no-ops (`.github/workflows/ci.yml:27-37`,
  `:39-49`). The file's own header says the job keys must match the
  required-status-check names and that per-repo commands are tuned "without
  renaming the jobs" (`.github/workflows/ci.yml:8-12`). Only `docs-validate`
  (`.github/workflows/ci.yml:77-86`) runs real checks.
- Branch protection on `master` (read via `gh api …/branches/master/protection/required_status_checks`
  on 2026-08-21) requires exactly `lint`, `unit`, `integration`, `e2e`,
  `coverage`, `codex-review-window`, strict mode on. `docs-validate` is **not**
  required. The contexts list is owned by the `plaintalk-dev-agent` bootstrap
  (`scripts/bootstrap-dsmolchanov-repo.sh:206`, `OUR_CONTEXTS`), which re-asserts
  it on every onboarding run — a repo-local change to branch protection would be
  overwritten and is outside this plan's authority. Consequence: any check that
  must gate merge has to run inside one of those five CI job names.
- The research eval preflight is fail-open in practice: `HERE` is the
  `evals/public` directory (`preflight.py:23`, `Path(__file__).parent`) and the
  check at `preflight.py:5999-6015` reads `HERE.parents[3] / "commands" /
  "research_codebase.md"`, a file removed in commit `5f10550` ("Remove legacy
  commands superseded by workflow skills"). `python3 runner.py --preflight`
  crashes with `FileNotFoundError` after ~24 s (measured 2026-08-21). The
  README advertises the preflight as the offline proof of every capability
  (`evals/public/README.md:84-90`) and does not name the individual check, so
  renaming it has no documentation consumer. From `HERE`, the skill root is
  `HERE.parents[1]` (`evals` → `research-codebase`).
- Plugin version is `2.0.0` in both manifests
  (`plugins/rpa/.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json:12`);
  `validate_docs.py` enforces semver on the plugin manifest
  (`scripts/validate_docs.py:278-316`).
- `.gitignore` ignores `.DS_Store`, `.claude/`, `__pycache__/`, `*.pyc` only.
- Both install layouts ship the skill package directory verbatim
  (`README.md:59-66` plugin install for Claude Code and Codex, `README.md:78-105`
  manual copy of `plugins/rpa/skills/*`), so `scripts/evidence.py` is always a
  sibling of the `SKILL.md` that was loaded.

## Desired End State

1. `python3 <skill-dir>/scripts/evidence.py {begin,run,status,checkpoint,export}`
   exists, is stdlib-only, relocatable with its skill package, and:
   - `run` requires `--phase`, `--case` (for `red`/`green`/`refactor`), at
     least one machine-checkable `--expect`, and for `red` the `red_inputs`
     and `plan` scopes; admits only the phases the run's state machine allows;
     refuses a `--requires` target that is not a `PASS` receipt of the
     expected phase for the same case; refuses to execute when the inherited
     freshness envelope (own + ancestral scopes, `HEAD`, branch, plan) is
     stale; executes the command as an argv list (never via a shell, never
     holding the store lock while the command runs) under a worktree-wide
     execution lease; writes an fsynced, already-sanitised intent record
     before the subprocess and exactly one terminal record after it;
     re-checks the envelope after the command and records drift as `STALE`;
     bounds output by streaming digest + ring-buffer tail; enforces a timeout
     on the whole process group; grades each claim independently; and appends
     the terminal record with a content-derived receipt id to an append-only
     store under `<repo root>/.rpa/evidence/`.
   - `status` reconstructs and prints the current bounded recovery capsule from
     the ledger: run and phase, verified receipt-backed claims per case,
     surprises, open/blocked/not-applicable items, unrecovered intents, state
     drift, and the next safe action — bound to a ledger hash.
   - `checkpoint` records a monotonic (non-decreasing) phase transition as a
     recoverable two-step transaction (snapshot, then record), writes an
     immutable ledger-hash-bound snapshot plus a derived `current.md`, and
     demotes evidence whose envelope is stale from `Verified` to `Open`.
     `checkpoint final --achieved <phase>` is the last record of a run; the
     run's `state`/`achieved` are derived from the ledger, never stored
     authoritatively.
   - `export` writes the **complete** verbatim ledger and ordered capsule
     snapshots of an open or sealed run under `thoughts/shared/tests/receipts/`;
     a later export of the same run may only extend the previous one.
   - `run`, `checkpoint`, and `export` fail closed while any execution in the
     same worktree holds a live lease, and repair the store idempotently first.
2. The claim grammar, freshness envelope, outcomes, record model and pairing
   rules, lease/recovery/checkpoint protocols, phase machine, store layout,
   sanitisation, containment rules, capsule rules, and export schema are
   defined once in `plugins/rpa/skills/tdd/references/evidence-contract.md`.
3. `python3 <skill-dir>/scripts/validate_session_log.py <log>` rejects a
   session log whose layout, headers, or export path deviate from the
   contract; whose receipts do not resolve or recompute; whose export has gaps,
   unpaired or duplicated records, or uncited attempts; whose phase attempts
   are not closed by checkpoints; whose dispositions do not cover exactly the
   planned cases of the bound test plan; whose Green/Refactor receipts do not
   chain causally to a `PASS` Red/Green of the same case; or whose cycle state
   disagrees with the ledger. `scripts/validate_docs.py` self-tests that
   validator against skill fixtures, runs it against every TDD session log
   committed under `thoughts/shared/tests/` (discovered by file name and by
   H1), fails on an orphan export, and has **permanent** self-test fixture
   roots for every branch of that discovery.
4. The `tdd` kernel's `Red causality`, `Green regression`, `Recovery capsule`,
   `Evidence export`, and `Session artifact` gate rows name those executable
   runners; its `permission-class`, scope/authority text, and acceptance
   criterion 5 name the local store and the committed export; the test-plan
   contract carries a typed claim per Red-phase case; the session-log contract
   cites receipts and checkpoints and carries schema marker and cycle state.
5. The required `unit` CI job runs `hooks/test_run_gate.py`, the evidence and
   validator tests, and `validate_docs.py`; the required `integration` job runs
   `runner.py --preflight`; both pass on `master`. No branch-protection change.

Recognizable by: all commands in the **Automated Verification** lists below
exit 0 on the branch; a TDD session log that fabricates a Red receipt, cites a
Green receipt whose `requires` is not a `PASS` Red of the same case, tampers
with, trims, or mispairs an exported ledger, covers one of ten planned cases,
binds to a different test plan, or claims `complete` on an open run fails
`validate_session_log.py` locally and fails the `unit` job in CI; and every
generated capsule is at most 120 physical lines and 16 KiB.

### Key Discoveries

- Gate binding pattern to mirror: `scripts/validate_docs.py:484-603` — the
  validator must accept the valid fixture and reject each invalid fixture; a
  missing fixture is itself an error. Extend, do not copy: the new check also
  discovers real logs and runs the validator on each, and the discovery itself
  is exercised by permanent `tests/fixtures/docs-validate/` roots.
- Test style to mirror: `plugins/rpa/hooks/test_run_gate.py` — `unittest`,
  `subprocess.run([sys.executable, script, ...])`, temp dirs, no network.
- Hook runner reporting contract to mirror for `status`/`run` output:
  `gate=<name> outcome=<passed|failed|not_applicable> reason=<…>`
  (`plugins/rpa/hooks/run_gate.py:19-22`).
- Red cause must be distinguished from infrastructure failure
  (`plugins/rpa/skills/tdd/SKILL.md:65-70`) — therefore `exit != 0` alone can
  never be the Red claim; the grammar needs `test <selector> fail-with
  "<literal>"`, `<error>` (infrastructure) must never satisfy it, and a
  stand-in (no JUnit) must pair `exit != 0` with a cause-specific output
  literal.
- Green necessarily changes the worktree, so Red-receipt freshness must be
  scoped to the Red inputs (tests, fixtures, helpers, test config, lockfiles)
  and the plan, not the whole worktree; otherwise every Red receipt is stale by
  the time Green runs. The scopes must be re-computable from the stored
  record, mandatory for Red, inherited as a **union** down the `requires`
  chain, and re-checked after the command as well as before.
- The child PID does not exist before `Popen`, so a durable "about to run"
  record cannot carry it; durability and liveness are two different facts —
  an intent record in the ledger and a lease keyed on the **controller**
  (`evidence.py`) process, written before `Popen`.
- Concurrent mutation is a property of the worktree, not of a run: two runs
  on one checkout would race on the same files, so the execution lease is one
  per store, not one per run.
- The workflow already has the phase boundaries needed for deterministic
  checkpoints (`plugins/rpa/skills/tdd/SKILL.md:48-111`). The capsule can
  therefore be a generated projection of the ledger, not a second editable
  task-memory artifact; likewise `run.json` is a derived index of the ledger.
- Generated artifacts (`__pycache__`, `.pytest_cache`, coverage files) must not
  trip "command changed no files"; the diff checks are gitignore-aware by
  construction (`git status --porcelain`). A directory that contains a
  `.gitignore` holding `*` is ignored in full by git without touching the
  repository's own `.gitignore` (the `.mypy_cache`/`.ruff_cache` pattern) —
  placed **inside** `.rpa/evidence/`, it stays within the authority boundary
  and hides nothing else under `.rpa/`.
- The preflight check at `preflight.py:5999-6015` verified that a *command
  wrapper* embedded the kernel in both install layouts; with wrappers removed,
  both install paths ship the skill package itself
  (`README.md:59-66`, `README.md:102-103`), so the check's replacement verifies
  the skill package is self-contained (SKILL.md + references/artifact-contract.md
  present) rather than deleting the capability row.
- The CI template explicitly invites per-repo commands inside the existing job
  keys (`.github/workflows/ci.yml:8-12`); the required gate must therefore be
  the `unit`/`integration` jobs, not new job names, because the required
  contexts are asserted by `plaintalk-dev-agent`'s bootstrap
  (`scripts/bootstrap-dsmolchanov-repo.sh:206`).
- Session logs, test plans, and exports all live under `thoughts/shared/tests/`
  (`session-log-contract.md:5`, test-plan contract path, `receipts/`
  subdirectory), so the validator can require one exact layout — log at
  `<root>/thoughts/shared/tests/<name>.md`, export at
  `<root>/thoughts/shared/tests/receipts/<run-id>.json`, plan at the
  repo-relative `**Test Plan**` path — and fixtures can be mini repo roots.

## What We're NOT Doing

- No universal `rpa run` ledger, no workflow registry or semantic validator, no
  `implement-plan`/`refactor`/`validate-plan` integration (later plan, after
  real TDD sessions).
- No Claude Code hook that forces test commands through `evidence.py`; the loop
  is closed at the artifact gate: unresolvable, non-recomputing, mis-chained,
  incomplete, or mis-stated receipts fail the log validator, and CI runs the
  validator on every committed log in this repository.
- No remote attestation. A receipt proves that a record is internally
  consistent and that it was produced by the tool on the checkout it names
  (raw-stream digests, report digest, pre/post worktree digests); it does not
  prove *who* ran it or that the machine was honest. Fabrication resistance
  comes from the ledger being complete, contiguous, correctly paired, and
  cross-checked by the validator, not from cryptography.
- No SQLite, no schema migrations, no multi-writer concurrency support; the
  store is single-writer JSONL with a portable file lock held only around
  ledger mutations, one worktree-wide execution lease, and atomic index
  replacement.
- No nudge thresholds, no batching/`commit` command, no ARC perception/A*/rules
  tiers. The generated capsule is a bounded recovery projection and does not
  replace the full session log, a cross-session handoff, or the receipt ledger;
  there is no free-form hand-maintained `NOTES.md`.
- No parsing of terminal output for per-test results; per-test claims require a
  JUnit XML report. No dependency installation of any kind.
- No retroactive validation of session logs in **other** repositories, and no
  CI wiring for other repositories; in this repository there are no legacy logs
  (`thoughts/shared/tests/` is absent at baseline), so every committed TDD
  session log must validate.
- No renaming of the CI template jobs and no change to branch protection (the
  contexts are owned by `plaintalk-dev-agent`'s bootstrap). Real steps are
  added **inside** the required `unit` and `integration` jobs; `lint`, `e2e`,
  `coverage`, and `docs-validate` are left unchanged. No changes to
  `AGENTS.md` or `CODEOWNERS`.
- No Codex wrapper clean-up; `evidence.py` is agent-agnostic and needs none.
- No full secret-scanning engine: sanitisation is the documented pattern set,
  applied before any persistence; raw unbounded output is never persisted
  anywhere.
- No Windows CI job; Windows support is limited to not depending on `fcntl`
  and not using `os.killpg` (documented fallback), verified only by code review.
- No `git commit` by the implementer as part of any verification step in this
  plan (`SKILL.md:31`); drift scenarios are exercised in throwaway repositories
  created by the tests or in the scratch directory.
- No in-repository override of the store location: `RPA_EVIDENCE_DIR` may
  only point outside the repository.

## Implementation Approach

One vertical slice owned by the `tdd` skill package, per `docs/conventions.md`
§1: deterministic operations in `skills/tdd/scripts/`, the grammar/schema in
`skills/tdd/references/evidence-contract.md` (single source, §9), the
requirement in `SKILL.md` gate rows, the binding in `scripts/validate_docs.py`
and CI (§4). Delivery is two PRs: **PR-A** carries Phase 0 alone (preflight
repair + required-job wiring — a separate subsystem and a slow gate, merged
first so that everything in PR-B is observed by required checks); **PR-B**
carries Phases 1–3, rebased on the merged PR-A. Within PR-B the phases are
ordered so each is independently verifiable: kernel, then the validator that
closes the loop, then the contract/kernel edits that make the workflow use it.

Design decisions fixed by this plan (implementer does not re-decide), grouped
as **state machine / WAL**, **provenance / phase causality**, **validator
completeness** (Phase 2), and **authority / security**.

### Store, authority, and security

- **Store location and visibility**: `<repo root>/.rpa/evidence/` (per
  worktree because each worktree has its own root). `begin` creates
  `.rpa/evidence/` and writes `.rpa/evidence/.gitignore` containing exactly
  `*` — **inside** the authority path, so nothing else under `.rpa/` is
  touched or hidden; if that file already exists with different content,
  `begin` exits 2 (foreign config, never overwritten). As defense in depth
  every status/scope/diff computation in `evidence.py` drops paths under the
  store root. `RPA_EVIDENCE_DIR` overrides the location only when its
  realpath is **outside** the repo root (not the root, not an ancestor, not
  a descendant — exit 2 otherwise), so an override can never blind the diff
  or scope computations. Rationale: the TDD authority is `workspace_write`
  over the checkout (`SKILL.md:12`), and `.git/` is read-only under the
  Codex `workspace-write` sandbox. Layout: `runs/<run-id>/events.jsonl`
  (append-only records — the only authoritative state), `runs/<run-id>/run.json`
  (derived index, atomic replace, rebuildable from the ledger),
  `runs/<run-id>/reports/` (run-owned scratch for JUnit reports),
  `runs/<run-id>/capsules/` (snapshots + derived `current.md`), `current`
  (text file naming the active run id), `lock`, `active.json` (the
  worktree-wide execution lease, present only while an execution is in
  flight).
- **Identifier containment**: run ids match
  `^tdd-\d{8}-\d{6}-[0-9a-f]{8}-[0-9a-f]{6}$`; `--resume <id>`, the content of
  `current`, and every `runs/<id>` path are validated against that regex and
  `store_paths()` asserts the resolved path is inside the store root before
  any I/O (exit 2 otherwise). Event refs match `^<run-id>#[1-9]\d*$`.
- **Path containment**: `--report`, `--out`, `path <p>` claims, `--scope`
  globs, and `--plan` are resolved with `os.path.realpath` and must lie inside
  the repo root (after symlink resolution); anything else is a usage error
  (exit 2).
- **Sanitisation before any persistence**: `redact(text)` is applied to every
  string **before** it is written anywhere — the intent record is built from
  already-sanitised `argv`, `cwd`, `because`, claim texts, `report_path`;
  the raw argv exists only in memory for `Popen`; tails, claim details, and
  capsule text are sanitised before write. Pattern set (single definition in
  the evidence contract): key/value `(?i)(api[_-]?key|token|secret|password|
  passwd|pwd)\s*[=:]\s*\S+`; split-form `(?i)(--?(api[_-]?key|token|secret|
  password|passwd|pwd))\s+\S+` → `\1 [REDACTED]` (applied across adjacent
  argv elements, so `--password hunter2` redacts the following element);
  `Bearer\s+\S+`; `sk-[A-Za-z0-9_-]{10,}`; `gh[pousr]_[A-Za-z0-9]{20,}`;
  `AKIA[0-9A-Z]{16}` → `[REDACTED]`. Raw streams are never persisted; their
  integrity is preserved as `stdout_sha256`/`stderr_sha256` over the raw
  bytes plus byte counts.
- **Reports**: `--report <name-or-path>`. A bare name (no path separator)
  resolves to `<store>/runs/<run-id>/reports/<name>` — the run-owned scratch
  space — and the literal substring `{report}` is replaced by that absolute
  path **inside every argv element** (so `--junitxml={report}`,
  `--outputFile={report}`, and a bare `{report}` element all work; the
  substring cannot otherwise legitimately appear in an argv). An explicit
  path elsewhere is accepted only if it is contained in the repo root **and**
  either does not exist or is listed in `run.json.reports[]` (produced by an
  earlier execution of this run); a path that is tracked by git (`git
  ls-files --error-unmatch`) or exists without being run-owned is a usage
  error (exit 2) — `run` never deletes a file it did not create. Pre-existing
  run-owned reports are deleted before execution; a missing report afterwards
  is `ERROR` "report not produced by this run"; `report_sha256` is recorded.
- **Execution**: `subprocess.Popen(argv, shell=False, cwd=<repo root>,
  env=os.environ, stdin=DEVNULL, stdout=PIPE, stderr=PIPE,
  start_new_session=True)`; two reader threads consume the pipes, each
  maintaining a streaming sha256, a byte count, a bounded ring tail
  (`--tail-bytes`, default 8192), and incremental matching for `stdout|stderr
  contains` claims over the **full** stream (carry an overlap of
  `len(literal)-1` bytes across chunks). Everything after `--` is the argv; no
  tokenization of a string command; the only substitution is `{report}`.
  `--timeout <seconds>` (default 900): on expiry send `SIGTERM` to the
  process group (`os.killpg`), `SIGKILL` after 5 s, record `timeout`
  (`outcome: TIMEOUT`, exit 4). `KeyboardInterrupt` kills the group and
  records `interrupted` (exit 130). On Windows, fall back to `proc.kill()` and
  record `detail: "process-group kill unavailable"`.

### State machine and WAL

- **Locking**: one `store_lock()` context manager — `fcntl.flock` on POSIX,
  `msvcrt.locking` on Windows — held only around ledger mutations (repair,
  allocating `n`, appending records, replacing `run.json`, writing lease and
  capsules), never across the subprocess.
- **Worktree-wide execution lease**: `<store>/active.json` = `{"run_id",
  "ref", "controller_pid", "start_token", "started_at_utc", "child_pid"}`.
  Written under the lock **before** `Popen` with `controller_pid` =
  `os.getpid()` of the `evidence.py` process and a fresh `start_token`
  (`secrets.token_hex(8)`), then atomically rewritten with `child_pid` right
  after `Popen`. Liveness is defined by the **controller**: the lease is live
  iff `controller_pid` is alive (`os.kill(pid, 0)`; Windows `OpenProcess`);
  `child_pid` is informational (used for group kill on recovery when the
  controller is dead and the child alive). While a live lease exists — for
  **any** run — `run`, `checkpoint`, and `export` on every run in this store
  exit 2 (`execution in progress: <ref>`). A dead lease is repaired (below)
  before the command proceeds. The lease is removed under the lock together
  with the terminal record.
- **Run identity and lifecycle**: run id
  `tdd-YYYYMMDD-HHMMSS-<first 8 hex of plan sha256>-<6 hex from secrets.token_hex(3)>`.
  One run covers one test plan's whole Red → Green → Refactor cycle and may
  span several sessions: `begin --plan <path>` creates a new run and points
  `current` at it; `begin --resume <run-id>` resumes a run whose derived
  state is `open`, whose `plan_sha256` equals the current plan's, and whose
  `branch` equals the current branch (`git rev-parse --abbrev-ref HEAD`),
  otherwise exit 2. A later session learns the run id from the session log's
  `**Evidence run**` header. `run.json` is a **derived index** holding `id`,
  `nonce`, `plan_path`, `plan_sha256`, `branch`, `head`, `started_at`,
  `reports[]`, plus `state: open|sealed`, `achieved`, `sealed_at`, `phase`
  (current phase-machine state) — the last four are recomputed from the
  ledger by `rebuild_index()` at every repair and never trusted over it.
- **Record model** (`events.jsonl`, one JSON object per line; every record has
  `ref` = `<run-id>#<n>`, `kind`, `at_utc`; `n` is contiguous from 1). Each
  `n` is **exactly one** of: (1) one `checkpoint` record; or (2) one intent
  record `kind: started` followed — at any later line, with the same `ref` —
  by exactly one terminal record of `kind` `finished | error | interrupted |
  timeout`. The intent carries `phase`, `case`, `workflow`, `because`,
  `risk`, sanitised `argv`, `cwd`, `claims[].text`, `scopes`, `envelope`
  (the full inherited freshness envelope, below), `requires`, `report_path`,
  `timeout`, `start_token`, `at` {`head`, `branch`, `plan_sha256`,
  `worktree_digest`}; the terminal record repeats every intent field
  verbatim (the validator compares them) and adds `controller_pid`,
  `child_pid`, `exit`, `started_at`, `finished_at`, `stdout_sha256`,
  `stdout_bytes`, `stdout_tail`, `stderr_sha256`, `stderr_bytes`,
  `stderr_tail`, `report_sha256`, `post_at` {same shape as `at`},
  `claims[]` {`text`, `kind`, `outcome`, `detail`}, `outcome`, `receipt`.
  `checkpoint` records carry `phase`, `achieved` (final only), `at`,
  `ledger_head`, `ledger_sha256`, `capsule_path`, `capsule_sha256`,
  `verified[]`, `open[]`, `blocked[]`, `not_applicable[]`, `next`, and their
  own `receipt` (same hash rule as terminal records), so the last checkpoint
  is covered by its own receipt even though `ledger_sha256` covers only the
  records before it.
- **Receipt id**: `sha256(canonical JSON of the record without the receipt
  field)[:12]`, computed over sanitised content, cited in logs as
  `receipt <hex12>`; the validator recomputes it for every terminal and
  checkpoint record.
- **Repair protocol** (idempotent; runs under the lock as the first step of
  every mutating command and never appends when the ledger is already
  consistent): (1) truncate a trailing partial line; (2) if `active.json`
  exists: when its controller is alive → stop here and fail closed (exit 2);
  when dead → if the ledger already has a terminal record for its `ref`, just
  delete the lease; otherwise kill `child_pid`'s group if alive, append an
  `interrupted` terminal record for that `ref` (`outcome: INTERRUPTED`,
  `exit: null`, `recovered_by: {"command": <run|checkpoint|export>,
  "at_utc"}`), and delete the lease; (3) any intent without a terminal record
  and without a matching lease → append the same `interrupted` record; (4)
  any `capsules/*.md` snapshot with no checkpoint record naming it → delete;
  (5) `rebuild_index()` → `run.json` (`state` = `sealed` iff a `checkpoint
  final` record exists; `achieved` from it; `phase` = phase of the last
  checkpoint or `none`); regenerate `capsules/current.md` from the last
  checkpoint record's snapshot. `status` is read-only and reports what repair
  *would* do (`open` intents, dead lease, orphan snapshot, index mismatch).
- **Phase machine**: the run's state is the phase of its last checkpoint
  (`none` before the first). Allowed `run --phase` by state: `none` →
  `baseline`; `baseline` → `baseline|red`; `red` → `red|green`; `green` →
  `green|refactor`; `refactor` → `refactor`; `final` → nothing (sealed).
  `checkpoint <phase>` is allowed when `phase` is the current state or its
  successor in `baseline < red < green < refactor < final` (non-decreasing,
  so a re-run Red after `checkpoint red` is closed by another `checkpoint
  red`). Invariant: for every phase P with at least one terminal record, the
  last `checkpoint P` has a larger `n` than every P attempt; `checkpoint
  final` is the last record of the run — no record may follow it. Violations
  are usage errors (exit 2) at write time and check (l) in the validator.
- **Checkpoint transaction** (`checkpoint <phase> [--achieved …] [--next
  "<action>"] [--open "<item>"]… [--blocked "<item>"]… [--not-applicable
  "<item>"]…`): under the lock, after repair and envelope check: (1) build the
  capsule text from the ledger; (2) write `capsules/<nn>-<phase>.md.tmp`,
  fsync, rename to `capsules/<nn>-<phase>.md` (immutable); (3) append the
  checkpoint record carrying `capsule_path`, `capsule_sha256`, `ledger_head`
  (the last `n` before it) and `ledger_sha256` (over records `1..ledger_head`)
  — this append is the commit point; (4) `rebuild_index()` and regenerate
  `current.md`. A crash after (2) leaves an orphan snapshot → repair deletes
  it; after (3) → repair rebuilds index and `current.md`. Nothing is stored
  in `run.json` that repair cannot recompute.
- **Capsule**: sections, in order: Run/Phase (id, branch, head, ledger_head,
  ledger_sha256); Verified (receipt-backed `PASS` claims per case whose
  envelope is still fresh); Open (stale-envelope, `PENDING`, and `--open`
  items); Blocked (`--blocked` items plus cases whose last terminal record is
  `ERROR`/`TIMEOUT`/`INTERRUPTED`); Not applicable (`--not-applicable`
  items); Surprises; State drift (`HEAD`, branch, plan, dirty paths); Next
  (`--next`, or derived: "re-run Red for <case>" when stale, "run Green for
  <case>" when Red verified and no Green, etc.). ≤ 120 physical lines and
  ≤ 16 KiB, truncated oldest-first with a `[+N older]` marker. `status`
  prints the same projection live and flags when `current.md` does not match
  the last checkpoint's `capsule_sha256`.
- **Export**: `export [--out <path>]` is allowed for `open` and `sealed` runs
  (a Red-only session must still commit its evidence); after repair and
  envelope check it writes canonical JSON (`sort_keys`, fixed separators,
  `\n` line endings) with `{"schema": 1, "run": {<derived index>},
  "exported_at", "records_through": <last n>, "events": [<all records 1..n
  verbatim>], "capsules": [{"phase", "path", "text", "sha256"}]}`; default
  path `thoughts/shared/tests/receipts/<run-id>.json`. Immutability by
  prefix: if the target exists, its `events` must be a strict prefix (or
  equal) of the new ledger and its `capsules` a prefix of the new ones,
  otherwise exit 2 without writing; equal content → exit 0 unchanged. The
  export is always the whole ledger; no transformation happens at export.

### Provenance and phase causality

- **Required run inputs**: `--phase baseline|red|green|refactor|final`
  (required and admitted by the phase machine), `--case <id>` (required for
  `red`/`green`/`refactor`, optional otherwise), `--workflow tdd` (default,
  recorded), `--because "<why>"`, **at least one machine-checkable
  `--expect`** (a run whose only claims are `manual` or that has no `--expect`
  exits 2 before any write — there is no vacuous `PASS`), and for `--phase
  red` both `--scope red_inputs=<globs>` and `--scope plan=<test-plan path>`
  (exit 2 otherwise).
- **Claim grammar v1** (each claim graded independently; outcome per claim is
  `PASS | SURPRISE | STALE | ERROR | PENDING`; run outcome is the worst; claims
  are not graded on `TIMEOUT`/`INTERRUPTED`):
  - `exit == <N>` · `exit != 0`
  - `stdout contains "<literal>"` · `stderr contains "<literal>"` — over the
    full stream, not the tail.
  - `diff none` · `diff within <glob>[,<glob>…]` — pre- and post-run
    snapshots are maps `path → sha256(content) | "deleted"` over the **union**
    of paths listed by `git status --porcelain=v1 -z --untracked-files=all`
    before and after (store root excluded); a path counts as changed when its
    hash differs or it appears/disappears, so modifying an already-dirty file
    is detected. `within` passes when every changed path fnmatches a glob
    against repo-relative paths.
  - `path <repo-relative> unchanged|created|absent` — sha256 before/after;
    the path must be contained.
  - `test <selector> pass` · `test <selector> fail-with "<literal>"` —
    requires `--report`. `<selector>` is a case-sensitive substring of
    `<classname>.<name>`; **exactly one** `<testcase>` must match (zero or
    several → `ERROR`, detail names the matches). `pass` passes only when
    `exit == 0` **and** the matched testcase has no `<failure>`, `<error>`, or
    `<skipped>` child. `fail-with` passes only when `exit != 0` **and** the
    matched testcase has a `<failure>` (not `<error>`) whose `message` or text
    contains the literal. The bare `test <selector> fail` form does not exist
    — it cannot distinguish wrong-cause failure.
  - `manual "<observable>"` → always `PENDING`; never `PASS`; never counts as
    the required machine-checkable claim.
  - Free text is not a claim; an unparseable `--expect` is a usage error (exit
    2) and nothing runs.
  - **Stand-in rule** (no JUnit available): a Red stand-in is the pair
    `exit != 0` **and** `stdout|stderr contains "<cause literal>"` where the
    literal names the expected assertion/cause and the test plan row marks the
    case `stand-in`; a Green stand-in is `exit == 0` plus the plan's named
    success literal if any. `exit != 0` alone is never Red.
- **Freshness envelope**: `begin` records `head`, `branch`, `plan_sha256`.
  Each `run` records `at` {`head`, `branch`, `plan_sha256`,
  `worktree_digest`} and, for every `--scope <name>=<glob,…>`, `scopes[name]
  = {"globs": [normalized, sorted], "paths": <count>, "digest": sha256 over
  sorted repo-relative matching paths + content hashes}`. A scope that
  matches zero files is `ERROR` (exit 2, nothing runs). The record's
  **envelope** is the union of its own scopes and the envelopes of its
  `requires` chain (a descendant never narrows an ancestor's scopes) plus
  `head`, `branch`, `plan_sha256`; it is stored in the intent as `envelope`
  so the validator and later runs recompute it from the record alone.
  `--requires <event-ref>` (one target) makes `run` validate the target
  first: it must exist in the same run, be a terminal record with `outcome:
  PASS`, have a smaller `n`, carry the same `case`, and have the phase the
  causal chain expects (`green` requires `red`; `refactor` requires `green`
  or `refactor`; any other combination or a `PENDING`/`SURPRISE`/`STALE`/
  `ERROR` target is a usage error, exit 2, nothing runs). **Before** the
  command, the envelope is recomputed: any scope digest difference, `HEAD`
  drift, branch change, or plan change → the run is recorded with outcome
  `STALE`, the command is **not** executed, exit 3. **After** the command,
  the envelope is recomputed again (`post_at`, post scope digests): any
  difference → outcome `STALE` with detail `drift during execution` (the
  command mutated its own inputs), exit 3 — a PASS can only be recorded when
  the envelope is identical before and after. `checkpoint` and `export` also
  refuse (exit 2) when branch or plan sha differ from the run's, and record
  `HEAD` drift as State drift. TDD convention (in the evidence contract):
  `red_inputs` covers the test files executed, their fixtures/helpers, the
  test-runner config (e.g. `pytest.ini`, `pyproject.toml`, `jest.config.*`,
  `vitest.config.*`), and lockfiles; Green runs pass `--requires <Red ref>`
  and may add scopes; Refactor runs pass `--requires <Green ref>`.
- **Exit codes** (`run`): 0 all claims `PASS`/`PENDING` with at least one
  `PASS`; 1 any `SURPRISE`; 2 `ERROR` (usage, no machine-checkable claim,
  unparseable claim, missing mandatory Red scopes, empty scope, phase not
  admitted, bad `--requires` target, containment or identifier violation,
  report rule violation, missing/ambiguous report, command could not start,
  sealed run, execution in progress, branch/plan mismatch); 3 `STALE` (pre- or
  post-run); 4 `TIMEOUT`; 130 `INTERRUPTED`. `status`, `checkpoint` and
  `export` exit 0 on success, 2 on usage/store error/execution in progress.
- **Risk field**: `--risk local_verify|local_mutate` (default `local_verify`),
  recorded for audit only; it grants nothing.
- **Tooling compatibility note** (goes in the evidence contract): pytest emits
  JUnit via `--junitxml={report}`; Jest via the `jest-junit` reporter
  (`JEST_JUNIT_OUTPUT_FILE` is an env var — pass `-- env JEST_JUNIT_OUTPUT_FILE={report} npx jest …`
  or configure the reporter path to `{report}`); Vitest via `--reporter=junit
  --outputFile={report}`; Python `unittest` has no built-in JUnit writer — use
  pytest to run unittest cases, or declare the stand-in claim pair in the test
  plan and say so in the session log; same for `cargo test`, `go test`.
- **Locating the tool after install**: `<skill-dir>` is the directory that
  contains the `SKILL.md` the agent loaded (plugin cache, `~/.claude/skills/tdd`,
  or the Codex plugin dir — all ship the package verbatim); the tool is always
  `<skill-dir>/scripts/evidence.py` and imports nothing outside its own
  directory. `SKILL.md` states this rule once; EV-23 proves relocatability.

## Phase 0: Baseline repair and required-job CI wiring (PR-A)

### Overview

Make the repository's own Python tests and the research preflight actually run
and pass **inside CI jobs that branch protection requires**, so every later
phase is checked by a hard merge gate. Ships as its own PR and merges first:
the preflight is a separate subsystem with a slow gate, and nothing else in
this plan is observed by a required check until this lands.

### Changes Required

#### 1. Research preflight obsolete wrapper check

**Files**: `plugins/rpa/skills/research-codebase/evals/public/preflight.py`

**Changes**:

- Replace the block at lines 5999-6015 (reads
  `HERE.parents[3] / "commands" / "research_codebase.md"`) with a check named
  `"skill package carries kernel + artifact contract in both install layouts"`
  that asserts `HERE.parents[1] / "SKILL.md"` and
  `HERE.parents[1] / "references" / "artifact-contract.md"` are files and that
  `SKILL.md` links `references/artifact-contract.md` (`HERE` is
  `evals/public`, `preflight.py:23`, so `parents[1]` is the skill root; the
  plugin install and the manual copy install both ship `skills/` verbatim,
  `README.md:64-66`, `102-103`). Keep the `ok &= check(...)` shape so the
  check count and notes table are preserved.
- Update the comment to state why (wrappers removed in `5f10550`).
- **Discovered during implementation (2026-08-21):** the preflight has a
  second obsolete root one check later — the step-5 operator check at
  `preflight.py:6078` reads the pilot plan via `HERE.parents[3] /
  "thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md"`,
  but `thoughts/` lives at the repository root (`HERE.parents[5]`), so the
  run crashed with `FileNotFoundError` immediately after the repaired check
  passed. Change that one read to `HERE.parents[5]` with a comment; no other
  `HERE.parents[N]` literal in the file resolves to a missing path
  (inventoried: `parents[3]/scripts`, `parents[3]/agents` exist).

#### 2. Real steps inside the required `unit` and `integration` jobs

**Files**: `.github/workflows/ci.yml`

**Changes**:

- `unit` job (`ci.yml:27-37`): keep the job key and the existing template step;
  add `actions/setup-python@v5` (`python-version: "3.12"`) and, each as its own
  named step:
  - `python3 -m pip install --quiet pyyaml==6.0.2 markdown-it-py==3.0.0`
    (same pins as `docs-validate`, `ci.yml:82`)
  - `python3 plugins/rpa/hooks/test_run_gate.py`
  - `python3 scripts/validate_docs.py --self-test`
  - `python3 scripts/validate_docs.py --root .`
  - (Phase 1 adds `python3 plugins/rpa/skills/tdd/scripts/test_evidence.py`;
    Phase 2 adds `python3 plugins/rpa/skills/tdd/scripts/test_validate_session_log.py`
    — add those steps in those phases, not here.)
- `integration` job (`ci.yml:39-49`): keep the job key and template step; add
  `actions/setup-python@v5` and a step running `python3 runner.py --preflight`
  with `working-directory: plugins/rpa/skills/research-codebase/evals/public`
  and `timeout-minutes: 15` (preflight reaches the formerly-broken check in
  ~24 s; the implementer records the full green run time in the PR
  description).
- Leave `lint`, `e2e`, `coverage`, and `docs-validate` unchanged.
  `docs-validate` now duplicates two `unit` steps; that is deliberate — the
  required gate must not depend on a non-required job name, and `needs:` is
  not a substitute (a skipped required job satisfies protection).
- Update the header comment (`ci.yml:8-12`) to say the repo-owned Python
  checks live in `unit`/`integration` because those are the required contexts.

### Success Criteria

#### Automated Verification

- [x] `cd plugins/rpa/skills/research-codebase/evals/public && python3 runner.py --preflight` exits 0 and the notes table lists
      `skill package carries kernel + artifact contract in both install layouts` as `PASS` (2026-08-21: 278/278, 1 min 22 s wall-clock locally).
- [x] `python3 plugins/rpa/hooks/test_run_gate.py` exits 0 locally.
- [x] `python3 scripts/validate_docs.py --self-test && python3 scripts/validate_docs.py --root .` exits 0.
- [x] On PR-A, the `unit`, `integration`, and `docs-validate` checks are green, and the `unit` job log shows the four new steps executed (not skipped). (PR #16, run 32479080266: all eight checks pass; `unit` 9 s with all four steps `success`; `integration` 1 m 17 s with the preflight step `success`; `codex-review-window` pass.)
- [x] `gh api repos/dsmolchanov/rpa/branches/master/protection/required_status_checks | jq -c .contexts` is unchanged (`["lint","unit","integration","e2e","coverage","codex-review-window"]`).

#### Manual Verification

- [ ] Not applicable — every outcome in this phase is a CI status.

---

## Phase 1: Evidence kernel (`evidence.py`) and its tests

### Overview

Deliver the predict → run → grade → persist tool and its contract. First phase
of PR-B; depends on Phase 0 for CI visibility only.

### Changes Required

#### 1. Evidence contract (single source of truth)

**Files**: `plugins/rpa/skills/tdd/references/evidence-contract.md` (new)

**Changes**:

- Sections mirroring the four decision groups in **Implementation Approach**:
  Purpose; Store, authority, and security (location, `.rpa/evidence/.gitignore`,
  `RPA_EVIDENCE_DIR` rule, identifier and path containment, sanitisation
  pattern set incl. split-form, reports and `{report}` substring rule,
  execution bounds, Windows fallback); State machine and WAL (locking,
  worktree-wide lease keyed on controller pid + start token, run
  identity/lifecycle with derived index, record model and the exactly-one
  pairing rule, receipt id, idempotent repair protocol, phase machine,
  checkpoint transaction, capsule sections/bounds, export schema and prefix
  immutability); Provenance and phase causality (required inputs incl. the
  mandatory machine-checkable claim and mandatory Red scopes, claim grammar
  v1 with JUnit semantics and the stand-in rule, freshness envelope with
  union inheritance and pre/post checks, `--requires` causal rules, exit
  codes, `risk` audit-only); Tooling compatibility; Locating the tool after
  install; Citation form for session logs (`receipt <hex12>`); the statement
  that the store is local and never committed and what a receipt does and
  does not prove.
- Everything else in the repo links here rather than restating the grammar.

#### 2. The tool

**Files**: `plugins/rpa/skills/tdd/scripts/evidence.py` (new, executable,
`#!/usr/bin/env python3`, stdlib only, `from __future__ import annotations`,
no imports outside its own directory)

**Changes**:

- `argparse` subcommands `begin`, `run`, `status`, `checkpoint`, `export` with
  the options, record model, and exit codes fixed in **Implementation
  Approach**.
- Module-level functions (names for tests to import or the implementer to keep
  separable): `repo_root()`, `store_root()` (applies the `RPA_EVIDENCE_DIR`
  outside-only rule), `ensure_store_ignored()`, `store_lock()`,
  `valid_run_id(s) -> bool`, `store_paths(run_id)`, `contained(path) ->
  Path`, `resolve_report(arg, run) -> Path`, `substitute_report(argv, path)
  -> list[str]`, `redact(text) -> str`, `redact_argv(argv) -> list[str]`,
  `parse_claim(text) -> Claim`, `worktree_snapshot() -> dict[path, hash]`,
  `scope_digest(globs) -> (paths, digest)`, `envelope_of(record, records)
  -> Envelope`, `check_envelope(envelope) -> list[drift]`, `grade(claim,
  context) -> (outcome, detail)`, `parse_junit(path) -> list[TestCase]`,
  `validate_requires(run, ref, phase, case) -> record`, `admitted_phase(state,
  phase) -> bool`, `StreamReader` (thread: sha256 + count + ring tail +
  incremental contains), `execute(argv, timeout, lease) -> ExecResult`,
  `append_record(run_id, record)`, `read_lease()`, `write_lease(lease)`,
  `clear_lease()`, `controller_alive(pid) -> bool`, `repair(run_id,
  command) -> RepairReport`, `rebuild_index(run_id)`, `load_records(run_id)
  -> (records, partial_line)`, `canonical_json(obj) -> str`,
  `receipt_of(record) -> str`, `ledger_digest(records, through_n) -> str`,
  `build_capsule(records, run) -> str`, `pair_records(records) -> dict[n,
  (intent, terminal|None)]`.
- `run` order of operations: parse/validate options, identifiers, claims
  (≥ 1 machine-checkable), mandatory Red scopes, containment, and report rule
  (usage errors exit 2 before any write) → sanitise argv/because/claims into
  the intent payload (raw argv kept in memory only) → acquire lock → `repair`
  (fails closed on a live lease) → refuse if run sealed or phase not admitted
  by the phase machine → if `--requires`, validate the target → compute
  envelope (own scopes ∪ chain) and check it; on drift append intent +
  `finished(STALE)` and exit 3 without executing → snapshot pre-state, delete
  a pre-existing run-owned report → allocate `n`, append and fsync the
  intent, write the lease (`controller_pid`, `start_token`) → **release
  lock** → `Popen`, atomically rewrite the lease with `child_pid` → stream,
  wait with timeout → snapshot post-state and recompute the envelope → parse
  report if any `test` claim → grade claims (post-envelope drift forces
  `STALE`) → sanitise tails/details → compute receipt → acquire lock →
  append terminal record, `run.json.reports[]`, clear lease, `rebuild_index`
  → release → print a per-claim table plus `event=<ref> receipt=<hex12>
  outcome=<…>` → exit code.
- `status` prints the capsule projection plus the last `--last N` (default 8)
  records as `ref  kind  outcome  phase/case  because`, any `open` intents,
  the lease if present (live/dead), the ignored partial line if any, orphan
  snapshots, and a `capsule mismatch`/`index mismatch` line when `current.md`
  or `run.json` disagree with the ledger; never writes.
- `checkpoint` as fixed above (repair → envelope/branch/plan check → phase
  admission → snapshot-then-record transaction → rebuild index).
- `export` as fixed above (repair → branch/plan check → whole ledger, prefix
  immutability, `--out` contained, creates `thoughts/shared/tests/receipts/`),
  prints the path.
- No `shell=True` anywhere; no `os.system`; no network; no `fcntl` import at
  module top level (import inside the POSIX branch of `store_lock()`).
- **Discovered during implementation (2026-08-21)** — four refinements, all
  recorded in `evidence-contract.md`: (1) run identity (`id`, `nonce`,
  `plan_path`, `plan_sha256`, `branch`, `head`, `started_at`) lives in an
  immutable `runs/<id>/run.meta.json` written once by `begin`, so that
  `run.json` can be a purely derived index that repair rebuilds byte-identically
  from meta + ledger (EV-14) — storing identity only in the derived file would
  have made "rebuild identically" impossible; (2) `PENDING` manual claims never
  become the run outcome — a run whose machine-checkable claims all `PASS` is
  `PASS`, otherwise a Green receipt carrying a `manual` observation could never
  serve as a `--requires` target; EV-21 therefore uses a `SURPRISE` Red (not a
  `PENDING` one) as the non-PASS target; (3) `checkpoint final` is admitted
  from any state after `baseline` (with `--achieved` bounded by the state), not
  only as the successor of `refactor`, because a cycle legitimately ends at
  Green with Refactor not applicable or as `blocked`; (4) `run --phase final`
  is admitted from states `red|green|refactor` so Final-Verification runs can
  precede `checkpoint final`, which closes them.
- **Phase 1 review round (2026-08-21), all accepted and implemented** —
  output handling: durable writes go through `mkstemp` + fsync + rename +
  directory fsync and refuse symlinked targets/parents; only a *produced*
  report (`report_sha256` set) confers ownership, and a run-owned report is
  deleted only after a fresh regular-file/containment check; `export`
  fails closed on foreign JSON, a symlink target, a different run's export,
  a missing or hash-mismatched capsule. False certification: phase-aware
  claims (`red` needs `test … fail-with` or the stand-in pair — a lone
  `exit != 0` is refused; `green|refactor` need a pass claim **and**
  `--requires`), empty literals refused, `checkpoint red|green|refactor`
  and `--achieved …` require a `PASS` receipt of that phase. Freshness: an
  inherited scope is never replaced by a same-named child scope (kept as
  `name@<ref>` unless value-identical) and the pre-run check reads the
  required record's envelope verbatim. Isolation: one total deadline with
  reader joins, group verified gone after every run (`stragglers_terminated`),
  leader reaped between SIGTERM/SIGKILL (macOS `EPERM` on zombie groups),
  child started through a pid-file wrapper so a controller death between
  `Popen` and the lease rewrite leaves no untracked mutator, and the
  lock/lease live in a canonical coordination root (`<repo>/.rpa/evidence/`)
  independent of `RPA_EVIDENCE_DIR`. Recovery: the lease-owning run is
  reconciled (torn tail truncated) before any append; checkpoint capsules
  describe the state **after** the checkpoint. Bounds/sanitisation:
  `--tail-bytes` 1…65536, `--timeout` 1…86400, capsule items ≤ 512 B with a
  hard cap, `--because` required, `workflow`/`report_path`/start-error
  details redacted. Contract text now states the precedence: run-level
  invariants (sealed, branch, plan) refuse with exit 2; envelope drift
  (inherited scopes, HEAD) is recorded `STALE`. New cases: EV-28
  phase-aware claims + required inputs; EV-29 inherited-scope bypass;
  EV-30 export fail-closed; EV-31 descendants/controller death; EV-32
  store override shares the worktree lease; EV-33 cross-run torn-ledger
  repair; EV-34 bounds. Revised: EV-11 inspects the live intent, EV-13 covers
  stale-report deletion and symlink swap, EV-25 asserts the active ref and
  the pre-`Popen` lease shape, EV-26 covers final admission paths.

#### 3. Fixtures shared by tests and the dry run

**Files**: `plugins/rpa/skills/tdd/scripts/fixtures/junit_stub.py` (new):
`--out <path> --case <classname.name> --outcome pass|failure|error|skipped
[--message <text>]` writes one-testcase JUnit XML and exits 0 for `pass`, 1
otherwise — so tests and the Phase 3 dry run exercise real JUnit semantics
without pytest.

#### 4. Tests

**Files**: `plugins/rpa/skills/tdd/scripts/test_evidence.py` (new, `unittest`,
mirrors `plugins/rpa/hooks/test_run_gate.py` style; each test builds a temporary
git repo with `git init -q`, `git -c user.name=t -c user.email=t@t commit
--allow-empty -m init`, and a `.gitignore` containing `__pycache__/`; Red runs
in tests always pass `--scope red_inputs=… --scope plan=…`)

**Changes** — cases (stable ids for the session log):

- `EV-01` wrong-cause Red: report has `<error message="ImportError: …">`;
  claim `test sample.test_x fail-with "AssertionError"` → `SURPRISE`, exit 1.
- `EV-02` right-cause Red and report substitution: report has `<failure
  message="AssertionError: …">` and exit 1 → `PASS`, exit 0; argv
  `--out={report}` (substring form) and a bare `{report}` element are both
  substituted with the run-owned path; `report_sha256` matches the file.
- `EV-03` stale-by-scope: Red run `--phase red --case U-01 --scope
  red_inputs=tests/*.py --scope plan=plan.md`; modify `tests/test_x.py`; Green
  run `--phase green --case U-01 --requires <ref>` → outcome `STALE`, exit 3,
  the argv's side-effect marker file was **not** created.
- `EV-04` fresh-by-scope: same as EV-03 but modify only `src/x.py` → Green
  runs, exit 0.
- `EV-05` argv injection: `-- python3 -c "print('a;b')" ';' 'echo pwned'`
  passes the extra tokens as literal argv and no file named by a `$(...)`
  token is created.
- `EV-06` gitignore noise and store visibility: command creates
  `__pycache__/x.pyc`; claim `diff none` → `PASS`; `begin` leaves `git status
  --porcelain` empty, creates `.rpa/evidence/.gitignore` and **not**
  `.rpa/.gitignore`; a pre-existing `.rpa/evidence/.gitignore` with other
  content makes `begin` exit 2 without rewriting it.
- `EV-07` diff boundary: command writes `src/a.py`; `diff within tests/**`
  → `SURPRISE`; `diff within src/**` → `PASS`.
- `EV-08` manual claims: `manual "UI renders"` alone → exit 2 (no
  machine-checkable claim); with `exit == 0` added → `PENDING` + `PASS`,
  exit 0, and `status` lists the manual item under Open.
- `EV-09` partial-line tolerance: append a partial JSON line to
  `events.jsonl`; `status` exits 0 and reports one ignored partial record; the
  next `run` truncates it and gets the next monotonic `n`.
- `EV-10` receipt determinism and export prefix rule: the same record content
  yields the same receipt; `export` twice on an unchanged run is
  byte-identical; `export` after one more `run` rewrites the file with the
  old `events` as a prefix; hand-editing a record in the file then exporting
  exits 2 and leaves it intact; `export` of an open run succeeds and carries
  `run.state: open`.
- `EV-11` sanitisation before any persistence: stdout containing
  `TOKEN=abc123`, argv containing `--password=hunter2` **and** split-form
  `--password hunter2` appear as `[REDACTED]` in the **intent** record (read
  while the command is still running), in the terminal record, and in the
  export; `stdout_sha256` equals the sha256 of the raw bytes;
  `receipt_of(record)` recomputes from the exported record.
- `EV-12` unparseable claim and no claim: `--expect "works fine"` → exit 2;
  no `--expect` at all → exit 2; in both cases no record appended, command not
  executed.
- `EV-13` report rules: `test x pass` without `--report` → `ERROR`; selector
  matching two testcases → `ERROR`; a run-owned report the command does not
  rewrite → `ERROR` "not produced by this run"; `--report src/module.py`
  (tracked) and `--report notes.txt` (existing, not run-owned) → exit 2,
  nothing runs, file intact.
- `EV-14` lifecycle: `begin` twice creates two runs with distinct nonces and
  moves `current`; `begin --resume` of the first succeeds with the same plan
  and branch; a second process's `begin --resume` after a Red (simulating a
  later session) can run Green with `--requires` the earlier Red; `--resume`
  exits 2 after `checkpoint final`, when the plan sha differs, and when the id
  is `../../x` or otherwise fails the regex; `run` after sealing exits 2;
  `run.json` deleted by hand is rebuilt identically by the next command.
- `EV-15` idempotent repair: (a) intent + lease with a dead controller and no
  terminal → `status` lists it `open`; the next `run` appends exactly one
  `interrupted` record with `recovered_by.command == "run"` and clears the
  lease; (b) terminal present **and** lease left behind (crash after the
  terminal append) → repair only deletes the lease, no second terminal;
  (c) lease-less dangling intent → one `interrupted` record; (d) `export`
  performs the same repair; (e) running repair twice changes nothing.
- `EV-16` timeout: `--timeout 1` on a command whose child sleeps 30 s →
  `TIMEOUT`, exit 4, and the child process group is gone.
- `EV-17` bounded output: command prints 1 MiB with the literal `NEEDLE`
  only in the first 100 bytes; `stdout contains "NEEDLE"` → `PASS`,
  `stdout_tail` ≤ 8192 bytes, `stdout_bytes` = 1 MiB, digest matches.
- `EV-18` containment: `--report ../x.xml`, `--out /tmp/x.json`, a `path`
  claim through a symlink pointing outside the repo, a `current` file
  containing `../../evil`, and `RPA_EVIDENCE_DIR` set to the repo root, an
  ancestor, or a subdirectory of the repo → exit 2, nothing runs; set to a
  sibling temp dir → accepted.
- `EV-19` JUnit semantics: `test x pass` with exit 1 → `SURPRISE`; `<skipped>`
  → `SURPRISE`; `fail-with` with `<error>` → `SURPRISE`; `fail-with` with
  exit 0 → `SURPRISE`.
- `EV-20` dirty-file change: pre-existing modified file is modified again by
  the command; `diff none` → `SURPRISE`.
- `EV-21` causal chain: Green `--requires` a Red of another case, a
  `PENDING` Red, a later `n`, or a `green` record → exit 2, nothing runs;
  Green against a `PASS` Red after `git commit` in the temp repo (HEAD drift,
  scopes fresh) → `STALE`, exit 3.
- `EV-22` mandatory and empty scopes: `--phase red` without `red_inputs` or
  without `plan` → exit 2; `--scope red_inputs=nonexistent/*.py` → exit 2;
  nothing runs.
- `EV-23` relocatable package: copy `skills/tdd/` to a temp dir; `python3
  <copy>/scripts/evidence.py begin …` and one `run` succeed.
- `EV-24` checkpoints and capsule: `checkpoint baseline`, `red`, `green`
  succeed in order; `checkpoint red` after `green` exits 2; a second
  `checkpoint red` after a re-run Red is allowed; the capsule file is ≤ 120
  lines / 16 KiB with a long history and contains Verified / Open / Blocked /
  Not applicable / Next sections with `--next`/`--open` items; the checkpoint
  record's `ledger_sha256` equals `ledger_digest(records, ledger_head)`,
  `capsule_sha256` matches the snapshot, and `receipt_of(checkpoint
  record)` recomputes; a Green with no own scopes stays Verified while its
  Red's scopes are fresh and is demoted to Open after a Red input changes;
  `checkpoint final --achieved green` seals; export contains ordered
  `capsules[]`; an orphan snapshot file written by hand is removed by the next
  repair; `current.md` deleted by hand is regenerated.
- `EV-25` worktree-wide lease, fail closed: (a) with a lease whose controller
  is a live sleeping process, `run`, `checkpoint`, and `export` on the **same**
  run and on a **different** run in the same store exit 2 naming the ref;
  (b) a lease with `controller_pid` alive but `child_pid` absent (pre-`Popen`)
  is treated as live; (c) after the controller exits, repair proceeds.
- `EV-26` phase machine: `run --phase red` before `checkpoint baseline` →
  exit 2; `run --phase red` after `checkpoint green` → exit 2; `run --phase
  green` in state `red` → allowed; `checkpoint final` then any `run` or
  `checkpoint` → exit 2; `checkpoint green` while the last Red attempt is
  newer than the last `checkpoint red` → exit 2 (invariant: every P attempt
  precedes the last `checkpoint P`).
- `EV-27` post-run drift: a Green command that appends to a file in the Red's
  `red_inputs` → outcome `STALE` with `drift during execution`, exit 3, even
  though the test claim itself would pass; a Red command that rewrites the
  plan file → `STALE`.

#### 5. CI step

**Files**: `.github/workflows/ci.yml`

**Changes**: add the `python3 plugins/rpa/skills/tdd/scripts/test_evidence.py`
step to the `unit` job (after the hooks test step).

### Success Criteria

#### Automated Verification

- [x] `python3 plugins/rpa/skills/tdd/scripts/test_evidence.py` exits 0 with all EV-01…EV-34 cases passing (2026-08-21, after the Phase 1 review round: 34/34 in ~44 s).
- [x] `python3 scripts/validate_docs.py --root .` exits 0 (new markdown links resolve).
- [x] `grep -n "shell=True\|os.system\|^import fcntl\|^from fcntl" plugins/rpa/skills/tdd/scripts/evidence.py` prints nothing.
- [x] Smoke in this repo: `python3 plugins/rpa/skills/tdd/scripts/evidence.py begin --plan thoughts/shared/plans/2026-08-21-tdd-evidence-kernel.md` then
      `python3 plugins/rpa/skills/tdd/scripts/evidence.py run --phase baseline --because "smoke" --expect 'exit == 0' --expect 'diff none' -- python3 plugins/rpa/hooks/test_run_gate.py`
      prints `outcome=PASS`, exits 0, and `git status --porcelain` shows no new files (`.rpa/evidence/` self-ignored, `.rpa/.gitignore` absent).
- [x] On the PR, the `unit` job log shows the `test_evidence.py` step executed and green. (PR #17 draft, run 32500765670: `unit` 54 s, step `TDD evidence kernel tests (EV-01…EV-34)` success; `integration` 1 m 8 s; all required checks pass.)

#### Manual Verification

- [ ] Not applicable — behavior is fully covered by EV-01…EV-34 and the smoke command.

---

## Phase 2: Session-log validator and its binding

### Overview

Close the loop: a session log is only acceptable when its evidence cites
receipts that resolve, recompute, and chain causally in a committed complete
export bound to the named test plan — and CI validates every committed log,
not only fixtures, with permanent fixtures for the discovery itself. Depends
on Phase 1 (export schema).

### Changes Required

#### 1. Validator

**Files**: `plugins/rpa/skills/tdd/scripts/validate_session_log.py` (new,
stdlib only; imports `receipt_of`/`canonical_json`/`ledger_digest`/
`pair_records` from the sibling `evidence.py`; CLI
`validate_session_log.py <log.md>`, exit 0 valid / 1 invalid with one error
per line / 2 usage)

**Changes**:

- **Layout binding** (no overrides): the log's realpath must be
  `<root>/thoughts/shared/tests/<name>.md` (the validator derives `<root>` as
  `log.parents[3]` and requires `log.parents[2].name == "thoughts"`,
  `parents[1].name == "shared"`, `parents[0].name == "tests"`; otherwise
  exit 2 "log outside the contract layout"). The export path is **exactly**
  `<root>/thoughts/shared/tests/receipts/<header run id>.json` — the
  `**Evidence export**` header must read `receipts/<header run id>.json`
  verbatim, and the resolved realpath must equal the expected realpath (no
  `..`, absolute, or symlinked alternatives). The `**Test Plan**` header is
  repo-relative and resolves to `<root>/<value>`, which must exist.
- **Structural parsing** first: exclude fenced code blocks (``` and ~~~),
  indented code blocks (≥ 4 spaces / tab outside lists), HTML comments
  (`<!-- … -->`, multi-line), and CommonMark HTML blocks (a line starting
  with `<` + tag, through the next blank line) before any heading, table,
  bullet, or `receipt` token scan.
- Checks, in order: (a) required headings of
  `references/session-log-contract.md` present exactly once and in order
  (`# TDD Session:`, `## Baseline`, `## Case Dispositions`, `## Red Phase`,
  `## Green Phase`, `## Refactor Phase`, `## Final Verification`, `## Summary`);
  (b) header lines `**Evidence schema**: `tdd/1``, `**Evidence run**:`
  (matches the run-id regex), `**Evidence export**:` (exact value above),
  `**Test Plan**:` present; Summary carries `**Achieved phase**` and
  `**Cycle state**: `continuing | complete | blocked``; (c) the export exists
  at the exact path, parses as the Phase 1 export schema, `run.id` equals the
  header run id, `run.plan_path` equals the `**Test Plan**` value, and
  `sha256(<root>/<plan_path>)` equals `run.plan_sha256`; (d) **ledger
  integrity**: `events[].n` is contiguous from 1 to `records_through`; each
  `n` is exactly one checkpoint record **or** exactly one `started` followed
  by exactly one terminal with the same `ref`, `run`, and byte-identical
  intent fields (`phase`, `case`, `argv`, `claims[].text`, `scopes`,
  `envelope`, `requires`, `report_path`, `start_token`, `at`); no terminal
  without its intent, no duplicate terminals, no intent-only `n`; no receipt
  token cites an `n` above `records_through`; the export's `run.state`,
  `run.achieved`, and `run.phase` equal the values derived from `events`;
  (e) every `receipt <hex12>` token resolves to a terminal or checkpoint
  record; (f) every terminal and checkpoint record's receipt recomputes and
  every checkpoint's `ledger_sha256` equals `ledger_digest(events,
  ledger_head)` and its `capsule_sha256` equals the sha256 of the matching
  `capsules[]` text; (g) each `Commands and exits` bullet in Red/Green/
  Refactor/Final sections either carries a `receipt <hex12>` or is exactly
  `Not run — <reason>` / `Not applicable — <reason>`; (h) **case
  completeness**: the planned case set P is parsed from the bound test plan's
  §3 tables (`^\| ([UIE]-\d+) \|` rows outside fences); the disposition set
  D from the Case Dispositions table; the ledger set L from terminal records
  with phase `red|green|refactor`; require P non-empty, D == P with each id
  exactly once, every disposition in the contract's enum, L ⊆ P, and every
  phase section that is not `Not run` has at least one receipt bullet; (i)
  **coverage**: every terminal record in the export with `phase` in
  `red|green|refactor|final` is cited at least once in the log (failed and
  stale attempts included — the log may not hide them); (j) disposition ↔
  receipt: `valid Red` cites a receipt with `phase: red`, `case` equal to the
  row's Case ID, `outcome: PASS`, and either a `test … fail-with` claim or,
  when the row's Evidence cell contains `stand-in`, both an `exit != 0` claim
  and a `contains` claim; `Green` → `phase: green`, same case, `PASS`,
  `requires` resolving to a `red` `PASS` record of the same case with a
  smaller `n` (stand-in Green: `exit == 0` claim present); `refactored-green`
  → `phase: refactor`, same case, `PASS`, `requires` chaining to a `green`
  `PASS` of the same case; `already covered` / `blocked` / `not_applicable`
  rows need no receipt but must carry a reason; (k) no receipt whose only
  claims are `manual` is cited as the sole evidence of a `Green` disposition;
  (l) **phase machine**: for every phase P with terminal records, the last
  `checkpoint P` has `n` greater than every P attempt; checkpoint phases are
  non-decreasing; if a `checkpoint final` exists it is the last record; (m)
  **cycle state**: `continuing` ⇒ `run.state == open`, no `checkpoint final`;
  `complete` ⇒ `run.state == sealed`, `run.achieved ∈ {green,
  refactored-green}`, and if `green` the `## Refactor Phase` section reads
  `Not applicable — <reason>`; `blocked` ⇒ `run.state == sealed` and
  `run.achieved == blocked`; in all cases `**Achieved phase**` maps to
  `run.achieved` (`Red`↔`red`, `Green`↔`green`, `Refactored Green`↔
  `refactored-green`, `Blocked`↔`blocked`) or, for `continuing`, to the
  phase of the last checkpoint.
- Output one line per error: `session-log: <check> — <detail>`.

#### 2. Fixtures

**Files** (new, under `plugins/rpa/skills/tdd/scripts/fixtures/session-logs/`;
**each case is a mini repo root** `<case>/thoughts/shared/tests/` holding the
log `<date>-TDD-SESSION-<case>.md`, the test plan `<date>-TEST-<case>.md`, and
`receipts/<run-id>.json`, so the layout binding is exercised verbatim):
`valid/` (a **complete** export produced by `evidence.py` in a throwaway repo
using `junit_stub.py` for a two-case plan, baseline → red → green for both
cases with one `STALE` attempt, sealed `complete` with Refactor `Not
applicable`, never edited by hand — the log cites every attempt);
`valid-continuing/` (open run, Red only, `continuing`); and invalid cases,
each differing from `valid` in one respect: `missing-receipt`,
`unresolvable-receipt`, `manual-as-green`, `heading-order`, `run-mismatch`,
`nonpass-disposition`, `fenced-heading`, `html-comment-heading` (headings and
receipt tokens inside `<!-- -->` and an HTML block), `broken-chain`,
`missing-checkpoint`, `hollow` (all headings, checkpoints, no disposition
rows, no receipt bullets), `uncited-attempt` (omits the `STALE` attempt),
`standin-exit-only`, `tampered-export` (one record's `exit` edited),
`trimmed-export` (one intent+terminal pair removed → gap), `intent-deleted`
(terminal left, intent removed), `duplicate-terminal`, `ref-mismatch`
(terminal's `argv` differs from its intent), `unsealed-complete` (open run,
log says `complete`), `achieved-mismatch` (`run.achieved: green`, log says
`Refactored Green`), `partial-cases` (plan has two cases, one disposition
row), `plan-mismatch` (header names a different plan file → sha mismatch),
`export-traversal` (header `../receipts/x.json`), `export-absolute`,
`export-symlink` (a symlink at the exact path pointing elsewhere → realpath
mismatch), `attempt-after-checkpoint` (Red attempt with `n` above the last
`checkpoint red`), `record-after-final`.

**Changes**: minimal synthetic content (conventions §10 — no fully populated
fake numbers); no markdown links (the link checker walks this directory).

#### 3. Tests

**Files**: `plugins/rpa/skills/tdd/scripts/test_validate_session_log.py` (new,
`unittest`) — `VL-01` `valid` exits 0; `VL-02` `valid-continuing` exits 0;
then one case per invalid fixture, each asserting the check letter appears in
the output: `VL-03` missing-receipt (g); `VL-04` unresolvable-receipt (e);
`VL-05` manual-as-green (k); `VL-06` heading-order (a); `VL-07` run-mismatch
(c); `VL-08` nonpass-disposition (j); `VL-09` fenced-heading (a)/(e); `VL-10`
html-comment-heading (a)/(e); `VL-11` broken-chain (j); `VL-12`
missing-checkpoint (l); `VL-13` hollow (h); `VL-14` uncited-attempt (i);
`VL-15` standin-exit-only (j); `VL-16` tampered-export (f); `VL-17`
trimmed-export (d); `VL-18` intent-deleted (d); `VL-19` duplicate-terminal
(d); `VL-20` ref-mismatch (d); `VL-21` unsealed-complete (m); `VL-22`
achieved-mismatch (m); `VL-23` partial-cases (h); `VL-24` plan-mismatch (c);
`VL-25` export-traversal (b); `VL-26` export-absolute (b); `VL-27`
export-symlink (b); `VL-28` attempt-after-checkpoint (l); `VL-29`
record-after-final (l); `VL-30` a log copied outside the
`thoughts/shared/tests/` layout exits 2.

#### 4. Binding in the docs gate: skill fixtures, committed logs, **and permanent discovery fixtures**

**Files**: `scripts/validate_docs.py`, `tests/fixtures/docs-validate/positive/`,
`tests/fixtures/docs-validate/negative/<new cases>/`

**Changes**:

- Add module constant `SESSION_LOG_VALIDATOR = Path(__file__).resolve().parents[1]
  / "plugins/rpa/skills/tdd/scripts/validate_session_log.py"` — the validator
  is resolved from the **real** repository that owns `validate_docs.py`, not
  from the root being validated, so fixture roots exercise the real binding.
- Add `check_session_log_validator(root, errors)` mirroring
  `check_artifact_validator` (`scripts/validate_docs.py:484-603`): skill
  package absent under `plugin_root(root)` → return (not applicable);
  validator or any fixture case missing → error; `valid`/`valid-continuing`
  rejected → error; each invalid case accepted → error naming the case.
- Add `check_session_logs(root, errors)`: discovery is the **union**, de-
  duplicated by resolved path, of (1) every `root/thoughts/shared/tests/*.md`
  whose file name matches `^\d{4}-\d{2}-\d{2}-TDD-SESSION-.+\.md$`
  (`session-log-contract.md:5`) and (2) every `*.md` there whose first H1
  outside fences/HTML starts with `# TDD Session:`; run
  `SESSION_LOG_VALIDATOR` on each (the validator, not discovery, checks the
  H1 and layout — a correctly named file with a broken or missing H1 fails
  check (a) instead of escaping); any non-zero exit → one error per validator
  line prefixed with the log path. Then every
  `root/thoughts/shared/tests/receipts/*.json` must be the resolved export of
  at least one discovered log (orphan export → error). Directory absent or
  both sets empty and no receipts → return (not applicable — true at
  baseline). This check does **not** skip when the skill package is absent
  from `root`: it needs only `SESSION_LOG_VALIDATOR`, which always exists in
  the real repo (error if it does not).
- Call both from `validate()` after `check_artifact_validator`
  (`scripts/validate_docs.py:605-613`).
- **Permanent discovery fixtures** (self-test, `scripts/validate_docs.py:614-652`;
  every negative case carries the usual minimal `agents/ commands/ skills/`
  plus an `EXPECTED` file): `positive/thoughts/shared/tests/` gains a valid
  log named per contract **whose H1 also matches** (union de-duplication: it
  must validate once and produce no error), its test plan, and
  `receipts/<run-id>.json` (generated by the same procedure as the skill
  `valid` fixture); new `negative/` cases: `session-log-filename-only-malformed`
  (contract file name, content `hello`; `EXPECTED` = `session-log: a`),
  `session-log-h1-only-malformed` (file `notes.md` with H1 `# TDD Session:`,
  no headers; `EXPECTED` = `session-log: b`), `session-log-orphan-export`
  (`receipts/orphan.json` and no log; `EXPECTED` = `orphan export`),
  `session-log-both-criteria-malformed` (file name and H1 both match, body
  hollow; `EXPECTED` = `session-log: h`, and the self-test output line shows
  the path once), `session-log-valid-layout-broken-export` (valid-shaped log
  whose export file is missing; `EXPECTED` = `session-log: c`).
- Confirm `python3 scripts/validate_docs.py --self-test` passes with the new
  positive content and catches each new negative case by its `EXPECTED` text.

#### 5. CI step

**Files**: `.github/workflows/ci.yml`

**Changes**: add `python3 plugins/rpa/skills/tdd/scripts/test_validate_session_log.py`
to the `unit` job.

### Success Criteria

#### Automated Verification

- [ ] `python3 plugins/rpa/skills/tdd/scripts/test_validate_session_log.py` exits 0 (VL-01…VL-30).
- [ ] `python3 scripts/validate_docs.py --self-test` exits 0 and its output lists `negative/session-log-filename-only-malformed`, `…-h1-only-malformed`, `…-orphan-export`, `…-both-criteria-malformed`, `…-valid-layout-broken-export` as caught, and `positive fixture clean`.
- [ ] `python3 scripts/validate_docs.py --root .` exits 0.
- [ ] Temporarily making `validate_session_log.py` return 0 unconditionally makes `python3 scripts/validate_docs.py --self-test` fail (the negative discovery cases are no longer caught) and `--root .` exit non-zero naming an accepted invalid skill fixture (revert before commit; record the observed messages in the PR).
- [ ] On the PR, the `unit` job log shows the `test_validate_session_log.py` step, `validate_docs.py --self-test`, and `validate_docs.py --root .` green.

#### Manual Verification

- [ ] Not applicable.

---

## Phase 3: Wire the workflow to the kernel (contracts, kernel rows, version)

### Overview

Make the TDD workflow produce and consume receipts. Depends on Phases 1–2.
Text edits only; the gate rows become executable by pointing at Phase 1–2
runners.

### Changes Required

#### 1. Test-plan contract: typed Red/Green claims

**Files**: `plugins/rpa/skills/create-test-plan/references/artifact-contract.md`

**Changes**:

- In each of the three Red-phase tables (lines 50-52, 58-60, 66-68) add a final
  column `Evidence claims` whose cell holds the Red claim and Green claim in the
  Phase 1 grammar, e.g. `Red: test <selector> fail-with "<literal>" · Green:
  test <selector> pass`, or — marked `stand-in` — `Red: exit != 0 + stderr
  contains "<cause literal>" · Green: exit == 0`.
- Content rules (line 114 ff.): add "Evidence claims use the grammar in
  `../../tdd/references/evidence-contract.md`; `manual "<observable>"` claims
  appear only in §5 and §6 Manual; a case whose expected result cannot be
  expressed as a `test …` claim (no JUnit report available) is marked
  `stand-in`, names the cause literal, and states why; every case names the
  `red_inputs` globs (tests, fixtures, helpers, runner config, lockfiles).
  The §3 case ids are the planned case set the session-log validator binds
  to: every planned case gets exactly one disposition."
- `## 6. Quality Gates` Automated bullets: note that `/tdd` runs them through
  `evidence.py run` and cites receipts.

#### 2. Session-log contract: receipts instead of transcribed commands

**Files**: `plugins/rpa/skills/tdd/references/session-log-contract.md`

**Changes**:

- Header block (lines 14-19): add `**Evidence schema**: `tdd/1``,
  `**Evidence run**: `[run id]`` and
  `**Evidence export**: `receipts/<run-id>.json`` (exactly this shape: the
  export is committed next to the log under `thoughts/shared/tests/receipts/`;
  the validator accepts no other path). Keep `**Test Plan**` as the
  repo-relative path — it is now binding (the export's `plan_path`/sha must
  match).
- Case Dispositions (lines 28-32): "exactly one row per case id in the test
  plan's §3 tables; Evidence column: `[receipt <hex12> — salient assertion;
  "stand-in" when the plan declared a stand-in claim; or the reason for
  already covered / blocked / not_applicable]`".
- Red/Green/Refactor/Final "Commands and exits" bullets: shape becomes
  ``- `receipt <hex12>` · `[argv]` → `[exit]`: [salient result]``; phases not run
  stay `Not run — reason`.
- Summary (lines 61-66): add `- **Cycle state**: [continuing / complete /
  blocked]` with the rule "`complete` only after `checkpoint final` (Refactored
  Green, or Green with Refactor `Not applicable — reason`); `blocked` only
  after `checkpoint final --achieved blocked`; otherwise `continuing`".
- Evidence rules (lines 69-80): replace "Record actual command strings and exit
  statuses" with "Every executed verification is a receipt from
  `scripts/evidence.py`, run with the phase and case it belongs to; the log
  cites the receipt and the exported receipt file; **every** attempt in the
  export is cited — a receipt that is `STALE`, `SURPRISE`, `TIMEOUT` or
  `INTERRUPTED` is evidence of a corrected belief, not something to omit."
  Keep the remaining rules.
- Add: "One evidence run per test plan across sessions: a continuation
  session runs `begin --resume <run id from this header>`. Checkpoint at each
  phase boundary (re-checkpoint a phase after re-running it); seal with
  `checkpoint final --achieved <phase>` when the cycle ends; `evidence.py
  export` before finishing **every** session; the export path is committed
  with the log and never edited by hand."
- Add a pointer to `evidence-contract.md` for the grammar.

#### 3. TDD kernel

**Files**: `plugins/rpa/skills/tdd/SKILL.md`

**Changes**:

- Frontmatter `permission-class` (line 12) →
  `workspace_write (plan-scoped source, tests, thoughts/shared/tests session log and receipts, .rpa/evidence local state)`
  — no nested parentheses (`scripts/validate_docs.py:91-93`).
- Scope & authority (lines 26-31): "Write only the source, tests, fixtures,
  and session artifact" → "…, the session log and its receipt export under
  `thoughts/shared/tests/`, and the local evidence store under
  `.rpa/evidence/` (never committed; nothing else under `.rpa/`)". Keep the
  commit/push clause.
- `## Artifact contracts`: add the evidence contract bullet and the rule
  "`<skill-dir>` is the directory containing this file; the tool is
  `<skill-dir>/scripts/evidence.py`".
- Process guidance step 2: if a session log for this plan exists, `begin
  --resume <its Evidence run>`; otherwise `begin --plan <test plan>` after
  baseline inspection; `checkpoint baseline`. Step 5-6: run the narrow Red
  command through `evidence.py run --phase red --case <id> --scope
  red_inputs=… --scope plan=… --report <name>` with `{report}` in the argv
  when the stack emits JUnit, and a `test <selector> fail-with` claim (or the
  plan's stand-in pair); an `ERROR`/`SURPRISE` Red is infrastructure or
  wrong-cause and is not Red; `checkpoint red --next …` (again after any
  re-run). Step 7-9: Green runs pass `--phase green --case <id> --requires
  <Red ref>`; a `STALE` result means the Red inputs, plan, branch, or `HEAD`
  changed since Red (or during the run) — re-run Red and re-checkpoint, do
  not edit the claim to fit; `checkpoint green`. Step 10-11: refactor runs
  `--phase refactor --case <id> --requires <Green ref>`; `checkpoint
  refactor`. Step 13: when the cycle ends, `checkpoint final --achieved
  <phase>`; in every session `evidence.py export`, fill `**Cycle state**`,
  then run the session-log validator.
- Acceptance criterion 5 (lines 131-132): "Only plan-scoped files, the
  session log, and its receipt export are changed; the local evidence store
  is not committed; pre-existing user changes remain intact."
- Deterministic verification profile (lines 144-149): change runners/evidence:
  - `Red causality` → runner `evidence.py run --phase red --case <id>` with
    mandatory `red_inputs`/`plan` scopes and a `test … fail-with` claim or the
    stand-in pair; evidence `receipt ref with outcome PASS`.
  - `Green regression` → runner `evidence.py run --phase green --case <id>
    --requires <Red ref>`; evidence `receipt refs, outcome PASS, no STALE`.
  - Add `Recovery capsule` → applicability every phase boundary; runner
    `evidence.py checkpoint <phase>`; blocking; evidence `checkpoint record
    and capsule snapshot`.
  - Add `Evidence export` → applicability every session; runner
    `evidence.py export` (after `checkpoint final` when the cycle ends); when
    before finishing; blocking; evidence `receipt file path committed
    alongside the log`.
  - `Session artifact` → runner
    `python3 <skill-dir>/scripts/validate_session_log.py <log>`; evidence `exit 0`.
- Escalation: add "Stop and report when `run` returns `STALE` twice for the
  same Red ref without an intervening test/plan edit you made — the scope
  declaration is wrong, not the code", "Stop when `run` returns `STALE` with
  `drift during execution` — the command mutates its own inputs", "Stop when
  `run` returns `TIMEOUT` or `INTERRUPTED` for a command that should be fast —
  do not raise `--timeout` to hide a hang", and "Stop when `run` reports
  `execution in progress` and you did not start it — another session holds
  the lease".

#### 4. Plugin version

**Files**: `plugins/rpa/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

**Changes**: bump `2.0.0` → `2.1.0` in both (new scripts, additive contract
fields).

#### 5. Hooks README cross-reference (documentation only)

**Files**: `plugins/rpa/hooks/README.md`

**Changes**: one sentence after line 32 noting that test-run evidence for TDD is
produced by `skills/tdd/scripts/evidence.py`, not by a hook, and why (the loop is
closed at the artifact gate and in CI by `validate_docs.py`).

### Success Criteria

#### Automated Verification

- [ ] `python3 scripts/validate_docs.py --self-test && python3 scripts/validate_docs.py --root .` exits 0 (frontmatter incl. the new `permission-class`, links, manifests, both validator bindings, log discovery fixtures).
- [ ] `python3 plugins/rpa/skills/tdd/scripts/validate_session_log.py plugins/rpa/skills/tdd/scripts/fixtures/session-logs/valid/thoughts/shared/tests/<date>-TDD-SESSION-valid.md` exits 0.
- [ ] `git diff --name-only origin/master..HEAD` lists only files named in this plan plus the plan itself.
- [ ] End-to-end dry run in this repo (implementer executes and pastes output into the PR; no git commits; order matters): `evidence.py begin --plan <this plan>`; `evidence.py checkpoint baseline`;
      `evidence.py run --phase red --case U-01 --because "red" --scope red_inputs='plugins/rpa/skills/tdd/scripts/test_*.py,plugins/rpa/skills/tdd/scripts/fixtures/junit_stub.py' --scope plan=<this plan> --report dryrun.xml --expect 'test sample.test_x fail-with "AssertionError"' -- python3 plugins/rpa/skills/tdd/scripts/fixtures/junit_stub.py --out={report} --case sample.test_x --outcome failure --message "AssertionError: expected"`
      → `outcome=PASS`; `evidence.py checkpoint red`;
      `evidence.py run --phase green --case U-01 --because "green" --requires <red ref> --report dryrun.xml --expect 'test sample.test_x pass' -- python3 plugins/rpa/skills/tdd/scripts/fixtures/junit_stub.py --out={report} --case sample.test_x --outcome pass`
      → `outcome=PASS`; `evidence.py checkpoint green`; `evidence.py export` (open run) → one new file under `thoughts/shared/tests/receipts/`;
      `evidence.py checkpoint final --achieved green`; `evidence.py export` again → same file rewritten with the previous content as prefix;
      `git status --porcelain` shows exactly that one new file and nothing under `.rpa/` (delete the export before commit — it is a dry run, not a session).
- [ ] Negative dry run in a throwaway repo (scratch dir, not this checkout): `git init`, one test file, `begin`, `checkpoint baseline`, Red as above with `--scope red_inputs='tests/*.py'`, `checkpoint red`, then append a line to the test file, then the Green `run --requires <red ref>` → `outcome=STALE`, exit 3, the stub's report was not rewritten; `run --phase red` again (admitted in state `red`) → `PASS`; `checkpoint green` before re-checkpointing red → exit 2; `checkpoint red`; then `checkpoint final --achieved blocked` and a further `run` → exit 2 (sealed); while a `run` with a sleeping command is in flight from one terminal, `evidence.py export` from another → exit 2 `execution in progress`.

#### Manual Verification

- [ ] Read the updated `tdd/SKILL.md` once end-to-end and confirm no step still asks the model to transcribe a command/exit by hand (the only human-judgment check in this plan).

---

## Testing Strategy

### Unit Tests

- `test_evidence.py` EV-01…EV-27: claim grading per kind (right/wrong cause
  with `<failure>` vs `<error>`, exit/pass coupling, ambiguous selectors,
  report rules, run-owned scratch and substring `{report}` substitution,
  content-hash diff boundaries, gitignore noise, manual pending, mandatory
  machine-checkable claim), freshness envelope (`STALE` blocks execution on
  scope/`HEAD`/branch/plan drift before the run and records drift after it;
  unrelated edits do not; mandatory Red scopes; empty scope refused; union
  inheritance), causal chain (`--requires` phase/case/outcome/order rules),
  phase machine (admitted phases, re-checkpoint, final is last), safety (argv
  literal, no shell, path/identifier/store-location containment,
  self-ignored store inside the authority path, never deleting non-run-owned
  files, sanitised intent incl. split-form credentials), execution bounds
  (timeout + process group, streaming digest + bounded tail), store
  robustness (partial line, idempotent repair across crash points,
  worktree-wide lease incl. cross-run and pre-`Popen`, monotonic contiguous
  refs, cross-session resume, derived index rebuild, seal), determinism
  (receipt id recomputes for terminal and checkpoint records, export prefix
  immutability), checkpoint transaction and hash-bound capsule, relocatable
  package, usage errors.
- `test_validate_session_log.py` VL-01…VL-30: layout binding (exact export
  path, traversal/absolute/symlink rejection, log outside layout), heading/
  header presence and order, fence/indent/HTML-comment/HTML-block stripping,
  plan path + sha binding, ledger contiguity and exactly-one pairing (gap,
  intent-deleted, duplicate terminal, ref mismatch), derived-state agreement,
  receipt resolution and recomputation, checkpoint hash binding, `Not run`
  allowance, case completeness (hollow, partial), attempt coverage,
  disposition ↔ phase/case/outcome incl. the stand-in pair, causal chain,
  manual-as-green rejection, phase-machine invariants (attempt after
  checkpoint, record after final), cycle-state consistency.
- Existing `hooks/test_run_gate.py` keeps passing and now runs in the
  required `unit` job.

### Integration Tests

- `scripts/validate_docs.py --self-test` binds the committed-log discovery to
  permanent positive/negative fixture roots (filename-only, H1-only,
  both-criteria de-duplication, orphan export, broken export) using the real
  validator; `--root .` validates skill fixtures, every committed TDD session
  log, and orphan exports — the cross-component check between
  `validate_docs.py`, the validators, the fixtures, and `thoughts/shared/tests/`.
- Phase 3 end-to-end dry run (begin → baseline → red with JUnit → green with
  `--requires` → checkpoints → open export → seal → prefix re-export) in this
  repository, plus the negative drift/phase-machine/seal/lease run in a
  throwaway repository.

### Manual Testing

- Phase 3 read-through of `tdd/SKILL.md` for residual hand-transcription steps.
  Otherwise not applicable — all other outcomes are command exits.

## Performance Considerations

- `run` calls `git status --porcelain` twice and hashes only the files it lists
  plus files matched by the envelope's scope globs (twice: before and after);
  on large repos the cost is the cost of `git status`. No full-tree hashing.
  Output is streamed (digest + ring buffer), so memory is bounded by
  `--tail-bytes` plus pipe buffers regardless of command output size; the
  store and exports stay small.
- The lock is held only around ledger mutations, so a long-running command
  does not block `status`; the worktree-wide lease makes concurrent mutators
  fail fast instead of queueing or interleaving.
- `integration` gains the preflight (reaches the repaired check in ~24 s; full
  duration recorded in PR-A); `unit` gains a few seconds of Python tests plus
  the docs validator and its larger self-test fixture set.

## Migration and Rollback

- No data migration: the store is new and local (`.rpa/evidence/`,
  self-ignored), never committed; deleting that directory is a full reset.
  `RPA_EVIDENCE_DIR` relocates it outside the repository without code change.
- No legacy session logs exist in this repository at baseline, so the
  committed-log CI check starts with an empty (not applicable) target set; the
  first real session log must validate. Other repositories are unaffected until
  they adopt plugin `2.1.0` and run the validator locally.
- PR-A (Phase 0) can be reverted independently; PR-B reverts to the PR-A
  state. No consumer outside this repository reads the receipts format yet.
  The test-plan contract change is additive (new column), so plans produced
  before it remain readable by `/tdd`, which treats a missing claim as "state
  the stand-in pair in the log"; their §3 case ids already exist and are what
  the validator binds to.

## References

- Request: this session's three-way reconciliation of the `arc-skill`
  analysis (source repo `https://github.com/pbshgthm/arc-skill` at
  `dba53c3799eab600a512dd73ed037d7ab6958c66`; mechanisms referenced:
  `predictions.py` claim grading, `live.py:296-317` stale-plan rejection,
  `core.py:105-209` append-only events/atomic writes/lock,
  `inspect.py:208-231` nudges, `inspect.py:285-298` mtime-based demotion).
- Review rounds 2–4 (2026-08-21) — synthesized in **Enhancement History**.
- `docs/conventions.md:20-35` (kernel layout), `:118-147` (gate model),
  `:162-178` (interaction gates), `:206-213` (single source of truth).
- `plugins/rpa/skills/tdd/SKILL.md:12` (permission-class), `:26-31` (scope &
  authority), `:50-51`, `:59-73`, `:77-78`, `:92-95`, `:131-132`, `:140-149`.
- `plugins/rpa/skills/tdd/references/session-log-contract.md:5`, `:14-19`, `:28-32`, `:61-66`, `:69-80`.
- `plugins/rpa/skills/create-test-plan/references/artifact-contract.md:44-71`, `:114-125`.
- `scripts/validate_docs.py:72-74` (`plugin_root`), `:91-93` (permission-class grammar), `:175-182` (`iter_markdown`), `:226-259` (`check_skills`), `:484-603` (`check_artifact_validator`), `:605-613` (`validate`), `:614-652` (`self_test`).
- `plugins/rpa/hooks/run_gate.py:19-22`, `plugins/rpa/hooks/test_run_gate.py:1-40`, `plugins/rpa/hooks/README.md:34-38`.
- `plugins/rpa/skills/research-codebase/evals/public/preflight.py:23` (`HERE`), `:5999-6015`, `runner.py:9008`, `:9103-9104`; `evals/public/README.md:84-90`.
- `.github/workflows/ci.yml:8-12`, `:27-37`, `:39-49`, `:77-86`.
- Branch protection: `gh api repos/dsmolchanov/rpa/branches/master/protection/required_status_checks` (2026-08-21); contexts owned by `plaintalk-dev-agent` `scripts/bootstrap-dsmolchanov-repo.sh:206`.
- `README.md:59-76`, `:78-105` (install layouts incl. Codex plugin).
- `plugins/rpa/.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json:12`.

## Enhancement History

### 2026-08-21 Enhancement

**Feedback considered**:

- Review round 2 (conversational, nine P1 findings + four additional fixes):
  receipts not bound to phase/case; artifact gate open in CI; new CI jobs not
  required checks; JUnit grammar admits false Red/Green; receipt hash lost on
  export and secrets persisted; store under `.git/` outside authority and
  Codex sandbox, `fcntl`-only lock, no path containment; execution not
  crash-safe or bounded; freshness/diff bypassable; run lifecycle open; E2E
  dry run uses `exit != 0` as Red; VL coverage gaps; no install-layout
  resolver; preflight repair as a prerequisite PR.

**Decisions**:

- Accepted: causal binding — `--phase`/`--case` required, `--requires`
  validated for phase/case/outcome/order, validator disposition check
  rewritten; grounded in `SKILL.md:65-77` (Green needs valid Red for *each*
  behavior).
- Accepted: artifact gate — committed logs discovered and validated in
  `validate_docs.py`; legacy exemption `not_applicable` because
  `thoughts/shared/tests/` is absent at baseline (verified); schema marker
  `**Evidence schema**: tdd/1` added to the header.
- Adapted: required CI gates — verified protection requires exactly
  `lint,unit,integration,e2e,coverage,codex-review-window` and the list is
  owned by dev-agent bootstrap (`bootstrap-dsmolchanov-repo.sh:206`), so the
  plan adds steps inside `unit` (tests + `validate_docs.py`) and `integration`
  (preflight) instead of new jobs or a protection change; `docs-validate`
  duplication kept deliberately.
- Accepted: JUnit semantics — exactly-one match, `<failure>`-only Red with
  `exit != 0`, `pass` needs `exit == 0` and no error/skipped, report produced
  by this run; bare `test … fail` dropped.
- Accepted: integrity/secrets — sanitise before persistence and hashing, raw
  stream digests retained, export verbatim, validator recomputes receipts;
  EV-11 rewritten accordingly.
- Accepted: storage authority — store moved to `<repo>/.rpa/evidence/`
  self-ignored, excluded from diff/scope; `permission-class` extended
  (grammar verified at `validate_docs.py:91-93`); portable `store_lock()`;
  path containment for `--report/--out/path/--scope/--plan`.
- Accepted: crash safety and bounds — durable pre-run record, recovery,
  partial-line truncation, streaming digest + ring tail, `--timeout` +
  process-group kill, lock released during execution; exit codes 4/130 added.
- Accepted: freshness — stored normalized selectors, empty scope refused,
  `HEAD` drift blocking under `--requires`, `red_inputs` convention, content-
  hash diff over the union of pre/post paths.
- Accepted: lifecycle — nonce in run id, no implicit resume, explicit
  `--resume` bound to plan sha and branch, `checkpoint final --achieved`
  seals, immutable export.
- Accepted: E2E dry run now uses `junit_stub.py` with a `fail-with` claim plus
  a negative `STALE` run; VL cases added; `<skill-dir>` resolver rule in
  SKILL.md plus EV-23 relocatability test.
- Accepted: preflight repair as prerequisite PR — Phase 0 becomes PR-A,
  Phases 1–3 PR-B; phase ordering unchanged.
- Adapted (self-consistency): `checkpoint` was named in Desired End State but
  absent from the tool's subcommand list and the validator — added the
  `checkpoint` record kind, capsule rules, EV-24, and a validator checkpoint
  check.

**Plan changes**:

- Frontmatter: `delivery` (two PRs). Overview/Desired End State/Key
  Discoveries/Exclusions rewritten for required-job CI, store location,
  causal binding, sanitisation, lifecycle.
- Current State: added permission-class, branch-protection ownership, absent
  `thoughts/shared/tests/`, fixtures-only binding, install layouts.
- Implementation Approach: all design decisions revised.
- Phase 0: `unit`/`integration` steps replace `plugin-tests`/`research-preflight`;
  protection-unchanged criterion added; PR-A.
- Phase 1: contract sections, tool functions/order of operations, shared
  `junit_stub.py`, EV-01…EV-24.
- Phase 2: validator checks with fence stripping, recomputation, chain and
  checkpoint checks; fixtures incl. tampered/unsealed exports; VL cases;
  `check_session_logs` CI discovery; fake-log negative criterion.
- Phase 3: `permission-class`, `<skill-dir>` rule, phase/case flags in process
  steps and gate rows, `Recovery capsule` row, schema marker, JUnit-based dry
  run with negative `STALE` run.

### 2026-08-21 Enhancement (round 3)

**Feedback considered**:

- Review round 3 (conversational, ten P1 findings + four additional areas):
  wrong preflight root (`HERE.parents[2]`); intent record cannot carry a PID
  before `Popen` and `recovered_by` references an unallocated ref; seal/export
  can overtake an in-flight execution; a Red-only session cannot be continued
  by a later Green session; CI discovery by H1 is fail-open; hollow logs pass
  vacuously; export path resolved twice (repo-relative vs log-relative);
  stand-in accepts `exit != 0` alone; `--report` can delete a source file; dry
  run seals before the negative run and needs a `git commit`; capsule lacks
  explicit next/open/blocked/not_applicable, hash binding, and demotes
  scope-less Green; run-id/`current` traversal; receipt proves only
  self-consistency and uncited attempts can be trimmed; Refactor step lacks
  `--case` and SKILL.md scope/acceptance text not updated.

**Decisions**:

- Accepted: preflight root — `HERE = Path(__file__).parent` (`preflight.py:23`)
  makes the skill root `HERE.parents[1]`; Phase 0 corrected.
- Adapted: WAL model — split durability from liveness: a pid-less intent
  record in the ledger plus a lease rewritten with the pid after `Popen`
  (refined again in round 4).
- Accepted: fail-closed seal/export — `run`/`checkpoint`/`export` exit 2 while
  a live lease exists (EV-25); dead leases are recovered first.
- Adapted: cross-session cycle — one run spans the whole cycle; `--resume`
  works for open runs across sessions (bound to plan sha and branch, per
  `SKILL.md:77-78` "auditable prior phase"); `export` allowed for open runs
  with prefix-extension immutability. `--requires` stays same-run, which is
  what makes the chain checkable.
- Accepted: discovery — union of the contract's mandatory file-name shape
  (`session-log-contract.md:5`) and H1; the validator checks the H1; orphan
  exports under `receipts/` fail.
- Accepted: non-vacuity and coverage — exports are always the whole ledger,
  gaps rejected, hollow and uncited-attempt fixtures; the valid fixture is a
  complete export, never trimmed.
- Accepted: export path — log-relative `receipts/<run-id>.json` (tightened to
  an exact path in round 4).
- Accepted: stand-in — the pair `exit != 0` + `contains "<cause literal>"`,
  marked in the test plan.
- Adapted: `--report` — run-owned scratch (`runs/<id>/reports/`) with a
  `{report}` argv token; explicit paths only when non-existent or run-owned;
  tracked or foreign files refused; `run` never deletes what it did not
  create (EV-13).
- Accepted: dry run — open export before seal, prefix re-export after seal,
  negative drift and sealed-run checks in a throwaway repo, no `git commit`
  (`SKILL.md:31`).
- Accepted: capsule — explicit Verified/Open/Blocked/Not applicable/Next
  sections with `checkpoint` flags, snapshot-then-record transaction,
  `ledger_head`/`ledger_sha256`/`capsule_sha256` binding; scope-less evidence
  inherits its `requires` chain's scopes and is demoted only when those drift.
- Accepted: identifier containment — run-id regex for `--resume`, `current`,
  and store paths.
- Adapted: receipt semantics — stated plainly as a non-goal (no remote
  attestation); fabrication resistance rests on complete, contiguous,
  cross-checked ledgers plus `report_sha256`/`post_worktree_digest` in the
  record.
- Accepted: Refactor `--case`; SKILL.md scope & authority (`:26-31`) and
  acceptance criterion 5 (`:131-132`) updated; `run in progress` escalation.

**Plan changes**:

- Current State: `HERE` evidence, `SKILL.md:26-31`/`:77-78`/`:131-132`,
  contract path line; Exclusions: no remote attestation, no `git commit` in
  verification.
- Implementation Approach: identifier containment, lease, cross-session
  lifecycle, intent/terminal/checkpoint record fields, recovery protocol,
  reports and `{report}` token, stand-in rule, inherited scopes, capsule
  sections/transaction/binding, export prefix immutability for open runs.
- Phase 0: `HERE.parents[1]`.
- Phase 1: tool functions and `run` order of operations (lease lifecycle),
  EV cases revised, EV-25 added.
- Phase 2: log-relative export rule; checks incl. ledger integrity,
  non-vacuity, coverage, stand-in pair, capsule binding; fixtures incl.
  hollow/uncited/trimmed; discovery by file name ∪ H1 and orphan-export
  check; negative criteria updated.
- Phase 3: session-log header `receipts/<run-id>.json`, resume/seal/export
  guidance, SKILL.md scope/acceptance text, Refactor `--case`, `{report}`
  usage, dry run re-sequenced with throwaway-repo negative run.

### 2026-08-21 Enhancement (round 4)

**Feedback considered**:

- Review round 4 (conversational, fourteen P1 blockers grouped by the
  reviewer as state machine/WAL, provenance/phase causality, validator
  completeness, authority/security): per-run lease allows cross-run writers
  and `pid:null` is undefined; recovery not idempotent and `recovered_by_n`
  impossible for `export`; checkpoint is four durable writes without a full
  repair protocol and the last checkpoint/`achieved` are not hash-covered;
  phase machine not tied to events; freshness fail-open (optional Red scopes,
  descendant scopes replace ancestors, no post-run check); no minimum claim
  (vacuous `PASS`); `{report}` substitution contradicts the `--junitxml=`
  examples; intent written before sanitisation and split-form credentials
  not redacted; export path binding bypassable (`..`, absolute, symlink, HTML
  comments); one-way intent/terminal pairing; case completeness vacuous and
  test plan not bound; completion lifecycle inconsistent (`Green` + Refactor
  N/A, `Blocked`, `Summary` vs `run.achieved`); `.rpa/.gitignore` outside
  authority and `RPA_EVIDENCE_DIR` can blind diff/scope; production binding
  has no permanent self-test.

**Decisions**:

- Adapted: lease — one worktree-wide `active.json` keyed on the controller
  pid + start token, written before `Popen`, child pid informational; any
  live lease blocks `run`/`checkpoint`/`export` for every run (EV-25 a–c).
- Accepted: idempotent repair — terminal-first reconciliation, one
  `interrupted` per orphan, `recovered_by: {command, at_utc}` (no `n`),
  repair on `export` too, repeated repair is a no-op (EV-15 a–e).
- Adapted: checkpoint transaction — snapshot-then-record with the record as
  commit point; `run.json` demoted to a derived index rebuilt by repair;
  `current.md` derived; checkpoint records carry their own receipt so the last
  one is covered; `state`/`achieved`/`phase` derived from the ledger and
  cross-checked by the validator (d).
- Accepted: phase machine — admitted phases per state, non-decreasing
  re-checkpoint, "every P attempt precedes the last `checkpoint P`", `final`
  last; enforced at write time (EV-26) and by validator check (l).
- Accepted: freshness — `red_inputs` + `plan` mandatory for Red, envelope =
  union of own and ancestral scopes + head/branch/plan, checked before and
  after each run (post-drift → `STALE`), branch/plan checked by `checkpoint`
  and `export` (EV-22, EV-27).
- Accepted: prediction gate — at least one machine-checkable `--expect`
  required before any write (EV-08, EV-12).
- Accepted: `{report}` — substring substitution inside every argv element
  (EV-02); Jest note corrected to its env-var/config reality.
- Accepted: sanitised intent — intent payload built from redacted values
  before append, raw argv in memory only; split-form pattern added (EV-11).
- Accepted: export binding — exact layout (`log.parents[3]` root, export at
  `receipts/<header run id>.json` by realpath, no overrides); CommonMark HTML
  comments/blocks and indented code excluded; traversal/absolute/symlink/HTML
  fixtures (VL-10, VL-25…27, VL-30).
- Accepted: pairing — each `n` is one checkpoint or exactly one intent + one
  terminal with identical immutable fields; intent-deleted, duplicate-
  terminal, ref-mismatch fixtures (VL-18…20).
- Accepted: case completeness — `**Test Plan**` bound to `run.plan_path` +
  `plan_sha256`; planned set from the plan's §3 tables == disposition set,
  ledger cases ⊆ planned (VL-23, VL-24).
- Accepted: completion lifecycle — `**Cycle state**: continuing|complete|
  blocked` in the Summary with sealed/final/achieved/Refactor-N/A consistency
  rules (check (m), VL-21, VL-22); grounded in `SKILL.md:92-95`.
- Accepted: authority — ignore file moved to `.rpa/evidence/.gitignore`,
  foreign content never overwritten, `RPA_EVIDENCE_DIR` must be outside the
  repo (EV-06, EV-18).
- Accepted: permanent binding — the validator is resolved from the real repo
  (`SESSION_LOG_VALIDATOR`), `check_session_logs` does not depend on the
  fixture root having the skill package, and `tests/fixtures/docs-validate/`
  gains positive content plus five negative discovery roots with `EXPECTED`
  texts (`validate_docs.py:614-652` pattern).

**Plan changes**:

- Overview/Desired End State/Key Discoveries/Exclusions: mandatory claim,
  worktree-wide lease, envelope pre/post, derived index, exact layout,
  permanent discovery fixtures, outside-only `RPA_EVIDENCE_DIR`.
- Implementation Approach regrouped into Store/authority/security, State
  machine/WAL, Provenance/phase causality; all affected decisions rewritten.
- Phase 1: function list (repair, rebuild_index, envelope, pair_records…),
  `run` order of operations, EV-02/06/08/11/12/14/15/18/22/24/25 revised,
  EV-26/27 added.
- Phase 2: layout binding, structural exclusions, checks (a)–(m), fixture
  cases as mini repo roots (≈30), VL-01…VL-30, `SESSION_LOG_VALIDATOR`,
  permanent self-test roots, criteria rewritten.
- Phase 3: session-log `Cycle state`, one-row-per-planned-case rule, exact
  export header, SKILL.md steps/escalations, dry run extended (re-checkpoint,
  lease) and `--out={report}` form.
