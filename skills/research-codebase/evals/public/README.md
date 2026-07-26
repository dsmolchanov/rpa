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

Capability → proof map (each is a named preflight check):

| Capability (plan, prereq 5) | Runner mechanism |
|---|---|
| Installation-hash verification | `hash_tree` + `verify_installation` before every run |
| Per-node model/effort capture | transcript nodes carry `model`; effort pinned in config; `validate_models` invalidates mismatched runs |
| Clean profile | fresh per-run `CLAUDE_CONFIG_DIR` containing only `settings.json` |
| Infra vs workflow failure | `InfraFailure` (crash/unparseable → rerun) vs `WorkflowFailure` (timeout/no artifact → counted, never replaced) |
| Tree-wide accounting | `account()` sums tokens/tool calls per node, main vs subagent subtotals |
| Anonymization | scored copy gets random run id + masked fingerprint frontmatter |
| Fresh pinned judge sessions | `score()` = one new session + profile per judge call, uniqueness asserted |

The mock-backed preflight proves the harness mechanics; a **real-backend
preflight** (same throwaway task, `backend_cmd` set to the pinned `claude`
CLI) must pass once before any baseline run — see the pilot plan sequence.

## Dev set

See `dev-set/README.md`. Public tasks (target: this repository) are
committed there; tasks targeting private repositories live in the private
eval workspace per the plan's privacy rule.
