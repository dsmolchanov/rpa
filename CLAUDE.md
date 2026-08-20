@AGENTS.md

# Guidance for Claude Code on the web (Auto-fix)

This file is read by any Claude Code on the web session spawned against this
repository, including Auto-fix sessions started from `plaintalk-dev-agent`.

## Durable artifacts on PR branches

Every PR opened by `plaintalk-dev-agent` commits these files before the PR
becomes visible:

- `thoughts/shared/plans/<date>-<slug>.md` — the authoritative plan.
- `thoughts/shared/tests/<date>-TEST-<slug>.md` — the test plan (Red-phase
  spec) the implementation was required to satisfy.
- `thoughts/shared/implementations/<date>-<slug>-validation.md` — the
  `/validate_plan` report comparing the commit history to the plan.

**Start every Auto-fix session by reading all three files in full.** They are
the source of truth for "what was supposed to happen" on this PR. Deviations
from the plan are P1 `[BLOCKER]`s (see `AGENTS.md`).

## Session model

Auto-fix sessions start from a **fresh clone**. Nothing on the Fly machine
that created the PR carries over. You only have what is checked into the
branch.

- The `CLAUDE_CODE_OAUTH_TOKEN` that started this session belongs to
  `dsmolchanov`. All follow-up commits land under that identity.
- The session is billed against the Claude Max subscription.
- When `plaintalk-dev-agent` triggers a session via
  `claude -p "/autofix-pr"`, the Claude GitHub App relays subsequent PR
  review-comment and CI-failure events into this session.

## Fix-commit conventions

- **Batch** all open blockers + CI failures into one commit. Do not reply
  per-comment.
- Commit messages: `fix(<scope>): <short summary> (responds to Codex review)`.
- Never force-push. Never amend merged commits.
- Never touch `AGENTS.md`, `CLAUDE.md`, `.github/workflows/codex-review-window.yml`,
  or branch protection in a fix commit.

## What counts as "done"

A fix pass is done when:

- Every open `[BLOCKER]` review comment has a corresponding code change.
- CI is green or the failures are explicitly covered by the batched fix.
- The fix does not introduce out-of-scope changes.
- The `codex-review-window` check will re-fire on your push, giving Codex
  another soak window to re-review. Do not try to merge manually.

Auto-merge is already queued at the PR level; the merge fires when branch
protection is satisfied.
