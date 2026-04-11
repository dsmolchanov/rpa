# Review guidelines (Codex + Claude Auto-fix)

This file steers Codex's native GitHub review and Claude Code on the web's
Auto-fix behavior on every PR in this repository.

## Severity

Codex only surfaces **P0** and **P1** findings in GitHub by default. Elevate
the following to **P1 `[BLOCKER]`**:

- Any deviation from the plan at `thoughts/shared/plans/*.md` on this branch.
- Any test specified in `thoughts/shared/tests/*.md` that is missing, skipped,
  or weakened.
- Security issues, correctness bugs, data-loss risks, auth regressions.
- Missing input validation on user-facing boundaries.
- Any change to files listed in `CODEOWNERS` without a corresponding entry in
  the plan.

Mark the following as **P2 `[NIT]`**:

- Style, naming, formatting, micro-optimizations.
- Anything the existing linter would catch (let CI handle it).

## Auto-fix response budget

When Claude Code on the web Auto-fix responds to review comments or CI
failures on a PR in this repo:

1. **Batch ALL open `[BLOCKER]` comments and current CI failures into ONE fix
   commit.** Do not reply per-comment. Do not churn on `[NIT]`s.
2. **Resolve every `[BLOCKER]` before touching any `[NIT]`.** Never flip the
   order.
3. **If a comment is genuinely ambiguous, tag the thread `Needs Decision` and
   stop.** Do not guess at architectural intent.
4. **Do not open follow-up PRs from an Auto-fix session.** If something is
   out of scope for this PR, note it in the PR body under "Out-of-scope
   findings" and leave it for the humans.

## Scope discipline

- Stay inside the plan. If you find a bug that isn't in scope, note it in the
  PR body and do NOT fix it in the same commit.
- Do not refactor unrelated code.
- Do not add dependencies, feature flags, or backwards-compat shims unless the
  plan explicitly lists them.
- Do not modify `.github/`, `CODEOWNERS`, `AGENTS.md`, or this file itself
  unless the plan says so.

## Merge gate reminder

CI + the `codex-review-window` soak check are the **only** hard merge gates.
Codex review is **advisory** — if you find a blocker post-merge, open a
follow-up PR.
