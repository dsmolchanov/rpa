---
task-id: dev-3
archetype: "3 — narrow where-is"
target-repo: dsmolchanov/rpa
target-sha: d86e82ded8fd7e90cafb8abd00a2ebae15463540
set: dev
---

# dev-3 — narrow where-is (rpa)

## Task prompt

Where is the god-module scoring formula defined in this repository, and
which other files restate it? I just need the authoritative location and
the list of copies.

## Ground truth (visible — dev set)

A correct document must contain:

1. Authoritative definition: the module scoring table in
   `agents/god-module-finder.md:23-30` (Size 30 / Public Surface 20 /
   Fan-In 20 / Fan-Out 10 / Smell Density 10 / Hotspot 10).
2. Restatement in `commands/refactor_candidates.md:57` (inline weighted
   scoring in the Task prompt).
3. Restatement in `commands/tech_debt_sweep.md:132` (same inline formula).
4. Restatement in `commands/refactor.md:44-49` (bulleted weights).
5. The duplication is a recorded single-source-of-truth violation:
   `docs/conventions.md` §9 lists "god-module scoring (4 copies)" among
   known violations to fix during rollout.

Scoring notes: facts 1–4 are the answer; fact 5 distinguishes a thorough
doc. **Efficiency expectation (this is the over-orchestration probe):** the
question is answerable with a handful of searches; a proportionate run
should need no subagents at all — heavy fan-out here is the waste this
archetype measures.
