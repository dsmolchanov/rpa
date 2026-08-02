---
date: 2026-08-02
type: pilot-results
scope: /research_codebase protocol-v2 replacement round
status: protocol-invalid — no verdict
---

# Protocol-v2 pilot round: terminal scorer exhaustion

## Outcome

This round is **protocol-invalid and indeterminate**. The frozen candidate is
not approved for rollout from this evidence.

The registered 42-slot randomized schedule completed and retained one
nonempty document for every slot. The artifact contract passed for 22 final
runs and rejected 20 final runs; those rejections remain counted workflow
outcomes, and all 42 documents entered the registered all-document judging
population. The scorer accepted its first required record, then exhausted all
three registered attempts for the next record because none satisfied the
exact response contract. The fail-closed terminal marker left the scorer
manifest incomplete. The verifier and deterministic aggregate were therefore
not launched.

No partial median, diagnostic substitution, response repair, fourth attempt,
selective rejudge, or prior-round reuse was performed. The complete private
run namespace, raw streams, immutable attempt records, validation outcomes,
and terminal marker are preserved unchanged.

## Registered identity

- Candidate: `b731f06cdff5f38c0fa4c5aa64f93277d69e741d`
- Withdrawn seal:
  `233987beac8d0da7c819fc159674638c3fab18a69a7d486243b63721f21be162`
- Scheduled population: 42 final runs — baseline 18, candidate 18,
  fleet-ablation 6
- Artifact gate: 22 passed, 20 rejected
- Scorer batch: incomplete after terminal three-attempt exhaustion
- Verifier batch: not launched
- Aggregate and go/no-go verdict: not produced

No private path, task text, document text, ground truth, source snapshot,
judge prose, run identifier, session identifier, or partial score is included
in this public record.

## What the round established

The invalidation path behaved as designed: strict schema validation rejected
nonconforming output, the bounded retry policy stopped at three observations,
resume was refused, and downstream judging and aggregation remained blocked.
The result identifies a prospective reliability gap in output steering, not
permission to weaken the frozen validator or reinterpret observed data.

## Required replacement round

1. Freeze and verify the prospectively registered judge-output hardening.
2. Reset registration until a clean session creates six genuinely new tasks
   in a new atomic seal.
3. Re-run installation verification plus synthetic and real-backend
   preflights on the exact pinned runtime.
4. Create and execute a completely new 42-slot randomized schedule.
5. Run the all-document scorer to completion, then the verifier, then the
   deterministic aggregate.
6. Publish only sanitized aggregates and the resulting go/no-go decision.
