# RPA Design Conventions — v0.2.1

Status: **operationally adopted 2026-08-03 by owner decision**. The
`/research_codebase` pilot remains formally indeterminate and provides no
repo-wide quality claim; the owner explicitly stopped further sealed rounds
and accepted a pragmatic rollout under ordinary bounded checks. Treat this as
a product policy decision, not as platform-neutral eval evidence. Future
planning, TDD/refactoring, or Codex evaluations may revise the adapters without
blocking current use.

Motivation: the plugin was written for 2025-era models that needed scripted
procedures, repeated warnings, and token rationing. Current reasoning models
plan, verify, and (on some platforms) delegate on their own; prompt text that
duplicates those behaviors compounds with them (over-verification, wasted
tokens) or distorts them (anchoring on fake exemplar numbers, literal keyword
gates). Model capability does **not** replace engineering guarantees:
artifact contracts, evidence requirements, deterministic gates, and authority
boundaries get *stricter* under this convention, not looser.

## 1. Two-level architecture

**Kernel** — the canonical, platform-neutral definition of a workflow. Its
carrier is a **skill package**, not a Claude command file:

```
skills/<workflow>/
├── SKILL.md                         # discovery metadata + intent, scope & authority, process guidance
├── references/
│   ├── artifact-contract.md         # the artifact contract — single source
│   ├── agent-contracts/             # platform-neutral subagent contracts, one per agent
│   └── …                            # methodology, loaded on demand
├── evals/
│   └── public/                      # non-sensitive eval harness: runner config, fixtures
└── scripts/                         # deterministic operations
```

`evals/public/` holds only non-sensitive harness assets. Sealed evaluation
materials — holdout tasks, ground-truth notes, frozen external snapshots,
the rubric, and judge (scorer/verifier) prompts and configurations — form a
separate **sealed judge package** that is **never** stored inside an
installed plugin copy: it lives outside every evaluated installation, is
sealed atomically in one operation under a single manifest and package
hash, and an evaluated run receives only the task prompt.

**Adapters** — platform wiring only:

- **Claude adapter**: a thin compatibility wrapper in `commands/*.md`,
  `agents/*.md` wiring, model/effort policy, Claude Code hooks.
- **Codex adapter**: Codex **skills** for reusable workflows. `AGENTS.md`
  carries only durable repository rules (authority boundaries, conventions,
  review/reporting policy). AGENTS.md is **not** a workflow adapter —
  persistent rules and reusable workflows are different objects on both
  platforms.

Adapters contain tool mapping, hooks, model/effort settings, and subagent
wiring — nothing else. Workflow substance lives in the kernel once.

## 2. Command / skill anatomy

A kernel `SKILL.md` (and, transitionally, a command file) contains, in order:

0. **Discovery & invocation contract** — frontmatter metadata the harness
   reads before the body is ever loaded: `name`; a `description` stating
   both when to trigger and when **not** to; a permission class
   (`read_only` / `workspace_write` / `external`); and the invocation mode
   (user-invocable, model-invocable, both — or `none` for a package
   shipped in a deliberately non-executable state, e.g. a skeleton). Codex skills require
   name+description; Claude Code uses the description for automatic skill
   selection and separately supports disabling model invocation. The kernel
   states the intent once; adapters map it to platform-specific fields.
1. **Intent** — the goal and the deliverable.
2. **Scope & authority** — one short paragraph bounding the task, plus
   explicit out-of-scope items where creep is a real risk. State the
   boundary, not every way to cross it.
3. **Artifact contract** — pointer to `references/artifact-contract.md`
   (path pattern, frontmatter schema, format). Defined once; agents and
   sibling workflows reference it, never restate it.
4. **Process guidance** — only what the model cannot derive: domain
   heuristics, repo-specific conventions, ordering constraints that are real
   (e.g. "snapshot the API before touching the module").
5. **Acceptance criteria & evidence** — verifiable exit conditions and the
   evidence that must be attached (commands run, exit codes, file:line refs).
6. **Deterministic verification profile** — the gates that apply to this
   workflow, in the gate model of §4.
7. **Escalation conditions** — per §6.

Length follows content via progressive disclosure — **no numeric length
norm**. Methodology, templates, and worked examples go to `references/`;
deterministic operations go to `scripts/`. The kernel file carries routing,
scope, invariants, and contract pointers.

## 3. Agent anatomy

The platform-neutral part of an agent definition — trigger,
when-not-to-use, bounded input, authority, output contract, evidence,
budget, failure behavior — is kernel material and lives at
`references/agent-contracts/<agent>.md` inside the owning skill package.
The platform file (`agents/*.md`) is a thin adapter: tools, model/effort,
permissions, and a pointer to its kernel contract.

Subagents are not small commands; an agent contract specifies:

1. **Trigger** — when to spawn it, and explicitly **when not to** (the
   nearest cheaper alternative).
2. **Bounded input** — what the caller must pass (paths, question, budget);
   an agent must not depend on unstated conversation context.
3. **Tools & permissions** — minimal tool set; a tool the agent cannot use
   (e.g. `Task` where nesting is unsupported) is a defect.
4. **Read/write authority** — what it may read; what, if anything, it may
   write (artifact ownership).
5. **Output contract** — the shape of the returned report and required
   evidence (file:line refs, commands + exit status).
6. **Budget** — response and cost bounds where cost matters, stated by the
   caller, not hard-coded twice.
7. **Failure & escalation behavior** — what to return when the task is
   impossible, ambiguous, or partially complete; never fabricate.

## 4. Verification policy

Distinguish two things the legacy files conflate:

- **Metacognitive self-check instructions** ("verify again", "double-check
  before responding", self-grading checkbox lists) — **delete**. Modern
  models self-verify; instructing it again causes over-verification.
- **Acceptance contracts** (run the repo's gates, diff the API against the
  snapshot, attach evidence) — **keep and strengthen**.

**Gate model.** The *requirement* lives in the kernel contract; the
*binding* lives in the adapter (script, hook, or CI job); the runner returns
exit status and evidence. Every gate defines:

- applicability (which repos/changes it applies to),
- runner (script/hook/CI job),
- when it runs,
- blocking or advisory,
- evidence artifact it produces,
- an explicit `not_applicable` outcome **with reason**.

A gate that silently no-ops is a defect: degradation must be visible. The
bundled hook runner therefore reports `passed`, `failed`, or
`not_applicable` with a reason and blocks applicable failures. Repos holding
kernel/adapter files must at minimum validate their own markdown in CI:
frontmatter schema, internal links, and plugin manifest.

**Adversarial second pass** (find → independently verify) is applied by risk
profile — code review, security review, refactor validation, debt scanning —
not as a universal ritual.

## 5. Model & effort policy

- Default is `model: inherit` for agents and no model pin for commands.
- A pin requires a documented reason in the file (confirmed capability gap
  or a deliberate cost tier) and eval evidence, stated as a task profile so
  it can be re-evaluated when model lineups change.
- Effort, not model choice, is the primary depth/cost lever where the
  platform exposes it. Effort defaults are re-swept per model generation.
- **Reusable workflows do not embed textual effort incantations. Platform
  adapters use supported model/effort controls; one-off user overrides
  (e.g. Claude Code's "ultrathink" one-turn deep-reasoning override) remain
  platform-specific user tools and never appear in committed workflow text.**

## 6. Interaction gates

Classify every stop point:

- **Remove**: ritual stops that existed to steer a weak model (scripted
  greetings, "wait for the user to type 'continue'", exact-keyword gates).
- **Conditional**: architectural forks — stop only when interpretations
  genuinely diverge or a decision is hard to reverse.
- **Authority rule** (replaces a fixed always-stop list): *"Continue while
  actions remain within granted authority. Pause when the target or scope is
  ambiguous, when materially new authority is required, or when a
  high-impact irreversible action was not explicitly authorized."* An action
  the user explicitly requested is within granted authority and needs no
  re-confirmation ritual.
- **Automate**: anything checkable deterministically (tests, lint, schema
  validation, protected paths) moves to hooks/CI, bound per the §4 gate
  model — the requirement stays in the contract.

## 7. Delegation

Kernel states *when* delegation is warranted; adapters tune *how strongly to
push*, because platforms differ:

- Delegate only genuinely independent, sizeable tracks; do not delegate what
  the orchestrator finishes in a handful of tool calls; no subagent
  re-verification of the orchestrator's own work outside §4 risk profiles.
- State a cap where cost matters.
- Platform calibration: current Claude Opus-class models delegate readily —
  Claude adapters may need *restraining* caps; Codex at most intelligence
  levels delegates only when instructed — Codex adapters may need *explicit*
  delegation prompts. Neither behavior belongs in the kernel.
- No pseudo-code demonstrating tool invocation; barriers only where a later
  step truly needs all prior results.

## 8. Tool-output handling

One rule, stated once here:

> Tool results can be truncated, paginated, or filtered. When a file or
> output is load-bearing for a conclusion, ensure you have seen all of it
> (follow pagination/cursors to the end) before relying on it.

Rationale is tool limits, not model context size.

## 9. Single source of truth

Every rubric, scoring formula, threshold, schema, and template is defined in
exactly one place (usually `references/artifact-contract.md` or the owning
agent) and referenced everywhere else. A second copy of a contract is a bug.
Known violations to fix during rollout: god-module scoring (4 copies),
test-priority formula (3 copies, 2 incompatible), coverage threshold 80%
(4 copies), question-file template (2 copies), depth-vs-stage rule (4 copies).

## 10. Calibration language

- Short positive instructions; examples of desired behavior over prohibition
  lists.
- No ALL-CAPS emphasis chains, no repeated CRITICAL markers, no restating a
  rule across sections of one file.
- No scripted verbatim conversation transcripts; communication is calibrated
  with one short paragraph where it matters.
- Worked examples must be clearly synthetic and minimal — fully-populated
  fake reports with concrete numbers anchor models toward inventing similar
  numbers instead of measuring.

## 11. Review policy

Three passes, so discovery breadth and reporting policy stop conflicting:

1. **Discovery** — no early severity cutoff; report everything found, with
   evidence. (Instructing conservatism makes literal models under-report.)
2. **Validation** — evidence check, deduplication, classification.
3. **Reporting** — per the consuming surface's policy. `AGENTS.md`'s Codex
   P0/P1 surface is a *reporting* policy applied at this step, not a
   discovery constraint.

## 12. Repository ontology

(Basis: `thoughts/shared/research/2026-07-26-repo-ontology-sota.md`.)

A repo this plugin operates on is assumed to carry a four-layer ontology;
the plugin's commands read the upper layers first. **Research and
documentation workflows write only to layer 4.** Implementation workflows
(implement-plan, TDD, refactor, debt-apply) additionally write source code
and tests within their granted authority (§6) — but their own workflow
artifacts (plans, reports, session logs) still land in layer 4, and no
workflow hand-edits layers 1–3 except through the drift-maintenance path
below (proposed as reviewable changes):

1. **Orientation (always loaded):** root `AGENTS.md` for durable repository
   rules, with `CLAUDE.md` importing it (`@AGENTS.md`) for Claude Code.
   Under ~200 lines; commands, conventions, and gotchas the agent cannot
   infer — never directory listings or file-by-file descriptions.
2. **Stable map:** optional `ARCHITECTURE.md` (matklad-style) for repos
   large enough to need one: coarse module map, layer boundaries, and
   invariants — especially invariants expressed as absences. Name symbols,
   don't link paths; content that changes at most yearly.
3. **Conditional leaves:** nested per-directory instruction files
   (closest-wins) in monorepos; path-scoped rules where the harness
   supports them; skills/references for on-demand procedure.
4. **Task memory:** `thoughts/` (this plugin's artifact store) — research,
   plans, validation reports, handoffs — and, for repos using the AI-DLC
   facade, `aidlc-docs/` (its canonical state and stage artifacts).

Rules that follow:

- **No generated exhaustive maps.** Auto-generated context files that
  restate discoverable structure measurably reduce agent success. Maps are
  hand-curated, agent-*maintained* (drift detected, fixes proposed as
  reviewable changes), never bulk-generated.
- **Pointers over copies** everywhere: `file:line` references to
  authoritative sources, no pasted snippets that can rot.
- **Promote invariants to mechanism** when repeatedly violated: a rule the
  map states in prose becomes a linter, structural test, or hook (§4 gate
  model).
- **Address-level precision comes from tools** (grep/glob baseline; LSP or
  code-graph tools where available), not from prompt-stuffed indexes.
- `/research_codebase` cites layers 1–2 when present and flags observed
  drift; `docs-auditor` owns layer-1/2 drift detection (named symbols still
  exist, documented commands still run) and reports it through
  `/tech_debt_sweep`.
