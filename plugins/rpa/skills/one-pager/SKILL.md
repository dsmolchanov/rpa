---
name: one-pager
description: >
  Produce a bounded, deterministic digest of the last work in a repository —
  what landed, what is open, what is next — from git, GitHub, and the
  repository's thoughts/shared artifacts, optionally across several
  repositories. Select when the user asks what happened recently, wants a
  status page or standup digest for a repository, or asks to refresh the
  one-pager. Do NOT select to investigate why something broke, to review a
  diff, or to author a plan; use debug, code-review, or create-plan instead.
user-invocable: true
permission-class: "read_only (repository and gh) + workspace_write (thoughts/shared/one-pagers and RPA_HOME one-pagers)"
invocation: "both"
---

# One-pager — kernel

## Intent

Answer *what landed, what is open, what is next* for a repository from facts a
machine can prove, on one screen, without the reader opening another file. The
digest is a projection of repository state, so regenerating it is idempotent
and safe to repeat at the end of every session.

## Scope & authority

Read git history, GitHub state via `gh` when it is available, and regular
files under `thoughts/shared/`. Write exactly one digest (plus its optional
`.json` companion) to `thoughts/shared/one-pagers/` in the repository, or to
`$RPA_HOME/one-pagers/` in cross-repository mode. Nothing else is modified:
not source, not other artifacts, not git state. This workflow never commits.

## Artifact contract

The digest path, structure, bounds, determinism rules, `## Sources` outcomes,
narrative rule, JSON schema, and validator checks (a)–(j) are defined once in
[`references/artifact-contract.md`](references/artifact-contract.md). Read that
file before writing a narrative. The script implements the contract; this
kernel does not restate it.

## Process guidance

1. **Establish the target.** Default to the current repository. Use
   `--repos <path>…` only when the user asks for a cross-repository page; that
   page is written outside every repository and is never committed.
2. **Choose the window deliberately.** `--since last` (the default) is right
   for a refresh: it reuses the previous page's window start when `HEAD` has
   not moved, so an unchanged rerun cannot collapse to an empty window. Pass
   an ISO date or a git ref when the user asks about a specific period.
3. **Generate.** Run
   `python3 <skill-dir>/scripts/onepager.py generate --write` (add `--json`
   when a machine will consume the page). The script prints the path it wrote.
4. **Read the result before adding anything.** A degraded source is not a
   failure to hide: a `## Sources` row reading `failed` or `not_applicable` is
   the honest report, and `gh` being absent or unauthenticated is normal.
5. **Add a narrative only when it earns its lines.** Append `## Narrative`
   with the required marker and at most 8 lines, restating only facts already
   present above it. Never introduce a pull request number, path, artifact
   name, or count that the facts do not contain — the validator rejects it,
   and a digest that invents is worse than one that is terse.
6. **Validate and report.** Run
   `python3 <skill-dir>/scripts/onepager.py validate <path>` and return the
   path plus anything a reader should act on (failed sources, `## Next`).

Tool results can be truncated, paginated, or filtered. When a file or output
is load-bearing, ensure you have seen all of it before relying on it.

## Acceptance criteria & evidence

The workflow is complete when:

1. A digest exists at the contract path and `onepager.py validate` exits 0.
2. Every fact in it came from the script; only `## Narrative` is model-written
   and it is marked as such.
3. Degraded sources are reported as `failed` or `not_applicable` with a
   reason, not silently omitted.
4. Nothing outside the digest path was written, and nothing was committed.
5. The final response names the digest path and its `## Next` items.

## Deterministic verification profile

| Gate | Applicability | Runner | When | Mode | Evidence |
|---|---|---|---|---|---|
| Digest validity | every produced digest | `python3 <skill-dir>/scripts/onepager.py validate <path>` | before finishing | blocking | exit status 0 |
| Idempotence | when refreshing an existing page | regenerate and compare | when a rerun is claimed to be a no-op | advisory | byte-identical file |
| Kernel/docs hygiene | this repository's kernel and adapter files | `python3 scripts/validate_docs.py` | before commit / in CI | blocking | exit status 0 |

Report `not_applicable` with a reason for a gate that does not apply.

## Escalation conditions

- Continue while the work stays inside the authority above.
- Stop and report when the target is not a git repository (the digest has no
  basis), or when `--write` is requested into a repository in
  cross-repository mode (the page would be committed to the wrong place).
- Report `gh` failures; do not retry them in a loop and never fabricate the
  state they would have returned.
- If the user wants a fact the sources cannot prove — who is blocked, why a
  build broke, what a reviewer meant — say so rather than inferring it into
  the narrative.
