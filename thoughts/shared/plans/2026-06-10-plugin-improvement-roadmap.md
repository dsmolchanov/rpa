---
date: 2026-06-10
type: improvement-roadmap
scope: entire rpa plugin (commands, agents, hooks, packaging)
status: phases 0-4 complete (one e2e verification item open in 3.8)
---

# RPA Plugin Improvement Roadmap

One-by-one improvement plan for every command, agent, and packaging concern in the plugin, with explicit deduplication against native Claude Code capabilities.

## Current State (verified 2026-06-10)

- **25 commands** in `commands/` (7 AI-DLC, 11 RPA core, 3 testing, 4 refactoring/debt)
- **33 agents** in `agents/` (incl. `test-refactorer`, added today)
- **Hooks**: `hooks/hooks.json` (PostToolUse, Stop) + tech-debt hooks doc
- **Stale mirror**: `.agent/workflows/` duplicates 17 commands + 21 agents (diverged; missing all AI-DLC and newer test agents)

## Phase 0 — Completed Today

- ✅ `agents/test-refactorer.md` created (promised in 2025-12-28 plan, Phase 2.5)
- ✅ `/test_suite standardize [apply]` subcommand implemented
- ✅ `/test_suite adopt [apply]` subcommand implemented (promised in plan, Phase 0.5); `init` now defaults to adopt when tests exist
- ✅ Frontmatter added to `commit`, `debug`, `validate_plan`, `create_handoff`
- ✅ Broken script path fixed in `research_codebase.md` (`~/.claude/hack/` → `~/.claude/scripts/` with manual fallback)
- ✅ README: command table completed (+7 commands), directory structure regenerated (33 agents, grouped)

## Native Overlap Matrix

Native = built into current Claude Code (skills, agents, tools). Verdict legend: **KEEP** (distinct value), **INTEGRATE** (delegate part of the job to native), **RETIRE?** (candidate for removal — needs owner decision).

| Plugin asset | Native counterpart | Overlap | Verdict |
|---|---|---|---|
| `/create_plan`, `/iterate_plan` | Plan mode + `Plan` agent | Native plans are ephemeral; plugin persists iterable docs in `thoughts/shared/plans/` | **KEEP** — persistence is the value |
| `/research_codebase` | `Explore` agent | Native explores ad-hoc; plugin writes durable research docs | **KEEP**, but spawn `Explore` internally for breadth sweeps instead of N locator calls |
| `codebase-locator`, `codebase-pattern-finder` | `Explore` agent | High — native Explore does locate+excerpt | **KEEP** for plugin portability, but commands may use `Explore` when available; document this |
| `file-analyzer` | `Explore` / plain Read | High; agent is orphaned (0 command references) | **INTEGRATE** into `/debug` and `/test_suite run` (log analysis) or **RETIRE?** |
| `web-search-researcher` | `deep-research` skill + WebSearch | High; agent referenced by zero commands | **RETIRE?** or wire as optional research step in `/create_plan` |
| `/validate_plan` | `/code-review` | Complementary: plan-conformance vs diff-quality | **INTEGRATE** — final step should suggest running `/code-review` for diff quality instead of duplicating it |
| `/refactor` | `/simplify` | Different altitude: structural decomposition vs local diff cleanups | **KEEP**; add boundary note ("small-scale → /simplify") |
| `config-auditor` (credential detection) | `/security-review` | Partial — secrets detection | **KEEP** focused on config externalization; defer security findings to `/security-review` |
| `/commit` | Harness git conventions | Conflict: plugin forbids co-author lines; harness adds them | **KEEP**, resolve the convention conflict explicitly (see Phase 2) |
| `parallel-worker` | Native parallel `Agent` calls + `Workflow` tool | Medium — native orchestration is now first-class | **KEEP** for plugin portability; document native alternative |
| `/test_suite run`, `test-runner` | `/run`, `/verify` | Low — native targets the app, plugin targets test frameworks | **KEEP** |
| `/debug` | none | — | **KEEP** |
| `/tdd`, `/create_test_plan`, `/test_suite` | none | — | **KEEP** (core differentiator) |
| `/tech_debt_*`, refactor agent fleet | none | — | **KEEP** (core differentiator) |
| `/aidlc_*` family | none | — | **KEEP** (unique) |
| `/create_handoff`, `/resume_handoff` | session resume/compaction | Low — handoffs are cross-machine/cross-person | **KEEP** |
| Name collisions: `verify`, `debug`, `commit` | native `/verify`; generic names | `verify` skill name collides with native verify | Always reference plugin versions as `rpa:<name>`; consider renaming any plugin-level `verify` |

## Phase 1 — Hygiene (low risk, do first)

1. ✅ **Frontmatter completion** — DONE 2026-06-11: `argument-hint` added to all 7 commands.
2. ✅ **Resolve `.agent/workflows/` drift** — RESOLVED 2026-06-11: owner chose deletion; `.agent/` removed.
3. ✅ **Orphan `file-analyzer`** — DONE 2026-06-11: wired into `/debug` (log-analysis Task + large-output rule) and `/test_suite run` (verbose output digestion).

## Phase 2 — Dedup against native (medium)

4. ✅ **`/commit` convention conflict** — DONE 2026-06-11: documented as a deliberate override; repo-local conventions win over the command.
5. ✅ **`/validate_plan` → `/code-review` handoff** — DONE 2026-06-11: scope note added (plan conformance only), report renamed to "Plan Conformance Findings" with a `/code-review` next step, workflow updated.
6. ✅ **`web-search-researcher`** — RESOLVED 2026-06-11: wired into `/create_plan` (external-context research block) and `/research_codebase` (trigger broadened to external-library/API questions).
7. ✅ **Document native-vs-plugin boundaries** — DONE 2026-06-11: "When to Use Plugin vs Native Claude Code" section added to README.

## Phase 3 — Per-command improvements (one by one)

Ordered by value; each item is independently shippable.

8. ✅ **`/test_suite`** — DONE 2026-06-12: manifest filename unified to `test-suite-manifest.json` everywhere. *Still open: end-to-end run of `adopt`/`standardize` on a real fragmented repo.*
9. ✅ **`/tdd`** — DONE 2026-06-12: patterns/anti-patterns catalog extracted to `docs/testing-patterns.md` (shared with `/create_test_plan`, `/test_suite`); command now 641 lines (from 829) with a compact pointer + non-negotiable rules.
10. ✅ **`/create_plan` family** — DONE 2026-06-12: all 5 commands now state the bold names are `subagent_type` values and include an explicit Task block example.
11. ✅ **`/implement_plan`** — DONE 2026-06-12: checkpoint-commit step added (one commit per verified phase, `/commit` conventions).
12. ✅ **`/refactor`** — DONE 2026-06-12: per-phase validation now spawns `refactor-validator` with the explicit persisted baseline path.
13. ✅ **`/tech_debt_sweep`** — DONE 2026-06-12: `metrics_schema: 1` field added + stable-contract note; `/tech_debt_trends` got drift-detection rules (missing field = v1, mixed versions compare shared keys, unknown versions skipped).
14. ✅ **`/debug`** — DONE 2026-06-12: transcript source added (`~/.claude/projects/.../*.jsonl`, digested via file-analyzer); file-analyzer integration done in Phase 1.
15. ✅ **AI-DLC thin agents** — DONE 2026-06-12: tailored "Edge Cases" sections added to all five (missing state, missing overlay, partial plans, re-run behavior, ERROR-vs-FAIL distinction).
16. ✅ **`/create_test_plan`** — DONE 2026-06-12: declared plan-only (never creates files), execution handoff to `/tdd` or `/test_suite init apply`, scope-boundary table added.

## Phase 4 — Packaging & distribution

17. ✅ **README "How Hooks Work"** — DONE 2026-06-12: prose section added documenting all three hooks (PostToolUse prettier, Stop lint, Stop related-tests), plugin vs manual installation (merge into `settings.json`, not `~/.claude/hooks/`), npm/Jest-centric caveats. Misleading `cp hooks/*.json ~/.claude/hooks/` install snippet and directory tree corrected.
18. ✅ **Skills migration (optional)** — EVALUATED 2026-06-12, verdict: **defer**. The concrete benefit skills offer (bundled supporting files) is already achieved — the `/tdd` pattern catalog lives at `docs/testing-patterns.md` and is referenced by path from three commands. Migration would fragment the flat `commands/*.md` layout the Quick Install copy flow depends on. Revisit only if a command needs per-skill supporting files that can't live in `docs/`.
19. ✅ **Marketplace metadata** — DONE 2026-06-12: `plugin.json` now has `version: 1.0.0`, `homepage`, `repository`, and 8 keywords. No explicit command/agent registries added (auto-discovery).
20. ✅ **Test-suite plan closure** — DONE 2026-06-12: status banner added to `2025-12-28-test-suite-command.md` plus per-phase "Implemented 2026-06-11" notes on Phases 0.5/2.5. Success-criteria checkboxes deliberately left unchecked — they require the e2e run tracked as item 3.8.

## Decisions Needed From Owner

| # | Question | Recommendation |
|---|---|---|
| 1 | ~~Delete `.agent/workflows/` mirror or add sync script?~~ | ✅ Deleted (2026-06-11) |
| 2 | ~~Retire `web-search-researcher` or wire into plan/research commands?~~ | ✅ Wired in (2026-06-11) |
| 3 | ~~`/commit` attribution policy: repo rule vs harness default?~~ | ✅ Documented as explicit override (2026-06-11) |
| 4 | ~~Migrate big commands to `skills/` format?~~ | ✅ Evaluated, deferred (2026-06-12) — see Phase 4 item 18 |
