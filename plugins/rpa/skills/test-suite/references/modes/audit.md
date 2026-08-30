# Mode: audit

Detect test infrastructure and refresh the manifest pair. `audit` rejects
`apply` — its writes are always the two manifest files.

## Procedure

1. Record git identity (`git rev-parse --short HEAD`, else `no-git`).
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
