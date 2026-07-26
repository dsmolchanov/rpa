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

Capability → proof map (each is a named preflight check; 19 checks total):

| Capability (plan, prereq 5) | Runner mechanism |
|---|---|
| Installation-hash verification | `hash_tree` + `verify_installation` before every run; the verified copy is **mounted into the profile** and its path passed to the backend via the `{installation}` placeholder in `backend_cmd` |
| Per-node model/effort capture | transcript nodes carry `model`; effort pinned in config; `validate_models` invalidates mismatched runs |
| Clean profile | fresh per-run `CLAUDE_CONFIG_DIR` containing only `settings.json` + the mounted installation |
| Worktree isolation | disposable detached `git worktree` at the task's pinned `target-sha`, verified clean and matching, removed after the run |
| Prompt extraction | only the `## Task prompt` section reaches the session; ground-truth-bearing files without the marker are refused |
| Infra vs workflow failure | `InfraFailure` (crash/unparseable/wrong sha → rerun) vs `WorkflowFailure` (timeout/no artifact → counted, never replaced) |
| Tree-wide accounting | `account()` sums tokens/tool calls per node, main vs subagent subtotals |
| Artifact freshness | pre-run snapshot of `thoughts/shared/research/`; only new/modified docs count |
| Anonymization | scored copy gets random run id + masked fingerprint frontmatter |
| Fresh pinned judge sessions | `--score` = one new session + profile per judge call, uniqueness asserted; the judge's **full response text is preserved** as `judge-<n>.json` |

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
