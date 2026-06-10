---
date: 2026-06-10
type: improvement-roadmap
scope: entire rpa plugin (commands, agents, hooks, packaging)
status: phases 0-2 complete; phases 3-4 pending
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

8. **`/test_suite`** — verify new `adopt`/`standardize` end-to-end on a real fragmented repo; align manifest filename (command references both `manifest.md` and `test-suite-manifest.json` — pick one).
9. **`/tdd` (829 lines)** — extract the testing patterns/anti-patterns catalog into `commands/shared/` or an agent doc; the command should orchestrate, not teach. Target <400 lines.
10. **`/create_plan` family** — convert prose agent mentions ("use codebase-locator…") into explicit Task blocks like `tech_debt_sweep` does; removes ambiguity about whether spawning is required. Applies to `create_plan`, `enhance_plan`, `enhance_research`, `iterate_plan`, `research_codebase`.
11. **`/implement_plan`** — add an explicit checkpoint step invoking `/commit` per completed phase; today commits are implied.
12. **`/refactor`** — wire `refactor-validator` to compare against `api-snapshotter` baselines explicitly per phase (the loop exists but the snapshot path contract is implicit).
13. **`/tech_debt_sweep`** — stabilize the YAML metrics block schema (trends depends on it); add schema version field so `tech_debt_trends` can detect drift.
14. **`/debug`** — integrate `file-analyzer` (Phase 1.3) and add a "recent Claude Code transcript" source alongside logs/db/git.
15. **AI-DLC thin agents** (`uow-decomposer`, `quality-gate-runner`, `operations-planner`, `feedback-collector`, `steering-rules-checker`, 49–73 lines each) — add edge-case guidance: empty inputs, missing canonical files, partial state. One pass over all five.
16. **`/create_test_plan`** — deduplicate against `/test_suite init` (both scaffold plans); make create_test_plan strategy-level and have it hand off to test_suite for execution.

## Phase 4 — Packaging & distribution

17. **README "How Hooks Work"** — document `hooks/hooks.json` (PostToolUse/Stop) behavior in prose.
18. **Skills migration (optional)** — current `commands/*.md` format works; modern plugins may also ship `skills/<name>/SKILL.md` for richer descriptions and supporting files. Evaluate once; if migrating, do it for the big three (`test_suite`, `refactor`, `tdd`) whose pattern catalogs would become supporting files.
19. **Marketplace metadata** — `plugin.json` is minimal; add `version`, keywords, and verify against current plugin schema (commands/agents auto-discovery makes explicit registries unnecessary — do NOT add them blindly).
20. **Test-suite plan closure** — update `thoughts/shared/plans/2025-12-28-test-suite-command.md` checkboxes for Phases 0.5/2.5 now implemented.

## Decisions Needed From Owner

| # | Question | Recommendation |
|---|---|---|
| 1 | ~~Delete `.agent/workflows/` mirror or add sync script?~~ | ✅ Deleted (2026-06-11) |
| 2 | ~~Retire `web-search-researcher` or wire into plan/research commands?~~ | ✅ Wired in (2026-06-11) |
| 3 | ~~`/commit` attribution policy: repo rule vs harness default?~~ | ✅ Documented as explicit override (2026-06-11) |
| 4 | Migrate big commands to `skills/` format? | Defer until a concrete benefit appears |
