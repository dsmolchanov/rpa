# Mode: adopt [apply]

Harmonize existing suites in a legacy repository — unified execution and
reporting **without** moving or rewriting any test file. For active
migration to a single framework, route to `standardize` instead.

## Procedure

1. Require a current manifest listing all detected layers and runners
   (mixed frameworks included). Missing manifest → direct to `audit`.
2. Group existing tests by layer (unit/integration/e2e) and runner; record
   runner, config file, invocation command, and approximate count per
   layer.
3. Propose only safe, reversible glue additions:
   - a wrapper script running each layer in sequence (e2e behind an opt-in
     flag),
   - script entries added as clearly marked blocks,
   - Makefile targets where a Makefile already exists,
   - per-layer CI jobs (handoff to the `ci` mode).
4. Write the harmonization plan per the artifact contract, with full glue
   file contents and a note per mixed-framework pair.
5. **apply**: write the plan's glue files and marked blocks, then run the
   wrapper once to verify every layer executes; report per-layer results.

## Idempotency

Existing glue is detected and updated in place; marked blocks are replaced,
never duplicated. Re-running without changes is a no-op.
