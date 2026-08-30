# Mode: audit

Detect test infrastructure and refresh the manifest pair. `audit` rejects
`apply` — its writes are always the two manifest files.

## Procedure

1. Record the default-branch anchor per the artifact contract:
   `git merge-base HEAD <default-branch>` (short), resolving the default
   branch via `git symbolic-ref --short refs/remotes/origin/HEAD` or the
   repository's documented mainline. On the default branch this is HEAD.
   If the default branch cannot be determined and HEAD is not evidently
   on it, stop and ask rather than stamping a branch HEAD that a
   squash-merge would discard. Without a repository: `no-git`.
2. Delegate infrastructure detection to `test-analyzer` (contract:
   `../agent-contracts/test-analyzer.md`): frameworks, conventions,
   commands, coverage backend, monorepo layout, existing test inventory.
   For a small repository whose layout a few direct reads settle, skip the
   delegation and gather the same fields directly.
3. Write `test-suite-manifest.json` and its Markdown projection per the
   artifact contract. Every command must be evidenced by repository
   configuration; unknown values stay `null`.
4. Report the detected stack, the evidenced test command, and suggested
   next modes.

## Idempotency

The manifest is a point-in-time snapshot: audit always overwrites both
files. This is the one artifact family exempt from the same-day collision
rule.
