# Claude 5 Context-Engineering Rollout Implementation Plan

## Overview

Finish rolling out the repository's adopted design conventions
(`docs/conventions.md` v0.2.1) across the legacy prompt surfaces, in line with
Anthropic's published context-engineering guidance for Claude 5-generation
models. Four independently shippable phases:

1. remove the six frozen `research-v2-*` adapters from the live roster while
   moving their integrity assertion to the frozen candidate build where it
   belongs;
2. migrate the test-suite workflow (command + 8 agents, the heaviest legacy
   surface) to the kernel/adapter form already proven by the research fleet,
   keeping `/rpa:test_suite` as a thin 2.x compatibility alias;
3. remove the destructive-rollback grants and instructions from the refactor
   workflow and single-source the god-module scoring formula; and
4. release the result as 2.3.0 with both version manifests bumped.

Enforcement relies on the existing deterministic gate
(`scripts/validate_docs.py`), the frozen-eval hash check, and the ordinary
Claude Code permission flow. This plan deliberately does not build new
sandboxing, receipt, or transactional-write infrastructure; see "What We're
NOT Doing".

## Current State Analysis

- `docs/conventions.md` v0.2.1 is the normative architecture: workflow
  substance lives in skill packages with progressive disclosure, agent
  contracts live under an owning skill, platform files are thin adapters, and
  metacognitive self-checks and populated fake reports are deleted while
  artifact contracts and deterministic gates stay
  (`docs/conventions.md:20-116,118-126,219-225`).
- The research fleet is already converted: six contracts under
  `plugins/rpa/skills/research-codebase/references/agent-contracts/` with thin
  adapters (exemplar: `plugins/rpa/agents/codebase-locator.md:10-22`).
- Six historical `research-v2-*` adapters still occupy live roster rows.
  Pilot arms are built from pinned git trees
  (`plugins/rpa/skills/research-codebase/evals/public/build_installs.py:45-46,120-137`)
  and their registered hashes live in
  `plugins/rpa/skills/research-codebase/evals/public/pilot_registration.py:32-38`,
  so live copies are not needed for reproduction. The only live-tree consumer
  is the stale assertion at
  `plugins/rpa/skills/research-codebase/evals/public/preflight.py:6019-6037`.
  Replacing it with `git show` against the current checkout would be wrong:
  the frozen candidate predates the `plugins/rpa/` relocation (its adapter
  path is `agents/...`), and CI uses a shallow checkout. The assertion belongs
  on the candidate tree that `build_installs.py` extracts.
- `plugins/rpa/commands/test_suite.md` is the largest legacy workflow surface:
  3,394 words, eight modes (`test_suite.md:2-4`), scripted "Initial Response"
  transcripts (`test_suite.md:35,188,264`), an embedded populated manifest
  example (`test_suite.md:107-153`), and a broad preapproval frontmatter
  (`Task`, `Edit`, `Write`, `TodoWrite`, test-command prefixes, `mkdir` —
  `test_suite.md:4`). Its eight agents add ~8,150 words of 2025-style prompts
  with prescribed algorithms and worked examples
  (e.g. `plugins/rpa/agents/test-impact-mapper.md:26-57`).
- `agents/test-runner.md:1-8` claims to execute tests but its tools are
  `Glob, Grep, LS, Read, Task` — no `Bash`. Its only executable consumer is
  `commands/refactor.md:176-186`, where the request is test
  discovery/assessment; mentions in `tdd/SKILL.md` and
  `create-test-plan/SKILL.md` are routing prose. The honest,
  compatibility-preserving contract is read-only analysis, with execution
  owned by the orchestrating workflow.
- Known single-source violations (conventions §9), verified in the checkout:
  a test-priority formula in `commands/test_suite.md:522-527` and
  `agents/test-impact-mapper.md:133-188`, plus an incompatible one in
  `agents/coverage-reporter.md:114-125`; an invented default coverage
  threshold in `commands/test_suite.md:852-859` and
  `agents/coverage-reporter.md:298-303` ("If threshold not configured:
  Default to 80%"). `skills/tdd/SKILL.md:126-129` is not a duplicate — it
  correctly prohibits inventing 80%.
- The refactor workflow is the highest-risk surface.
  `commands/refactor.md:4` preapproves `Bash(git reset --hard HEAD:*)` and
  `Bash(git checkout:*)`; its rollback/error paths instruct
  `git reset --hard HEAD` and suggest `git clean -fd`
  (`refactor.md:397-406,526-529,564-576`), and
  `agents/refactor-validator.md:120-122` repeats the destructive rollback.
  These instructions can discard unrelated user work.
- God-module scoring is restated in `agents/god-module-finder.md:19-48`,
  `commands/refactor_candidates.md:49-63`, and `commands/refactor.md:42-48`.
  `skills/tech-debt-sweep/SKILL.md:64` and its artifact contract already defer
  to the owning scanner and need no change.
- Release metadata is duplicated in
  `plugins/rpa/.claude-plugin/plugin.json:3` and
  `.claude-plugin/marketplace.json:12`; both must be bumped together.
- The blocking docs gate exists: `scripts/validate_docs.py` validates command,
  agent, and skill frontmatter, JSON manifests, and internal links
  (`validate_docs.py:240-333,467`), and fails if `agents/` becomes empty
  (`validate_docs.py:258-259`). `plugins/rpa/hooks/hooks.json` references no
  agent or command names and is unaffected.
- The 2026-06-10 roadmap still records missing end-to-end coverage for
  test-suite `adopt`/`standardize`
  (`thoughts/shared/plans/2026-06-10-plugin-improvement-roadmap.md:69`).

## Desired End State

- `plugins/rpa/agents/` contains no `research-v2-*` files; one research fleet
  in the roster. Frozen arm builds still reproduce the three registered
  hashes.
- `plugins/rpa/skills/test-suite/` is the canonical workflow: a routing-only
  `SKILL.md`, mode and methodology references loaded on demand, the artifact
  contract owning the manifest schema, and eight agent contracts with thin
  Claude adapters. `/rpa:test-suite` is canonical; `/rpa:test_suite` is a
  documented thin 2.x alias without the legacy broad preapprovals.
- `test-runner` is an honest read-only test-command/results analyst
  (`Glob, Grep, LS, Read`). No live file states a numeric test-priority
  formula or an invented coverage default.
- No live refactor file preapproves or instructs `git reset --hard`,
  `git clean`, or broad `git checkout`. Failure handling reports the scoped
  diff and waits for the user's decision.
- God-module scoring is defined once (owning scanner) and referenced
  everywhere else.
- Both manifests say 2.3.0 and `python3 scripts/validate_docs.py` exits 0.

Recognition: `find plugins/rpa/agents -maxdepth 1 -name 'research-v2-*.md'`
is empty; `build_installs.py` reproduces the registered hashes; grep finds no
destructive rollback pattern in live refactor files; a fresh session shows
one research fleet and both test-suite entrypoints.

### Key Discoveries

- Claude Code loads agent/skill *descriptions* for discovery and bodies only
  on invocation, so Phase 1 (six fewer roster rows) is the only guaranteed
  discovery-context reduction; Phases 2–3 reduce on-demand activation and
  delegation context and remove fake-exemplar anchoring. Word counts are
  telemetry, not a gate.
- Frozen-eval integrity authority is pinned extraction plus registered hashes
  (`pilot_registration.py:32-38`); the six-adapter assertion belongs on the
  extracted candidate in `build_installs.py`, not on the live roster, and a
  missing git object there is an infrastructure failure, never
  `not_applicable`.
- The correct coverage single source of truth is a resolution policy, not the
  number 80: repository-configured policy is the floor; without one, the
  outcome is `not_applicable — no configured threshold`.
- The destructive rollback grant is more consequential than prompt size and
  is a small, self-contained edit — it does not require migrating the whole
  refactor workflow first.
- Keeping one thin deprecated command alias costs one discovery row but
  avoids a breaking invocation rename in a minor release.

## What We're NOT Doing

Deliberately descoped as disproportionate to a prompt-architecture rollout in
a plugin of markdown workflows (the ordinary permission flow, the docs gate,
and manual smoke runs are the enforcement):

- No new enforcement platform: no generation-compatibility runner, OS
  validator sandboxes, tool-guard hooks, Codex smoke driver, receipt
  verification, canonical plan IDs/digests, fsynced journals, or
  transactional write guard. If release-grade behavioral qualification is
  wanted later, it is a separate plan with its own cost justification.
- No context-telemetry script; before/after `wc -w` and roster observation
  are recorded in the PR as evidence, not gated.
- Not migrating the refactor workflow to a skill package in this release
  (Phase 3 is a safety fix in place); not converting `debug`, `commit`,
  handoff, `implement_plan`, `validate_plan`, or `tech_debt_trends`.
- Not trimming the debt fleet (`architecture-guard`, `debt-scanner`,
  `dependency-auditor`, `docs-auditor`, `config-auditor`) or misc agents
  (`code-analyzer`, `file-analyzer`, `parallel-worker`); they need owning
  packages first (follow-up).
- Not deleting any public agent or command name; `/rpa:test_suite` and
  `/rpa:refactor_candidates` survive as compatible entrypoints. The one
  retired option is unsafe `test_suite init --force`.
- Not changing sealed judge material, pilot registrations, pinned SHAs,
  registered hashes, or `fleet-routing.md`; not editing `AGENTS.md`,
  `CLAUDE.md`, or hooks. CI changes are limited to running existing checks
  plus the frozen-build gate.
- Not changing `test-suite-manifest.json` filename or existing fields, and
  not moving persisted artifacts out of `thoughts/shared/test-suite/`.
- Not inventing coverage percentages, runtimes, CI platforms, or test
  commands; not pinning a production model (`model: inherit` stays).
- Not adopting a numeric prompt-size target; Anthropic's reported 80%
  reduction is evidence simplification works, not a local acceptance
  threshold.

## Implementation Approach

One PR per phase, dependency-ordered but independently shippable and
revertable. Phase 2 depends on nothing in Phase 1; Phase 4 lands last and
bumps versions once.

Rewrite rule for every migrated prompt (conventions §3, §4, §10): keep
trigger / when-not-to-use, bounded input, tools and authority, output
contract with evidence, and failure behavior. Delete prescribed step
algorithms, populated example outputs, ALL-CAPS emphasis chains, scripted
transcripts, and self-verification checklists. Frontmatter (`name`,
`description`, `tools`, `model: inherit`, `color`) stays intact; descriptions
keep the "use / do not use" routing form.

Thin-adapter form (copy `agents/codebase-locator.md`): frontmatter, canonical
`@${CLAUDE_PLUGIN_ROOT}/skills/<skill>/references/agent-contracts/<name>.md`
import, ordered fallbacks (`~/.claude/skills/...`, repo-root
`plugins/rpa/skills/...`, then `skills/...` only when the working directory
is the plugin root), and the "do not restate or weaken" clause.

## Phase 1: De-roster frozen research-v2 adapters

### Overview

Remove six duplicate live registrations; relocate their integrity assertion
to the frozen candidate build.

### Changes Required

#### 1. Live adapter removal

**Files**: delete `plugins/rpa/agents/research-v2-analyzer.md`,
`research-v2-locator.md`, `research-v2-pattern-finder.md`,
`research-v2-thoughts-analyzer.md`, `research-v2-thoughts-locator.md`,
`research-v2-web-researcher.md`

#### 2. Frozen candidate validation

**Files**:
`plugins/rpa/skills/research-codebase/evals/public/build_installs.py`,
`plugins/rpa/skills/research-codebase/evals/public/preflight.py`

**Changes**:

- Remove the live-tree assertion at `preflight.py:6019-6037`. Do not replace
  it with `git show` against the checkout and do not add a `not_applicable`
  escape.
- In `build_installs.py`, after extracting the pinned candidate, validate the
  explicit set of six `candidate/agents/research-v2-*.md` files and their
  exact contract imports; make the ablation arm remove that validated set
  instead of an unchecked glob. Missing, extra, or miswired adapters fail the
  build before hashing.
- Compare built hashes with `pilot_registration.INSTALL_SHA256` and exit
  non-zero on mismatch, so the builder CLI is safe to bind in CI. Keep the
  pins and registered values unchanged.

#### 3. Documentation and CI

**Files**:
`plugins/rpa/skills/research-codebase/references/agent-contracts/README.md`,
`README.md`, `.github/workflows/ci.yml`

**Changes**:

- Contract README: the historical adapters exist only in the frozen candidate
  tree addressed by the registered SHA.
- README: update the agent count/tree.
- CI: give the existing integration job full history (`fetch-depth: 0`) and
  run the builder CLI with an output directory outside the checkout
  (`--out "${RUNNER_TEMP}/rpa-frozen-installs"`); its internal hash
  comparison is the gate. Keep the existing required job name.

### Success Criteria

#### Automated Verification

- [x] `find plugins/rpa/agents -maxdepth 1 -name 'research-v2-*.md' -print`
      produces no output
- [x] `python3 plugins/rpa/skills/research-codebase/evals/public/build_installs.py
      --repo . --out "$(mktemp -d)/installs"` exits 0 and reproduces exactly
      the registered hashes (`pilot_registration.py:32-38`):
      baseline `2762bf04…a3e7b28c`, candidate `5638b816…4d4c4d126c`,
      ablation `a1d44b13…5993b21e9b57`
- [x] `python3 scripts/validate_docs.py` exits 0
- [x] `grep -rn "research-v2" plugins/rpa --include="*.md" | grep -v evals`
      returns only the historical note in the contract README
      (additionally: `runner.py --preflight` passes 277/277 after removing
      the relocated live-tree check)

#### Manual Verification

- [ ] A fresh session with an isolated `CLAUDE_CONFIG_DIR` and only this
      plugin shows no `rpa:research-v2-*` agents

---

## Phase 2: Test-suite workflow → kernel skill and thin adapters

### Overview

Move the eight-mode workflow into an owning skill package with progressive
disclosure, correct the authority/coverage/ordering defects, and keep the old
command as a thin compatibility alias.

### Changes Required

#### 1. Kernel and references (new)

**Files**: `plugins/rpa/skills/test-suite/SKILL.md`,
`plugins/rpa/skills/test-suite/references/artifact-contract.md`,
`plugins/rpa/skills/test-suite/references/coverage-policy.md`,
`plugins/rpa/skills/test-suite/references/modes/{audit,adopt,init,update,gaps,run,ci,standardize}.md`

**Changes**:

- `SKILL.md` holds discovery frontmatter (description with when-not,
  `permission-class`, `invocation: both`), intent, scope & authority, the
  mode/authority matrix below, cross-mode invariants, contract pointers,
  acceptance criteria, and escalation rules. It reads `$ARGUMENTS` and loads
  only the selected mode reference. No scripted transcripts, no populated
  example reports, no framework recipes in the kernel.
- Mode/authority matrix (stated once):

  | Mode | Without `apply` | With `apply` |
  |---|---|---|
  | `audit` | refresh manifest under `thoughts/shared/test-suite/` | n/a — rejects `apply` |
  | `adopt`, `init`, `update`, `gaps`, `standardize` | write the mode's plan/report artifact only | additionally write plan-listed tests, fixtures, and named test config; never product source |
  | `run` | execute the manifest's evidenced test command; no persisted artifact | n/a |
  | `ci` | write a CI plan artifact | write the one explicitly selected CI file |

  Assertion-meaning changes, snapshot updates, expected-value edits, and test
  deletions always require an explicit user decision, `apply` alone is not
  consent. Every non-`audit` mode requires a current manifest and directs the
  user to `audit` instead of silently refreshing it. If `init` finds existing
  tests it produces an adopt plan. CI provider comes from an explicit flag or
  a uniquely detected existing provider; with none or both, stop — never
  invent a platform. Retire `init --force`: reject it with guidance to use
  `init apply` against a reviewed plan.
- `references/artifact-contract.md` owns every artifact family: the manifest
  pair (existing `test-suite-manifest.json` filename and fields preserved;
  canonical schema moved here from `agents/test-analyzer.md:130-180`), the
  mode plan/report shapes, and the dated CI-plan path. A same-day artifact
  with a different content digest stops for an explicit decision instead of
  overwriting.
- `references/coverage-policy.md` owns threshold resolution: repository
  config/CI with a cited defining file is the non-weakenable floor; an
  explicitly named plan/user requirement may only strengthen it; with
  neither, `not_applicable — no configured threshold` and CI generation omits
  the coverage gate. Test-gap priority is qualitative (high/medium/low with
  evidence); the numeric formulas are removed, not relocated.
- Mode references carry the per-mode procedure and any genuinely
  non-derivable methodology (framework detection, generation patterns,
  assertion migration, coverage parsing) at the depth the mode needs —
  minimal, synthetic examples only. Generated placeholder tests must be
  explicit pending/skipped constructs, never empty passing bodies.

#### 2. Agent contracts and thin adapters

**Files**:
`plugins/rpa/skills/test-suite/references/agent-contracts/{test-analyzer,test-architect,test-generator,test-impact-mapper,test-refactorer,test-runner,test-updater,coverage-reporter}.md`
(new); rewrite the matching eight files under `plugins/rpa/agents/`

**Changes**:

- One contract per conventions §3 (trigger/when-not, bounded input, tools,
  authority, output/evidence, failure behavior), distilled from the current
  bodies under the rewrite rule.
- `test-runner`: read-only test-command/results analyst; adapter tools become
  exactly `Glob, Grep, LS, Read` (drop `Task`, do not add `Bash`). The
  orchestrating workflow owns execution. The current `commands/refactor.md`
  consumer already requests discovery/assessment and keeps working.
- `coverage-reporter`: returns structured measured data; remove the
  incompatible priority formula and the "Default to 80%" fallback; no write
  authority to `thoughts/shared/test-coverage/`.
- `test-architect` output is consumed by `test-generator`; the init mode runs
  them sequentially, other independent tracks may parallelize.
- Adapters follow the thin-adapter form; public names, `model: inherit`, and
  colors unchanged.

#### 3. Compatibility alias

**Files**: `plugins/rpa/commands/test_suite.md`

**Changes**:

- Replace the body with a thin deprecated adapter that forwards `$ARGUMENTS`
  to the test-suite kernel (canonical plugin-root path, then the standard
  fallbacks). It contains no mode procedures, schemas, or policy copies.
- Drop the legacy broad preapprovals from its frontmatter (`Task`, `Edit`,
  `Write`, `TodoWrite`, test-command prefixes, `mkdir` —
  `test_suite.md:4`); keep only read/discovery tools and the read-only git
  commands. Writes and test execution go through the ordinary permission
  flow. Public syntax stays compatible; the reduced preapproval and the
  retired `init --force` are documented as intentional safety corrections.

#### 4. Consumer pointers, docs

**Files**: `plugins/rpa/docs/testing-patterns.md`,
`plugins/rpa/skills/tdd/SKILL.md`,
`plugins/rpa/skills/create-test-plan/SKILL.md`, `README.md`

**Changes**:

- Point testing-patterns at the new mode/methodology references instead of
  `agents/test-generator.md` as template owner.
- In tdd and create-test-plan routing prose, route execution to
  `test-suite run` rather than implying the read-only `test-runner` executes;
  keep tdd's "do not invent 80%" rule untouched.
- README: update the Commands Overview and manual-install tree with the
  canonical skill and the deprecated alias.

### Success Criteria

#### Automated Verification

- [x] `python3 scripts/validate_docs.py` exits 0 (new skill package, adapter
      frontmatter, links)
- [x] `grep -rn "Priority Score\|Default to 80" plugins/rpa --include="*.md"
      | grep -v fixtures` returns nothing
- [x] `grep -n "tools:" plugins/rpa/agents/test-runner.md` shows exactly
      `Glob, Grep, LS, Read`
- [x] `grep -c "allowed-tools" plugins/rpa/commands/test_suite.md` shows the
      alias frontmatter contains no `Edit`, `Write`, `Task`, `TodoWrite`, or
      test-command preapproval (inspect the line)
- [x] Each of the eight adapters imports its contract path and each contract
      file exists (link check via `validate_docs.py`)

#### Manual Verification

- [ ] `/rpa:test-suite audit` and `/rpa:test_suite audit` on this repo both
      produce the manifest pair under `thoughts/shared/test-suite/` with the
      unchanged filename, and touch nothing else
- [ ] `adopt` and `standardize` are exercised end to end on a fragmented
      fixture repo (closes the roadmap's open item)
- [ ] An `update apply` involving assertion changes stops for explicit
      confirmation of those items
- [ ] A direct `rpa:test-runner` spawn describes/analyzes the evidenced
      command without claiming to have executed anything

---

## Phase 3: Refactor destructive-rollback removal and scoring dedup

### Overview

A safety fix in place: no live refactor file may grant or instruct discarding
user work, and the scoring formula gets one owner. The full kernel/adapter
migration of the refactor workflow is follow-up work.

### Changes Required

#### 1. Remove destructive grants and instructions

**Files**: `plugins/rpa/commands/refactor.md`,
`plugins/rpa/agents/refactor-validator.md`

**Changes**:

- Frontmatter (`refactor.md:4`): remove `Bash(git reset --hard HEAD:*)` and
  `Bash(git checkout:*)`; keep read-only git and the named test/lint
  commands.
- Replace the rollback/abort sections (`refactor.md:397-406,526-529,564-576`)
  with non-destructive failure handling: report the scoped diff of
  workflow-touched files, preserve all pre-existing changes, and wait for the
  user's decision; any reversal is user-driven and file-scoped. Remove the
  `git clean -fd` suggestion.
- `refactor-validator.md:120-122`: the failure contract becomes FAIL plus
  evidence; delete the rollback command option.

#### 2. Single-source god-module scoring

**Files**: `plugins/rpa/agents/god-module-finder.md`,
`plugins/rpa/commands/refactor.md`,
`plugins/rpa/commands/refactor_candidates.md`

**Changes**:

- `god-module-finder.md` remains the owner of the weighted scoring definition
  (`god-module-finder.md:19-48`); keep the "big but cohesive" false-positive
  guidance, drop worked scoring tables with concrete fake numbers per the
  rewrite rule.
- Replace the formula restatements at `refactor.md:42-48` and
  `refactor_candidates.md:49-63` with pointers to the owning agent. Emitted
  score fields and `metrics_schema` meaning stay unchanged for debt/trend
  consumers.

### Success Criteria

#### Automated Verification

- [ ] `grep -rn "reset --hard\|git clean" plugins/rpa/commands/refactor.md
      plugins/rpa/agents/refactor-validator.md
      plugins/rpa/commands/refactor_candidates.md` returns nothing
- [ ] The scoring weights appear in exactly one live file:
      `grep -rln "0.25\|weighted scor" plugins/rpa/agents plugins/rpa/commands
      --include="*.md"` → only `agents/god-module-finder.md`
- [ ] `python3 scripts/validate_docs.py` exits 0

#### Manual Verification

- [ ] `/rpa:refactor_candidates` on a sample repo still produces a ranked
      index with unchanged score fields
- [ ] In a dirty worktree, a simulated failed verification step reports the
      scoped diff and waits — no reset/clean is proposed

---

## Phase 4: Release 2.3.0

### Overview

Bump both version authorities, document the changes, and verify the combined
result.

### Changes Required

#### 1. Version and docs

**Files**: `plugins/rpa/.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `README.md`

**Changes**:

- Bump both version fields 2.2.0 → 2.3.0 in the same commit.
- README/PR body: 2.3.0 notes — canonical `/rpa:test-suite`, supported
  `/rpa:test_suite` 2.x alias, retired `init --force`, reduced preapprovals,
  non-destructive refactor failure handling, removed research-v2 roster rows.
  There is no changelog file; do not invent one.

### Success Criteria

#### Automated Verification

- [ ] `grep '"version"' plugins/rpa/.claude-plugin/plugin.json
      .claude-plugin/marketplace.json` → both `2.3.0`
- [ ] `python3 scripts/validate_docs.py` exits 0 from a clean checkout
- [ ] Phase 1's frozen-build hash check still passes on the release commit

#### Manual Verification

- [ ] Fresh isolated session: one research fleet, both test-suite
      entrypoints, `/rpa:refactor` and `/rpa:refactor_candidates` visible and
      routing correctly; before/after `wc -w plugins/rpa/agents/*.md` and
      roster row counts recorded in the PR as (non-gating) evidence

---

## Testing Strategy

### Unit Tests

- `python3 scripts/validate_docs.py` (backed by
  `tests/fixtures/docs-validate/`) is the blocking structural gate for every
  phase: frontmatter, links, manifests, skill packages.

### Integration Tests

- Phase 1: `build_installs.py` reproduces the three registered arm hashes
  from pinned history (run in CI with full-history checkout).
- Existing hook, TDD evidence, session-log, and one-pager tests continue
  unchanged in their required jobs.

### Manual Testing

- Per-phase smoke runs listed in each phase's manual criteria: both
  test-suite entrypoints, the previously untested `adopt`/`standardize`
  modes, the refactor failure path in a dirty worktree, and roster
  inspection in an isolated profile.

## Performance Considerations

Phase 1 is the only guaranteed discovery-context reduction (six roster rows).
Phases 2–3 reduce activation/delegation context and remove fake-exemplar
anchoring; the effect is recorded as before/after measurements in the PR, not
gated. No runtime code paths change; hooks are untouched.

## Migration and Rollback

- One PR per phase; rollback is `git revert` of that PR. Phase 2's command
  replacement and skill creation land in one commit so a revert restores the
  legacy command atomically.
- `/rpa:test_suite` stays supported through 2.x; removal is a 3.0 decision.
  `init --force` is the one retired option and its rejection message points
  to the plan-based flow.
- Manifest filename/fields and `thoughts/shared/test-suite/` locations are
  unchanged; no data migration.
- Reduced preapprovals are a behavior change users will notice as permission
  prompts for writes/test runs — documented as an intentional safety
  correction.
- Frozen research artifacts remain reconstructible from pinned history and
  registered hashes.

## References

- Anthropic, [The new rules of context engineering for Claude 5 generation
  models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models)
- Normative repository spec: `docs/conventions.md` v0.2.1 (§1–§6, §9–§10)
- Prior program plan:
  `thoughts/shared/plans/2026-06-10-plugin-improvement-roadmap.md`
- Pilot freeze mechanics:
  `plugins/rpa/skills/research-codebase/evals/public/build_installs.py`,
  `pilot_registration.py`, `preflight.py:6019-6037`
- Converted exemplar: `plugins/rpa/agents/codebase-locator.md` and
  `plugins/rpa/skills/research-codebase/references/agent-contracts/README.md`

## Enhancement History

### 2026-08-30 Enhancement

Adversarial review pass (see git history of this file for the full text).
Validated corrections retained by the current revision: frozen-eval
validation moved to the extracted candidate with exact registered hashes;
`test-runner` made honestly read-only; refactor destructive-rollback removal
elevated to its own phase; `/rpa:test_suite` kept as a 2.x alias; both
version manifests bumped; coverage policy as resolution rules instead of a
number; word-count gates rejected as measuring the wrong layer.

### 2026-08-30 Simplification

Owner directive: remove overengineering. Removed from scope (recorded in
"What We're NOT Doing"): the generation-compatibility runner, OS validator
sandboxes, Claude tool-guard hooks, Codex smoke driver, receipt
verification, canonical plan IDs/sealed change bundles/decision receipts,
transactional write guard with fsynced journals, context-telemetry scripts
with committed baselines, per-skill characterization eval harnesses, the
single-release-PR stamp-and-qualify protocol, and the full refactor kernel
migration (now a follow-up; Phase 3 keeps only the in-place safety fix and
scoring dedup). Restored independently shippable per-phase PRs. Enforcement
returns to `validate_docs.py`, the frozen-eval hash gate, the ordinary
permission flow, and manual smoke verification.
