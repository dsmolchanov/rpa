---
task-id: dev-4
archetype: "4 — code + prior thoughts/ docs"
target-repo: dsmolchanov/rpa
target-sha: d86e82ded8fd7e90cafb8abd00a2ebae15463540
set: dev
---

# dev-4 — code plus thoughts history (rpa)

## Task prompt

What is the current decision status of migrating this plugin's commands to
the skills format? Trace how the decision evolved and which artifacts
record each stage, including what exists in the tree today.

## Ground truth (visible — dev set)

A correct document must contain:

1. The original decision: roadmap item 18 in
   `thoughts/shared/plans/2026-06-10-plugin-improvement-roadmap.md:82` —
   evaluated 2026-06-12, verdict **defer**, because migration would
   fragment the flat `commands/*.md` layout Quick Install depends on.
2. The supersession: the same roadmap line now carries "**Superseded
   2026-07-26 for the research workflow family only**", pointing to
   conventions and the pilot plan.
3. The new convention: `docs/conventions.md` §1 — the kernel carrier for a
   workflow is a **skill package** (`skills/<workflow>/`), with
   `commands/*.md` as thin platform adapters.
4. The authorization and packaging consequences: the pilot plan's
   Packaging section
   (`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`)
   — the rewrite PR must extend Quick Install to copy `skills/` and bump
   `.claude-plugin/plugin.json` version at candidate release.
5. What exists today: `skills/research-codebase/` is a structural skeleton
   only — deliberately non-invocable (`user-invocable: false`,
   `disable-model-invocation: true`, kernel `invocation: none` in
   `skills/research-codebase/SKILL.md`), with the artifact contract already
   extracted verbatim at
   `skills/research-codebase/references/artifact-contract.md`; behavior
   still lives in `commands/research_codebase.md` (frozen baseline).
6. Scope boundary: all other command families remain on the deferred
   decision until their own gates (roadmap supersession note).

Scoring notes: facts 1–2 require reading `thoughts/` history, facts 3–5
require the current tree — the archetype tests joining both sources; a doc
built from only one source is incomplete.
