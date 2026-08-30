# Test-suite artifacts — contract

Single source for every artifact the test-suite workflow persists. All
artifacts live under `thoughts/shared/test-suite/`. Field names below are
stable: downstream consumers (tdd, one-pager, debt tooling) read them, so
add fields rather than renaming.

## Common rules

- Dated artifacts use `YYYY-MM-DD-<type>.md` with the local date.
- Writing a dated artifact when a same-day file with **different** content
  exists stops for an explicit decision (archive/rename); identical content
  is an idempotent no-op.
- Markdown frontmatter always carries `date` (ISO timestamp), `type`, and
  `commit` — the checkout's **default-branch anchor**:
  `git merge-base HEAD <default-branch>` (short), which equals HEAD on the
  default branch itself; `no-git` without a repository. Branch SHAs die at
  squash-merge, so a durable stamp must be a default-branch ancestor.
- Audit artifacts are per-checkout snapshots produced by running `audit`
  on the target checkout; hand-editing a manifest (e.g. to satisfy review
  feedback) is not a valid refresh.
- Plans list every file they would touch, precisely enough that `apply` can
  be checked against the authority matrix afterwards.

## Manifest pair (mode: audit)

`test-suite-manifest.json` — canonical, machine-readable; overwritten on
every audit (point-in-time snapshot). Required fields:

```json
{
  "detected_at": "<ISO timestamp>",
  "commit": "<default-branch anchor per the common rules, or no-git>",
  "languages": ["<language>", "..."],
  "frameworks": {"test": "<framework>", "lint": null, "typecheck": null},
  "commands": {
    "test": "<evidenced command>",
    "test_single": "<command with {file}/{name} placeholders or null>",
    "test_related": null,
    "coverage": null,
    "lint": null,
    "typecheck": null
  },
  "patterns": {
    "test_files": ["<glob>"],
    "test_directories": ["<dir>"],
    "source_to_test": "<mapping description>",
    "naming_convention": "<colocated|centralized|mixed>"
  },
  "coverage_backend": {
    "available": false,
    "tool": null,
    "output_path": null,
    "threshold_config": null
  },
  "monorepo": {"detected": false, "tool": null, "packages": []},
  "existing_tests": {"count": 0, "files": [], "passing": null},
  "additional_tools": {"mocking": null, "assertions": null, "fixtures": null},
  "evidence_paths": ["<files the detection relied on: configs, CI, scripts>"]
}
```

Every command value must be evidenced by repository configuration (script
entry, config file, Makefile target) — never invented. Unknown values are
`null`, not guesses. `coverage_backend.threshold_config` names the defining
file when the repository configures a threshold (see coverage-policy).

A manifest is **current** while both hold:

1. **Lineage** — its `commit` is an ancestor of the checkout HEAD
   (`git merge-base --is-ancestor <commit> HEAD`); and
2. **Freshness** — no commit after the anchor changed the files the
   detection relied on: `git diff --name-only <commit>..HEAD` is disjoint
   from `evidence_paths` and from paths matching `patterns.test_files`.

Otherwise non-audit modes treat it as stale and direct the user to
`audit`. A `no-git` manifest carries no lineage to test: treat it as
current only within the session that produced it, and re-run `audit`
when in doubt.

`test-suite-manifest.md` — human-readable projection of the same data:
detected infrastructure table, patterns, commands table, existing-test
summary, coverage backend, suggested next modes. It restates the JSON; it
never carries data the JSON lacks.

## Harmonization plan (mode: adopt)

`YYYY-MM-DD-test-adopt-plan.md`, `type: test-adopt-plan`. Body: detected
layers table (layer, runner, config, command, approximate count); proposed
glue files with full contents (wrapper script, marked script blocks,
Makefile targets — additions only, never moved or rewritten tests); a note
per mixed-framework pair (run both, report separately; suggest
`standardize` for unification).

## Init plan (mode: init)

`YYYY-MM-DD-test-init-plan.md`, `type: test-init-plan`, frontmatter also:
`source_manifest`, `files_to_create`. Body per file: source path, target
test path (manifest convention), functions covered, mock strategy, scaffold
preview. Scaffolds use explicit pending/skipped constructs or TODO
assertions that the framework reports as pending — never an empty test body
that passes silently.

## Update plan (mode: update)

`YYYY-MM-DD-test-update-plan.md`, `type: test-update-plan`, frontmatter
also: `changed_files`, `affected_tests`, `safe_updates`, `approval_needed`,
`deletions`. Body sections in this order: Safe Updates (non-behavioral:
renames, moves, import paths, signature-call syncs) with diffs; Requires
Approval (assertion values, expected errors, snapshots, new required
parameters) each with the source change, the proposed test diff, and the
open question; Suggested Deletions (removed code) with per-item options —
never auto-applied.

## Gap report (mode: gaps)

`YYYY-MM-DD-gaps-report.md`, `type: test-gaps-report`, frontmatter also:
`mode: static|runtime`. Gaps are grouped by qualitative priority — high /
medium / low — where each entry states its evidence: behavior criticality,
dependency reach (import fan-in), recent change, security relevance, and
observed test absence or weakness. There is no numeric gap score. Runtime
reports additionally cite the coverage data source; a runtime request
without usable coverage data produces no report (see the gaps mode file).

## CI plan (mode: ci)

`YYYY-MM-DD-test-ci-plan.md`, `type: test-ci-plan`, frontmatter also:
`provider: github|gitlab`. Body: the complete proposed workflow file
content, its exact target path, the commands sourced from the manifest, and
the coverage-gate decision per the coverage policy (a gate appears only
when a threshold resolves; otherwise the plan states
`coverage gate: not_applicable — no configured threshold`).

## Migration plan (mode: standardize)

`YYYY-MM-DD-test-migration-plan.md`, `type: test-migration-plan`,
frontmatter also: `from_framework`, `to_framework`, `files_to_migrate`,
`safe`, `needs_review`, `dead_tests`. Body: Safe Migrations (target path +
full diff per file), Needs Review (semantic ambiguity — custom matchers,
complex mocks — with the reason), Dead Tests (unresolvable source imports,
listed with evidence, never auto-deleted), and Verification (exact
commands; expectation: each migrated test preserves its pre-migration
pass/fail status).
