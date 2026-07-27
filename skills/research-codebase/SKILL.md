---
name: research-codebase
description: >
  Research and document a codebase as it exists today: answer "how does X
  work", "where is Y defined/configured", "explain subsystem Z end-to-end",
  including history from thoughts/ and, when the question hinges on external
  libraries or APIs, their documentation. Produces a citation-backed research
  document under thoughts/shared/research/. Do NOT select for requests to
  change code, plan work, review quality, or find bugs — those belong to the
  planning, TDD/refactor, and review workflows; this workflow only describes
  what exists.
user-invocable: true
permission-class: "read_only (target repo) + workspace_write (thoughts/shared/research/ only)"
invocation: "both"
---

# Research Codebase — kernel

## Intent

Answer the user's research question about this repository by investigating
the code as it exists now, and deliver a self-contained research document —
every claim backed by a `file:line` citation (or an external citation for
library/API facts) — at the path defined by the artifact contract.

## Scope & authority

You are a documentarian. Describe what exists, where it lives, how it
works, and how components interact. Suggestions, critiques, root-cause
analyses, refactoring proposals, and future enhancements are out of scope
unless the user explicitly asks for them — the deliverable is a technical
map of the current system, not an assessment of it.

Write authority is limited to `thoughts/shared/research/`. Everything else
— the target repository, other `thoughts/` areas, configuration — is
read-only for this workflow.

## Artifact contract

The output document — path pattern, frontmatter schema, body template, and
follow-up semantics — is defined once in
[`references/artifact-contract.md`](references/artifact-contract.md).
Consumers (`/create_plan`, `/enhance_research`) depend on that exact shape;
emit it precisely.

## Process guidance

What the model cannot derive on its own:

- **Read the artifact contract before writing.** Load
  `references/artifact-contract.md` itself before emitting the document
  and reproduce its frontmatter schema and body template exactly — the
  contract is a file to read, not a shape to recall. (Real-backend
  shakedown finding: a session that skips this read improvises a
  nonconforming format and fails the artifact gate.)
- **Read user-mentioned files first, fully, yourself.** If the question
  names specific files (tickets, docs, code), read them completely in the
  main context before any delegation — decomposition quality depends on it.
- **Orientation layers first.** If the repo carries `AGENTS.md` /
  `CLAUDE.md` or an `ARCHITECTURE.md`, read them before searching; cite
  them where they answer part of the question, and note observed drift
  between those maps and the code (report it — fixing is out of scope).
- **Code is the source of truth.** `thoughts/` supplies historical context
  only; never answer from a prior research document without re-verifying
  against the live code at the current checkout.
- **Metadata comes from the script.** Run the installed
  `spec_metadata.sh` (this plugin's `scripts/spec_metadata.sh`) for the
  document's metadata; if unavailable, gather the same fields manually.
  The artifact contract lists the fields.
- **Permalinks when shareable.** If the current commit is pushed, convert
  local `file:line` references to commit-pinned GitHub permalinks per the
  artifact contract.
- Tool results can be truncated, paginated, or filtered. When a file or
  output is load-bearing for a conclusion, ensure you have seen all of it
  (follow pagination/cursors to the end) before relying on it.

## Delegation

Delegate only genuinely independent, sizeable investigation tracks; do not
delegate what you can finish yourself in a handful of tool calls, and do
not spawn a subagent to re-verify your own reading. When the question
decomposes into parallel tracks (separate subsystems, code vs history vs
external docs), the research agent fleet and its routing live in
[`references/fleet-routing.md`](references/fleet-routing.md); each fleet
agent's contract is under
[`references/agent-contracts/`](references/agent-contracts/).

## Acceptance criteria & evidence

The task is complete when:

1. The research document exists at the contract path, with valid
   frontmatter and the contract's body sections.
2. The user's question is answered in the Summary, with the reasoning
   grounded in Detailed Findings.
3. Every verifiable claim carries a citation: `file:line` for repository
   facts, a source link for external facts, a `thoughts/` path (with
   `searchable/` stripped) for historical facts. An uncited verifiable
   claim is a defect.
4. The document is self-contained — a reader with no session context can
   follow it.
5. The final reply to the user summarizes the findings and links the
   document; follow-up questions append to the same document per the
   artifact contract.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Metadata correctness | every document | `scripts/spec_metadata.sh` | before writing | blocking | script output used in frontmatter |
| Artifact schema | every document | `evals/public/validate_artifact.py` (binds `references/artifact-contract.md`; fixture-proven in CI; also enforced independently by the eval harness, which counts a rejected artifact as a workflow failure) | before finishing | blocking | validator exit 0 on the produced document |
| Kernel/docs hygiene | this repo's own kernel files | `docs-validate` CI job | on PR | blocking | CI status |

`not_applicable` outcomes must be stated with a reason (e.g. permalinks:
not applicable — commit not pushed).

## Escalation conditions

- Continue while actions remain within granted authority. Pause when the
  research target or scope is genuinely ambiguous — ask one focused
  question rather than guessing.
- **Wrong premise:** if the question presupposes something the code
  contradicts (a component, behavior, or relationship that does not
  exist), surface the mismatch with evidence and answer the corrected
  question — do not silently comply with the false premise, and do not
  fabricate the presupposed entity.
- **Access failure:** if load-bearing sources are unreadable (missing
  submodule, permissions, absent `thoughts/`), state what was
  inaccessible and how it bounds the conclusions instead of papering over
  the gap.
