---
name: enhance-research
description: >
  Improve an existing codebase research document by verifying and synthesizing
  supplied corrections, missing areas, or additional perspectives while
  preserving a factual description of the current system. Select when the user
  names a research artifact and provides feedback to incorporate. Do NOT
  select for new research, recommendations, implementation planning, code
  review, or source changes; use research-codebase, create-plan, or the
  relevant review workflow instead.
user-invocable: true
permission-class: "read_only (target repo and feedback) + workspace_write (named research document only)"
invocation: "both"
---

# Enhance Research — kernel

## Intent

Correct and deepen an existing research artifact from supplied feedback. Verify
material claims against the current checkout, integrate confirmed findings
into the document's existing narrative, and preserve a traceable, citation-
backed account of what exists today.

## Scope & authority

Read the target research document, supplied feedback, repository sources, and
related `thoughts/` artifacts. Write authority is limited to the named document
under `thoughts/shared/research/`. Remain a documentarian: do not turn feedback
into recommendations, defect judgments, implementation plans, or source edits
unless the original research question explicitly includes that perspective.

## Artifact contracts

- Preserve the research artifact shape and metadata semantics from
  [`../research-codebase/references/artifact-contract.md`](../research-codebase/references/artifact-contract.md).
- Record substantive enhancement work using
  [`references/enhancement-record.md`](references/enhancement-record.md).

Read both before editing. The research artifact contract is the single source
for `last_updated`, `last_updated_by`, and `enhancement_note` behavior.

## Process guidance

1. **Require the document and feedback.** Identify the research path and the
   corrections, omissions, or perspectives to assess. If either is missing,
   ask one focused question. Report an inaccessible file or link instead of
   silently excluding it.
2. **Read the full context.** Read the entire research artifact, applicable
   repository instructions, and every supplied feedback source. Recover the
   original research question, checkout metadata, findings, and citations.
3. **Classify the feedback.** Group duplicates and distinguish factual
   corrections, missing coverage, requested depth, alternative interpretations,
   and structural improvements. Identify which claims need new evidence.
4. **Verify proportionally.** Re-check every factual correction and new
   repository claim against the current checkout. Use the shared fleet routing
   at
   [`../research-codebase/references/fleet-routing.md`](../research-codebase/references/fleet-routing.md)
   only for independent, sizeable investigation tracks. Read load-bearing
   source files in the main context before relying on an agent result.
5. **Reconcile checkout drift.** If the artifact's recorded commit differs
   from the current checkout, distinguish a correction to the original
   snapshot from behavior that changed later. Do not silently rewrite history;
   state the verified checkout context in the enhancement notes.
6. **Integrate confirmed findings.** Correct inaccurate text in place and add
   missing facts to the relevant sections. Keep every verifiable claim tied to
   a `file:line` citation or authoritative external source. Preserve accurate
   content and the documentarian tone.
7. **Update metadata and record.** Apply the artifact contract's enhancement
   metadata exactly. Add one concise enhancement record when changes are
   substantive; do not append a second disconnected research report.
8. **Report the result.** Return the document path, main corrections/additions,
   rejected feedback with evidence, and any checkout-time limitation.

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing for the enhancement, ensure you have seen all of it before
relying on it.

## Acceptance criteria & evidence

The workflow is complete when:

1. Only the named research artifact is modified.
2. Every material feedback theme is incorporated, adapted, or rejected with an
   evidence-backed reason.
3. The document still answers its original research question and conforms to
   the research artifact contract.
4. New or changed factual claims carry current citations; historical claims
   remain clearly distinguished from current-checkout evidence.
5. `last_updated`, `last_updated_by`, and `enhancement_note` follow the
   contract, and substantive work has one enhancement record.
6. No recommendation or proposed future state is introduced as though it were
   current behavior.
7. The final response links the artifact and summarizes corrections,
   additions, rejected claims, and evidence limits.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Path authority | every enhancement | inspect changed paths | before finishing | blocking | only the named research file is changed |
| Artifact schema | every enhancement | `skills/research-codebase/evals/public/validate_artifact.py` | before finishing | blocking | validator exit 0 |
| Feedback coverage | every enhancement | compare material themes with the enhancement record | before finishing | blocking | each theme has a disposition |
| Citation integrity | every factual change | inspect cited source at the relevant checkout | before finishing | blocking | matching `file:line` or external source |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

Record `not_applicable` with a reason for gates the enhancement does not touch.

## Escalation conditions

- Continue while verification and edits stay within the named research
  artifact.
- Pause when the path or feedback is missing, required evidence is
  inaccessible, or feedback changes the original research question enough to
  require a new artifact.
- When feedback is contradicted by code, preserve the verified fact and explain
  the mismatch; do not incorporate the claim for politeness.
