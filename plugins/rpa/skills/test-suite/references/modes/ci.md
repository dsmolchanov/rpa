# Mode: ci [--github|--gitlab] [apply]

Generate CI test configuration through a reviewable plan.

## Procedure

1. Require a current manifest; missing → direct to `audit`.
2. Resolve the provider: the explicit flag wins; otherwise exactly one
   provider evidenced by existing repository CI files (`.github/workflows/`
   vs `.gitlab-ci.yml`). With neither evidenced or both present and no
   flag, stop and ask — never invent a platform, runtime version, or cache
   strategy the repository does not evidence.
3. Compose the workflow from the manifest's evidenced commands only.
   Include a coverage gate only when the coverage policy resolves a
   threshold, citing its source; otherwise the plan states
   `coverage gate: not_applicable — no configured threshold`.
4. Write the CI plan per the artifact contract (full file content + exact
   target path).
5. **apply**: write the one CI file the plan names, nothing else.
