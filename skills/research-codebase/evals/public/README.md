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

Capability → proof map (each row is backed by named preflight checks; 36 checks total):

| Capability (plan, prereq 5) | Runner mechanism |
|---|---|
| Installation-hash verification | `hash_tree` + `verify_installation` before every run; the verified copy is **mounted into the profile** and its path passed to the backend via the `{installation}` placeholder in `backend_cmd` |
| Workflow entrypoint invocation | the arm's `entrypoint` (e.g. `/research_codebase`) is prefixed to the extracted task prompt, so the session enters the evaluated workflow rather than answering bare |
| Real Claude stream schema | `parse_transcript` understands both the synthetic mock schema and the real Claude headless stream (`assistant` events with usage/model nested in `message`, `tool_use` content blocks as tool calls, non-null `parent_tool_use_id` = subagent node) |
| Per-node model/effort capture | transcript nodes carry `model`; effort must be pinned via the `{effort}` placeholder in `backend_cmd` (a command without it is refused). Nodes reporting effort must match the registered value (`per_node` capture); the real Claude schema exposes no per-node effort, so an all-absent transcript is accepted on the strength of the mandatory pin (`command_pin` capture, recorded per run) — partial reporting is broken capture and invalidates the run |
| One runtime config across arms | `validate_arm_parity` refuses configs whose arms differ in model or effort before any run: installation content is the only permitted arm difference |
| Clean profile | fresh per-run `CLAUDE_CONFIG_DIR` containing only `settings.json` + the mounted installation |
| Worktree isolation | disposable detached `git worktree` at the task's pinned `target-sha`, verified clean and matching, removed after the run |
| Prompt extraction | only the `## Task prompt` section reaches the session; the marker is required unconditionally — any task without it is refused, never sent whole |
| Infra vs workflow failure | `InfraFailure` (crash/unparseable/wrong sha) is invalid and **automatically re-executed** (`run_task_with_retries`, bounded by `max_infra_retries`) vs `WorkflowFailure` (timeout/no artifact/registered abort exit → counted, never replaced); `workflow_abort_exit_codes` registers backend exits that mean the workflow itself gave up; failed-run records preserve tree-wide accounting, including nodes harvested from the partial transcript of a timed-out or aborted session |
| Tree-wide accounting | `account()` sums tokens/tool calls per node, main vs subagent subtotals |
| Artifact freshness | pre-run snapshot of `thoughts/shared/research/`; only new/modified docs count |
| Anonymization | scored copy gets random run id + masked fingerprint frontmatter; score mode enforces blinding at its own boundary — raw `run-*-raw.md` artifacts and any document with unmasked fingerprint fields are refused |
| Fresh pinned judge sessions | `--score` = one new session + profile per judge call via `judge_backend_cmd` (must be **mount-free** — an `{installation}` placeholder in the judge command is refused); judge model/effort pinned via `judge_model`/`judge_effort` and validated per node; the judge's **full response text is preserved** as `judge-<scoring_id>-<n>.json` — the per-invocation id keeps separate scorer/verifier passes from overwriting each other |
| Judge isolation | each judge runs rooted **outside the experiment tree** in an empty working directory, and its profile denies filesystem/exec/web tools (`JUDGE_SETTINGS`), so an unsandboxed judge cannot read run artifacts and unblind itself |

CLI:

- run:   `runner.py --config C --arm A --task T.md --repo /path/to/clone`
- score: `runner.py --config C --score --docs D1.md D2.md --judge-prompt J.md`
- preflight: `runner.py --preflight`

The mock-backed preflight proves the harness mechanics; a **real-backend
preflight** (same throwaway task, `backend_cmd` set to the pinned `claude`
CLI) must pass once before any baseline run — see the pilot plan sequence.

## Dev set

See `dev-set/README.md`. Public tasks (target: this repository) are
committed there; tasks targeting private repositories live in the private
eval workspace per the plan's privacy rule.
