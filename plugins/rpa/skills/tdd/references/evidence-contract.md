# TDD evidence contract — single source

This file defines the evidence kernel used by the `tdd` workflow: the claim
grammar, the freshness envelope, the record model and pairing rule, the lease,
repair and checkpoint protocols, the phase machine, the store layout,
sanitisation and containment rules, the capsule, and the export schema.
`scripts/evidence.py` implements it; `scripts/validate_session_log.py` checks
artifacts against it; every other document links here instead of restating it.

## Purpose

Before a load-bearing test run, record the state it is valid for, the expected
effect, and the invariants that must hold; afterwards persist exact evidence;
continue only while reality matches the contract. A session log cites
receipts produced this way instead of hand-transcribed commands.

Invoke the tool as `python3 <skill-dir>/scripts/evidence.py …`, where
`<skill-dir>` is the directory containing the `SKILL.md` you loaded (plugin
cache, `~/.claude/skills/tdd`, or the Codex plugin directory — every install
layout ships the package verbatim). The tool imports nothing outside its own
directory.

## Store, authority, and security

- **Location**: `<repo root>/.rpa/evidence/` (per worktree). `begin` creates
  it with `.rpa/evidence/.gitignore` containing exactly `*`, so the store is
  invisible to git without touching the repository's `.gitignore` or anything
  else under `.rpa/`. An existing `.gitignore` there with different content is
  never overwritten (`begin` exits 2). Every status/scope/diff computation
  drops paths under the store root.
- **`RPA_EVIDENCE_DIR`** may relocate the store only to a realpath **outside**
  the repository (not the root, an ancestor, or a descendant); anything else
  exits 2.
- **Layout**: `runs/<run-id>/events.jsonl` (append-only ledger — the only
  authoritative state), `runs/<run-id>/run.meta.json` (immutable identity
  written once by `begin`), `runs/<run-id>/run.json` (derived index, rebuilt
  from meta + ledger by every repair), `runs/<run-id>/reports/` (run-owned
  scratch for JUnit reports), `runs/<run-id>/capsules/` (immutable snapshots
  plus derived `current.md`), `current` (active run id), `lock`, `active.json`
  (the worktree-wide execution lease, present only while a command is in
  flight).
- **Identifier containment**: run ids match
  `^tdd-\d{8}-\d{6}-[0-9a-f]{8}-[0-9a-f]{6}$`; `--resume`, the content of
  `current`, and every `runs/<id>` path are validated against that regex and
  resolved inside the store before any I/O. Event refs are `<run-id>#<n>`.
- **Path containment**: `--report`, `--out`, `path <p>` claims, `--scope`
  globs, and `--plan` must resolve (after symlinks) inside the repository
  root; scope globs and path claims must be repo-relative without `..`.
- **Sanitisation before any persistence**: every string is passed through
  `redact()` before it is written anywhere — the intent record is built from
  already-sanitised `argv`, `because`, claim texts, `report_path`; raw argv
  exists only in memory for `Popen`; tails, claim details, and capsule text
  are sanitised before write. Patterns (all → `[REDACTED]` unless noted):
  key/value `(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*\S+`;
  split-form flag `(?i)--?(api[_-]?key|token|secret|password|passwd|pwd)`
  followed by a value (the *next* argv element, or the next token inside one
  string, becomes `[REDACTED]`); `Bearer\s+\S+`; `sk-[A-Za-z0-9_-]{10,}`;
  `gh[pousr]_[A-Za-z0-9]{20,}`; `AKIA[0-9A-Z]{16}`. Raw streams are never
  persisted; their integrity is kept as `stdout_sha256`/`stderr_sha256` over
  the raw bytes plus byte counts.
- **Reports** (`--report <name-or-path>`): a bare name (no path separator)
  resolves to `runs/<run-id>/reports/<name>` — run-owned scratch — and the
  literal substring `{report}` is replaced by that absolute path inside
  **every** argv element (`--junitxml={report}`, `--outputFile={report}`, or a
  bare `{report}` element). An explicit path elsewhere is accepted only when it
  is contained in the repository **and** either does not exist or was produced
  by an earlier execution of this run; a git-tracked file, or an existing file
  the run does not own, is refused (exit 2). `run` never deletes a file it did
  not create. A pre-existing run-owned report is deleted before execution; a
  report missing afterwards grades `test` claims `ERROR` ("report not produced
  by this run"); `report_sha256` is recorded.
- **Execution**: `Popen(argv, shell=False, cwd=<repo root>, stdin=DEVNULL,
  start_new_session=True)`; two reader threads keep a streaming sha256, a byte
  count, a bounded ring tail (`--tail-bytes`, default 8192), and incremental
  `contains` matching over the **full** stream. Everything after `--` is the
  argv — no shell, no tokenization; `{report}` is the only substitution.
  `--timeout` (default 900 s): on expiry `SIGTERM` the process group, `SIGKILL`
  after 5 s, outcome `TIMEOUT` (exit 4). `KeyboardInterrupt` kills the group
  and records `INTERRUPTED` (exit 130). On Windows the fallback is
  `proc.kill()` (no process groups) and `msvcrt` locking.
- What a receipt proves: that the record is internally consistent and was
  produced by the tool on the checkout it names (raw-stream digests, report
  digest, pre/post worktree digests). It is not a remote attestation of who
  ran it. Fabrication resistance comes from the ledger being complete,
  contiguous, correctly paired, and cross-checked by the validator.

## State machine and WAL

- **Lock**: `store_lock()` (`fcntl.flock` on POSIX, `msvcrt.locking` on
  Windows) is held only around ledger mutations — repair, allocating `n`,
  appending records, rewriting `run.json`, the lease, and capsules — never
  across the subprocess.
- **Worktree-wide lease**: `active.json` = `{run_id, ref, controller_pid,
  start_token, started_at_utc, child_pid}`. Written under the lock **before**
  `Popen` with the `evidence.py` process as `controller_pid` and a fresh
  `start_token`; rewritten with `child_pid` right after `Popen`. The lease is
  live iff the controller is alive. While a live lease exists, `run`,
  `checkpoint`, and `export` on **every** run in the store exit 2
  (`execution in progress: <ref>`). The lease is removed under the lock
  together with the terminal record.
- **Run identity and lifecycle**: run id
  `tdd-YYYYMMDD-HHMMSS-<plan sha256[:8]>-<6 hex nonce>`. One run covers one
  test plan's whole Red → Green → Refactor cycle and may span sessions:
  `begin --plan <path>` creates a run and points `current` at it;
  `begin --resume <run-id>` resumes a run whose derived state is `open`,
  whose plan sha equals the current plan's, and whose branch equals the
  current branch — otherwise exit 2. A later session learns the run id from
  the session log's `**Evidence run**` header. `run.meta.json` holds the
  identity (`id`, `nonce`, `plan_path`, `plan_sha256`, `branch`, `head`,
  `started_at`); `run.json` adds the derived `state: open|sealed`,
  `achieved`, `sealed_at`, `phase`, `reports[]`, `records` and is rebuilt from
  the ledger by every repair — it is never trusted over the ledger.
- **Record model** (`events.jsonl`, one JSON object per line; every record has
  `ref`, `n`, `run`, `kind`, `at_utc`; `n` is contiguous from 1). Each `n` is
  exactly one of: (1) one `checkpoint` record; or (2) one intent record
  (`kind: started`) followed, at any later line with the same `ref`, by
  exactly one terminal record of kind `finished | error | interrupted |
  timeout`. The intent carries `workflow`, `phase`, `case`, `because`,
  `risk`, sanitised `argv`, `cwd`, `claims[].{text,kind}`, `scopes`,
  `envelope`, `requires`, `report_path`, `timeout`, `start_token`, `at`
  {`head`, `branch`, `plan_sha256`, `worktree_digest`}. The terminal record
  repeats every intent field verbatim and adds `controller_pid`, `child_pid`,
  `exit`, `started_at`, `finished_at`, `stdout_sha256`, `stdout_bytes`,
  `stdout_tail`, `stderr_sha256`, `stderr_bytes`, `stderr_tail`,
  `report_sha256`, `post_at`, `claims[].{text,kind,outcome,detail}`,
  `outcome`, `receipt` (and `recovered_by` when written by repair).
  `checkpoint` records carry `phase`, `achieved` (final only), `at`,
  `ledger_head`, `ledger_sha256`, `capsule_path`, `capsule_sha256`,
  `verified[]`, `open[]`, `blocked[]`, `not_applicable[]`, `next`, `receipt`.
- **Receipt id**: `sha256(canonical JSON of the record without "receipt")[:12]`
  over sanitised content; cited in logs as `receipt <hex12>`; recomputable
  from the export. Canonical JSON = `sort_keys`, separators `(",", ":")`.
- **Repair** (idempotent; first step of every mutating command, under the
  lock): truncate a trailing partial line; if a lease exists and its
  controller is alive → fail closed; if dead → when the ledger already has a
  terminal record for the lease's `ref` just delete the lease, otherwise kill
  the child's group if alive, append one `interrupted` terminal record
  (`outcome: INTERRUPTED`, `exit: null`, `recovered_by: {command, at_utc}`)
  and delete the lease; any intent without a terminal record and without a
  lease gets the same `interrupted` record; snapshot files no checkpoint
  record names are deleted; `run.json` and `current.md` are regenerated.
  Running repair again changes nothing. `status` is read-only and reports
  what repair would do.
- **Phase machine**: the run's state is the phase of its last checkpoint
  (`none` before the first). Admitted `run --phase` by state: `none` →
  `baseline`; `baseline` → `baseline|red`; `red` → `red|green|final`;
  `green` → `green|refactor|final`; `refactor` → `refactor|final`; `final`
  (sealed) → nothing. `checkpoint <phase>` is admitted when `phase` equals
  the current state or its successor in `baseline < red < green < refactor`
  (non-decreasing — a re-run Red after `checkpoint red` is closed by another
  `checkpoint red`); `checkpoint final --achieved <v>` is admitted from any
  state after `baseline`, with `--achieved red|green|refactored-green`
  requiring state ≥ `red|green|refactor` respectively (`blocked` from
  anywhere). Invariant: for every phase P with attempts, the last `checkpoint
  P` has a larger `n` than every P attempt — a checkpoint refuses while an
  earlier phase has attempts newer than its own last checkpoint; `checkpoint
  final` is the last record of a run.
- **Checkpoint transaction**: under the lock, after repair and the
  branch/plan check: build the capsule → write `capsules/<nnnn>-<phase>.md`
  via temp file + fsync + rename → append the checkpoint record carrying
  `capsule_path`, `capsule_sha256`, `ledger_head` (last `n` before it) and
  `ledger_sha256` (over records `1..ledger_head`) — the append is the commit
  point → rebuild `run.json` and regenerate `current.md`. Nothing is stored
  outside the ledger that repair cannot recompute.
- **Capsule** (≤ 120 physical lines, ≤ 16 KiB, truncated oldest-first with a
  `[+N older]` marker), sections in order: Run/Phase (id, state, branch, head,
  ledger_head, ledger_sha256); Verified (receipt-backed `PASS` records whose
  envelope is still fresh); Open (stale-envelope records, `PENDING` manual
  claims, `STALE` attempts, `--open` items); Blocked (`--blocked` items and
  cases whose last attempt is `ERROR`/`TIMEOUT`/`INTERRUPTED`); Not
  applicable (`--not-applicable` items); Surprises; State drift (HEAD,
  branch, plan, dirty paths); Next (`--next` or derived). `status` prints the
  same projection live and flags `capsule mismatch` / `index mismatch`.
- **Export** (`export [--out <path>]`, allowed for open and sealed runs):
  after repair and the branch/plan check, writes canonical JSON
  `{"schema": 1, "run": <derived index>, "exported_at", "records_through",
  "events": [<all records verbatim>], "capsules": [{"phase", "path", "text",
  "sha256"}]}` to `thoughts/shared/tests/receipts/<run-id>.json` by default.
  Immutability by prefix: an existing file's `events` and `capsules` must be a
  prefix of the new ones, otherwise exit 2 without writing; equal content
  leaves the file untouched. The export is always the whole ledger; nothing is
  transformed at export time.

## Provenance and phase causality

- **Required run inputs**: `--phase` (admitted by the phase machine);
  `--case <id>` for `red|green|refactor`; `--because "<why>"`; at least one
  machine-checkable `--expect` (a run with no claims, or only `manual` claims,
  exits 2 before any write — there is no vacuous `PASS`); for `--phase red`
  both `--scope red_inputs=<globs>` and `--scope plan=<test-plan path>`.
  `--workflow` (default `tdd`) and `--risk local_verify|local_mutate`
  (default `local_verify`, audit only — it grants nothing) are recorded.
- **Claim grammar v1** (graded independently; per-claim outcome
  `PASS | SURPRISE | ERROR | PENDING`; the run outcome is the worst
  machine-checkable claim outcome — `PENDING` manual claims never degrade it —
  or `STALE`/`TIMEOUT`/`INTERRUPTED` as a whole):
  - `exit == <N>` · `exit != 0`
  - `stdout contains "<literal>"` · `stderr contains "<literal>"` — over the
    full stream, not the tail.
  - `diff none` · `diff within <glob>[,<glob>…]` — pre/post snapshots are
    maps `path → sha256 | "deleted"` over the union of paths listed by `git
    status --porcelain=v1 -z --untracked-files=all` before and after (store
    root excluded); a path is changed when its hash differs or it appears/
    disappears — modifying an already-dirty file is detected. `within` passes
    when every changed path `fnmatch`es a glob against repo-relative paths.
  - `path <repo-relative> unchanged|created|absent` — sha256 before/after.
  - `test <selector> pass` · `test <selector> fail-with "<literal>"` —
    require `--report`; `<selector>` is a case-sensitive substring of
    `<classname>.<name>` and must match **exactly one** `<testcase>` (zero or
    several → `ERROR`). `pass` passes only when `exit == 0` **and** the
    testcase has no `<failure>`/`<error>`/`<skipped>` child. `fail-with`
    passes only when `exit != 0` **and** the testcase has a `<failure>` (not
    `<error>`) whose `message` or text contains the literal. There is no bare
    `test … fail` form.
  - `manual "<observable>"` → always `PENDING`; never `PASS`; never the
    required machine-checkable claim.
  - Free text is not a claim; an unparseable `--expect` exits 2 and nothing
    runs.
  - **Stand-in rule** (no JUnit available): a Red stand-in is the pair
    `exit != 0` **and** `stdout|stderr contains "<cause literal>"`, with the
    test-plan row marked `stand-in`; a Green stand-in is `exit == 0` plus the
    plan's named success literal if any. `exit != 0` alone is never Red.
- **Freshness envelope**: `begin` records `head`, `branch`, `plan_sha256`.
  Each `run` records `at` {`head`, `branch`, `plan_sha256`,
  `worktree_digest`} and `scopes[name] = {"globs": [normalized, sorted],
  "paths": <count>, "digest": sha256 over sorted matching paths + content
  hashes}`; a scope matching zero files exits 2. The record's **envelope** is
  the union of its own scopes and the envelope of its `requires` target
  (never narrowed; a colliding name with different globs is kept as
  `name@<ref>`) plus `head`/`branch`/`plan_sha256` — stored on the intent so
  later runs and the validator recompute it from the record alone.
  `--requires <ref>` (same run) must name a terminal record with `outcome:
  PASS`, a smaller `n`, the same `case`, and the phase the chain expects
  (`green` requires `red`; `refactor` requires `green` or `refactor`) —
  anything else exits 2 and nothing runs. **Before** the command the inherited
  envelope is recomputed: any scope, `HEAD`, branch, or plan drift → the run
  is recorded `STALE` and not executed (exit 3). **After** the command the
  whole envelope is recomputed again: any difference → `STALE` with detail
  `drift during execution` (exit 3). `checkpoint` and `export` refuse (exit 2)
  when branch or plan differ from the run's. TDD convention: `red_inputs`
  covers the test files executed, their fixtures/helpers, the test-runner
  config (`pytest.ini`, `pyproject.toml`, `jest.config.*`, `vitest.config.*`,
  …), and lockfiles; Green passes `--requires <Red ref>`; Refactor passes
  `--requires <Green ref>`.
- **Exit codes** (`run`): 0 all machine-checkable claims `PASS`; 1 any
  `SURPRISE`; 2 `ERROR` (usage, no machine-checkable claim, unparseable
  claim, missing mandatory Red scopes, empty scope, phase not admitted, bad
  `--requires` target, containment or identifier violation, report rule,
  missing/ambiguous report, command could not start, sealed run, execution
  in progress, branch/plan mismatch); 3 `STALE`; 4 `TIMEOUT`; 130
  `INTERRUPTED`. `begin`, `status`, `checkpoint`, `export`: 0 on success, 2
  on usage/store error/execution in progress.
- **Citation form** in session logs: `receipt <hex12>`; the exported receipt
  file is committed next to the log as `receipts/<run-id>.json`.

## Tooling compatibility

pytest: `--junitxml={report}`. Vitest: `--reporter=junit --outputFile={report}`.
Jest: the `jest-junit` reporter reads `JEST_JUNIT_OUTPUT_FILE` from the
environment or its config — run through `env JEST_JUNIT_OUTPUT_FILE={report}
npx jest …` or point the reporter config at `{report}`. Python `unittest` has
no built-in JUnit writer: run unittest cases through pytest, or use the
stand-in claim pair and say so in the session log; the same applies to
`cargo test` and `go test`.
