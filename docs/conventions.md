# RPA Design Conventions — v0.1 (working draft)

Status: **draft, not yet validated**. These conventions are adopted repo-wide only
after the `/research_codebase` pilot (see
`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`) shows
equal-or-better quality against the frozen baseline. Until then they govern the
pilot rewrite only.

Motivation: the plugin was written for 2025-era models that needed scripted
procedures, repeated warnings, and token rationing. Current reasoning models
(Claude Opus 5 generation, Codex equivalents) plan, verify, and delegate on
their own; prompt text that duplicates those behaviors now compounds with them
(over-verification, wasted tokens) or distorts them (anchoring on fake
exemplar numbers, literal keyword gates). At the same time, model capability
does **not** replace engineering guarantees: artifact contracts, evidence
requirements, deterministic gates, and authority boundaries get *stricter*
under this convention, not looser.

## 1. Two-level architecture

Every workflow is specified in two layers:

**Platform-neutral kernel** — what the workflow *is*, independent of which
agent runs it:

- intent (what problem this solves, one or two paragraphs)
- scope and authority (what may be read, written, executed; what is out of bounds)
- artifact contract (paths, formats, schemas — the single source of truth)
- acceptance criteria (verifiable exit conditions)
- evidence requirements (what must be shown: file:line refs, commands run, exit codes)
- escalation conditions (when to stop and ask a human)
- deterministic verification profile (which gates run outside the model: tests, lint, hooks, CI)

**Platform adapters** — how a specific harness executes the kernel:

- Claude adapter: `commands/*.md` + `agents/*.md` frontmatter, effort policy,
  Claude Code hooks, subagent wiring.
- Codex adapter: `AGENTS.md`, Codex skills/review conventions, CI gates
  (`codex-review-window`).

In v0.1 the kernel is expressed as a mandatory section structure inside each
command file (see §2), not as separate kernel files. Extract shared kernel
files only when the Codex adapter needs to consume the same kernel — do not
pre-abstract.

## 2. Command anatomy

A command file contains, in order:

1. **Intent** — the goal and the deliverable.
2. **Scope & authority** — one short paragraph bounding the task, plus explicit
   out-of-scope items when scope creep is a real risk. Not a list of 30 "do not"
   bullets: state the boundary, not every way to cross it.
3. **Artifact contract** — output path pattern, frontmatter schema, format.
   Defined here **once**; agents and sibling commands reference it, never
   restate it.
4. **Process guidance** — only the parts the model cannot derive: domain
   heuristics, repo-specific conventions, ordering constraints that are real
   (e.g. "snapshot the API before touching the module"). No step-by-step
   scripts for things a capable model does unprompted.
5. **Acceptance criteria & evidence** — verifiable conditions ("required test,
   lint, and typecheck gates pass; report the commands and any failures"), not
   metacognitive rituals ("double-check your work").
6. **Escalation conditions** — see §5.

Length follows content via progressive disclosure — there is **no numeric
length norm**. Methodology catalogs, templates, and worked examples go to
`references/` (today: `docs/`); deterministic operations go to `scripts/`.
The command file itself carries routing, scope, invariants, and the contract.

## 3. Verification policy

Distinguish two things that the old files conflate:

- **Metacognitive self-check instructions** ("verify again", "double-check
  before responding", "re-verify every conclusion", self-grading checkbox
  lists) — **delete**. Modern models self-verify; instructing it again causes
  over-verification.
- **Acceptance contracts** (run the repo's test/lint/typecheck gates, diff the
  API against the snapshot, attach evidence) — **keep and strengthen**. These
  are engineering guarantees, not model babysitting.

Agent "Success Criteria" sections are rewritten in these terms: keep the
verifiable exit conditions, drop the behavioral checklist items.

**Adversarial second pass** (find → independently verify findings) is applied
by risk profile — code review, security review, refactor validation, debt
scanning — not as a universal ritual on every research task.

## 4. Model & effort policy

- Default is `model: inherit` for agents and no model pin for commands.
- A pin is allowed only with a documented reason in the file (confirmed
  capability gap or a deliberate cost tier for mechanical work) and eval
  evidence. Floating marketing names ("opus", "sonnet") drift across
  generations — a justified pin states the task profile it serves, so it can
  be re-evaluated when models change.
- Effort, not model choice, is the primary depth/cost lever on platforms that
  expose it. Effort defaults are re-swept per model generation, not inherited.
- No thinking incantations ("ultrathink", "think deeply/hard") anywhere; depth
  is controlled by the harness, not by magic phrases.

## 5. Interaction gates

Classify every stop point; the old files made all gates mandatory regardless
of risk:

- **Remove**: ritual stops that existed to steer a weak model (scripted
  greetings, "wait for the user to type 'continue'", exact-keyword gates).
- **Conditional**: architectural forks and materially different design options
  — stop only when interpretations genuinely diverge or a decision is hard to
  reverse. Formula: *"If the task is sufficiently specified, run to
  completion. Stop when you find materially different interpretations of the
  request, when you lack authority for an action, or before an irreversible
  decision."*
- **Always stop**: destructive actions, scope expansion, external writes or
  publication, spending, security/compliance-relevant changes.
- **Automate**: anything checkable deterministically (tests, lint, schema
  validation, protected paths) moves to hooks/CI, out of prompt text.

## 6. Delegation

Give criteria and caps, not scripted fan-out:

- Delegate only genuinely independent, sizeable tracks (wide multi-file
  investigation, parallel analyzers over disjoint concerns).
- Do not delegate what the orchestrator can finish in a handful of tool calls,
  and do not spawn subagents to re-verify the orchestrator's own work unless
  the risk profile (§3) calls for an adversarial pass.
- State a cap where cost matters. No pseudo-code showing how to call the Task
  tool; no "wait for ALL agents" boilerplate — barriers only where a later
  step truly needs all prior results.

## 7. Tool-output handling

One rule, stated once at convention level and not repeated per command:

> Tool results can be truncated, paginated, or filtered. When a file or
> output is load-bearing for a conclusion, ensure you have seen all of it
> (follow pagination/cursors to the end) before relying on it.

This replaces the ~11 scattered "read files FULLY" repetitions. The rationale
is tool limits, not model context size — it stays true regardless of context
window.

## 8. Single source of truth

Every rubric, scoring formula, threshold, schema, and template is defined in
exactly one place (usually the owning agent or the artifact contract) and
referenced everywhere else. A second copy of a contract is a bug. Current
known violations to fix during rollout: god-module scoring (4 copies),
test-priority formula (3 copies, 2 incompatible), coverage threshold 80%
(4 copies), question-file template (2 copies), depth-vs-stage rule (4 copies).

## 9. Calibration language

- Short positive instructions; examples of desired behavior over lists of
  prohibitions.
- No ALL-CAPS emphasis, no repeated CRITICAL markers, no restating a rule in
  multiple sections of the same file.
- No scripted verbatim transcripts of the conversation. Communication is
  calibrated with one short paragraph (narration cadence, deliverable length)
  when it matters.
- Worked examples in agent files must be clearly synthetic and minimal —
  fully-populated fake reports with concrete numbers anchor models toward
  inventing similar numbers instead of measuring.

## 10. Review prompting

Never instruct reviewers to be conservative or report only high-severity
findings — literal models under-report. Ask for everything, then filter or
adversarially verify in a separate pass (§3).

## 11. Repository ontology

(Basis: `thoughts/shared/research/2026-07-26-repo-ontology-sota.md`.)

A repo this plugin operates on is assumed to carry a four-layer ontology;
the plugin's commands read the upper layers first and write only to layer 4:

1. **Orientation (always loaded):** root `AGENTS.md` as the cross-tool
   kernel carrier, with `CLAUDE.md` importing it (`@AGENTS.md`) for Claude
   Code. Under ~200 lines; commands, conventions, and gotchas the agent
   cannot infer — never directory listings or file-by-file descriptions.
2. **Stable map:** optional `ARCHITECTURE.md` (matklad-style) for repos
   large enough to need one: coarse module map, layer boundaries, and
   invariants — especially invariants expressed as absences. Name symbols,
   don't link paths; content that changes at most yearly.
3. **Conditional leaves:** nested per-directory instruction files
   (closest-wins) in monorepos; path-scoped rules where the harness
   supports them; skills/references for on-demand procedure.
4. **Task memory:** `thoughts/` (this plugin's artifact store) — research,
   plans, validation reports, handoffs.

Rules that follow:

- **No generated exhaustive maps.** Auto-generated context files that
  restate discoverable structure measurably reduce agent success. Maps are
  hand-curated, agent-*maintained* (drift detected, fixes proposed as
  reviewable changes), never bulk-generated.
- **Pointers over copies** everywhere: `file:line` references to
  authoritative sources, no pasted snippets that can rot.
- **Promote invariants to mechanism** when repeatedly violated: a rule the
  map states in prose becomes a linter, structural test, or hook.
- **Address-level precision comes from tools** (grep/glob baseline; LSP or
  code-graph tools where available), not from prompt-stuffed indexes.
- `/research_codebase` cites layers 1–2 when present and flags observed
  drift; `docs-auditor` owns layer-1/2 drift detection (named symbols still
  exist, documented commands still run) and reports it through
  `/tech_debt_sweep`.
