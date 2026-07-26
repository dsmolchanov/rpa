# Public eval harness assets

Non-sensitive assets only. Sealed materials — holdout tasks, ground-truth
notes for the holdout, external-source snapshots, the quality rubric, and
judge (scorer/verifier) prompts — must NEVER be committed here. They form
the sealed judge package that lives outside every evaluated plugin
installation (`docs/conventions.md` §1; pilot plan, "Atomic seal").

## Eval-runner (pilot plan, prerequisite 5)

- `runner.py` — the harness. `run` mode drives one arm on one task in a
  disposable worktree; `score` mode spawns fresh pinned judge sessions.
- `mock_claude.py` — deterministic mock backend with declared accounting
  and selectable failure modes.
- `preflight.py` — the synthetic preflight: proves every capability against
  the mock backend, offline (`python3 runner.py --preflight`).
- `runner-config.example.json` — configuration shape; the filled copy (real
  installation paths + hashes) lives in the private eval workspace.

Capability → proof map (each row is backed by named preflight checks; 60 checks total):

| Capability (plan, prereq 5) | Runner mechanism |
|---|---|
| Installation-hash verification | `hash_tree` + `verify_installation` for **every registered arm** before every run (drift in any arm halts the experiment); the selected arm's verified copy is **mounted into the profile** and its path passed to the backend via the `{installation}` placeholder in `backend_cmd` — a command without the placeholder is refused, so no arm can silently run a bare backend |
| Workflow entrypoint invocation | the arm's `entrypoint` (e.g. `/research_codebase`) is prefixed to the extracted task prompt, so the session enters the evaluated workflow rather than answering bare |
| Real Claude stream schema | `parse_transcript` understands both the synthetic mock schema and the real Claude headless stream (`assistant` events with usage/model nested in `message`, `tool_use` content blocks as tool calls, non-null `parent_tool_use_id` = subagent node); **all input-token categories** — fresh, cache creation, cache read — count toward tree-wide cost |
| Per-node model/effort capture | transcript nodes carry `model`; effort must be pinned via the `{effort}` placeholder in `backend_cmd` (a command without it is refused). Nodes reporting effort must match the registered value (`per_node` capture); the real Claude schema exposes no per-node effort, so an all-absent transcript is accepted on the strength of the mandatory pin (`command_pin` capture, recorded per run) — partial reporting is broken capture and invalidates the run. This two-mode policy is registered in the pilot plan (prereq 5); the real-backend preflight must demonstrate the pinned CLI applies the effort flag to the whole session tree |
| One runtime config across arms | `validate_arm_parity` refuses configs whose arms differ in model, effort, or workflow `entrypoint` before any run (a shared non-empty entrypoint is required): installation content is the only permitted arm difference |
| Clean profile | fresh per-run `CLAUDE_CONFIG_DIR` containing only `settings.json` + the mounted installation |
| Worktree isolation | disposable detached `git worktree` at the task's pinned `target-sha`, verified clean and matching, removed after the run; destinations are resolved to absolute paths before reaching git, so a relative `--output` cannot split the worktree between two locations |
| Prompt extraction | only the `## Task prompt` section reaches the session; the marker is required unconditionally — any task without it is refused, never sent whole |
| Config hygiene | `max_infra_retries` is validated as a nonnegative integer (classified infra failure, not an IndexError/ValueError crash); unknown `--arm` values are refused with the configured arm list |
| Infra vs workflow failure | `InfraFailure` (crash/unparseable/wrong sha) is invalid and **automatically re-executed** (`run_task_with_retries`, bounded by `max_infra_retries`) vs `WorkflowFailure` (timeout/no artifact/registered abort exit → counted, never replaced); `workflow_abort_exit_codes` registers backend exits that mean the workflow itself gave up; failed-run records preserve tree-wide accounting, including nodes harvested from the partial transcript of a timed-out or aborted session — those partial nodes are validated for model/effort parity first, so runtime drift invalidates the run (infra) instead of counting as a workflow outcome, and a failure whose run produced NO accounting nodes in any session is invalidated outright — a counted failure requires effective-runtime parity evidence. `timeout_seconds` is a **run-level deadline** shared by the initial session and every continuation — a per-session reset would grant stop-prone arms extra compute |
| Tree-wide accounting | `account()` sums tokens/tool calls per node, main vs subagent subtotals, plus `subagents_spawned` — a count of **distinct** subagent identities (several messages from one subagent ≠ several subagents) |
| Pre-registered run schedule | `--make-schedule` emits a balanced, seed-recorded randomized interleaving of arm × task × replicate. The protocol fixes **exactly 3 replicates** per cell (other counts require an explicit nonstandard mark — dev-set tuning only, never holdout), and a no-subagent ablation arm must be **explicitly scoped to exactly its two designated tasks** via `schedule_tasks`. `--run-schedule` **reconstructs** the expected schedule from the registered config, the operator-supplied `--tasks` set, and the recorded seed — the file's own arms/tasks/entries are never trusted — executes in recorded order, **persists progress to the manifest after every entry**, and resumes an interrupted schedule at the first unfinished entry. The schedule also carries a **digest of the whole registered runtime configuration** (arm models/efforts/entrypoints/hashes, backend command + version, judge pins, retry/timeout policy); a uniform config change after registration — which arm parity alone cannot see — is refused on resume |
| Ablation no-subagent policy | an arm with `forbid_subagents: true` (the fleet-ablation third arm) fails as a counted workflow failure if its run spawned any subagent, so third-arm differences stay attributable to fleet removal |
| Ritual-stop capture | every pre-artifact response is preserved verbatim in `interventions_log` and mechanically tagged (`question`/`statement`/`empty`), so ritual stops stay countable against the zero-ritual-stop pass bar |
| Artifact freshness | pre-run snapshot of `thoughts/shared/research/`; only new/modified docs count |
| Anonymization | scored copy gets random run id + masked fingerprint frontmatter; score mode enforces blinding at its own boundary — raw `run-*-raw.md` artifacts and any document with unmasked fingerprint fields are refused |
| Fresh pinned judge sessions | `--score` = one new session + profile per judge call via `judge_backend_cmd` (must be **mount-free** — an `{installation}` placeholder in the judge command is refused); judge model/effort pinned via `judge_model`/`judge_effort` and validated per node; the judge's **full response text is preserved** as `judge-<scoring_id>-<n>.json` — the per-invocation id keeps separate scorer/verifier passes from overwriting each other |
| Pinned backend version | the exact Claude Code version is registered (`backend_version` + `backend_version_cmd`) and probed before every run and before **every judge session** (per document, recorded in each judge result); version drift between interleaved entries or mid-scoring-batch blocks the run |
| Judge isolation (two roles) | each judge runs rooted **outside the experiment tree**. Blind **scorers** get an empty working directory with filesystem/exec/web tools denied (`JUDGE_SETTINGS`) so they cannot unblind themselves; evidence **verifiers** (`--evidence-repo` + `--evidence-sha`) get a disposable read-only worktree of the frozen evidence at the pinned sha with read-only inspection tools allowed (`VERIFIER_SETTINGS`), so file-and-line citations can actually be checked |

CLI:

- run:   `runner.py --config C --arm A --task T.md --repo /path/to/clone`
- score (blind scorer): `runner.py --config C --score --docs D1.md D2.md --judge-prompt J.md`
- score (evidence verifier): add `--evidence-repo /path/to/frozen-clone --evidence-sha <target-sha>`
- schedule: `runner.py --config C --make-schedule --tasks T1.md T2.md --replicates 3 --seed S --schedule-out schedule.json`, then `runner.py --config C --run-schedule schedule.json --repo /path/to/clone --tasks T1.md T2.md` (the same registered task set, revalidated)
- preflight: `runner.py --preflight`

The mock-backed preflight proves the harness mechanics; a **real-backend
preflight** (same throwaway task, `backend_cmd` set to the pinned `claude`
CLI) must pass once before any baseline run — see the pilot plan sequence.

## Dev set

See `dev-set/README.md`. Public tasks (target: this repository) are
committed there; tasks targeting private repositories live in the private
eval workspace per the plan's privacy rule.
