# Technical debt artifacts — contract

## Paths

- Sweep: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-sweep.md`
- Paydown: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-paydown.md`
- Apply report: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-applied.md`

Use a disambiguating suffix when more than one artifact of a type is produced
on the same date. Never overwrite historical evidence from a different commit.

## Sweep frontmatter

```yaml
---
date: [ISO timestamp with timezone]
type: tech-debt-sweep
metrics_schema: 1
commit: [full git commit]
branch: [branch or detached@short-sha]
repository: [repository name]
previous_sweep: [path or null]
metrics:
  total_items: [integer]
  critical_items: [integer]
  quick_wins: [integer]
  debt_density: [number]
  suppression_ratio: [number]
  doc_coverage: [number]
  config_health: [number]
  dependency_health: [number]
  god_modules_count: [integer]
  god_modules_severe: [integer]
  god_modules_high: [integer]
  god_modules_worst_score: [number]
---
```

### Metrics schema 1 definitions

These definitions are the single source consumed by sweep/trends workflows:

- `total_items`: count of deduplicated finding IDs.
- `critical_items`: finding IDs classified critical because they represent an
  evidenced security, data-loss, credential, correctness, or release-blocking
  risk.
- `quick_wins`: paydown entries proven `auto_fixable: true` by the eligibility
  contract below.
- `debt_density`: `total_items / analyzed source KLOC`; exclude generated,
  vendored, fixture, and dependency code and record the analyzed LOC source.
- `suppression_ratio`: suppression directives divided by analyzed source LOC,
  multiplied by 100.
- `doc_coverage`: documented eligible public symbols divided by eligible public
  symbols, multiplied by 100. Record the symbol detector and exclusions.
- `config_health`: compliant configuration sites divided by all assessed
  configuration sites (compliant plus evidenced hardcoded environment-specific
  sites), multiplied by 100.
- `dependency_health`: assessed direct dependencies without an evidenced
  health finding divided by assessed direct dependencies, multiplied by 100.
- `god_modules_count`, `god_modules_severe`, `god_modules_high`, and
  `god_modules_worst_score`: values emitted by the owning god-module scanner
  under its current scoring contract. Do not reproduce that formula here.

Round ratios consistently to two decimal places. A category with no eligible
denominator records `0` plus an adjacent measurement note of
`not_applicable — zero eligible denominator`; trends must not interpret that
zero as bad health. Changing a key's meaning requires a new schema version and
an updated trends consumer.

## Sweep body

```markdown
# Technical Debt Sweep Report

## Scope and Evidence

- Repository/commit/branch
- Included and excluded paths
- Languages and tooling
- Commands, versions, exits, dates, and external advisory sources
- `not_assessed` categories and reasons
- Metric numerators, denominators, and measurement sources

## Executive Summary

- Total, critical, and auto-fixable finding counts
- Highest-consequence themes
- Important evidence limitations

## Findings

### [Category]

#### [DEBT-ID] [Finding title]

- **Severity / consequence**:
- **Location and evidence**:
- **Confidence**:
- **Remediation**:
- **Verification**:
- **Disposition**: [pay down / accept / investigate / not_assessed]

## God-Module Shortlist

[Ranked scanner output with paths/scores/classifications and false-positive
notes; no duplicate scoring formula]

## Trends vs Previous Compatible Sweep

[Per-key comparison, new/resolved IDs, or Not applicable — reason]

## References

[Repo files, retained tool output, advisory sources, and prior sweep]
```

## Paydown frontmatter and entries

```yaml
---
date: [ISO timestamp with timezone]
type: tech-debt-paydown
repository: [repository name]
source_commit: [full commit]
source_sweep: [path]
auto_fixable_count: [integer]
---
```

Order entries by prerequisite and risk rather than invented hour estimates.
Each entry has this shape:

```markdown
## [PAY-ID] [Outcome]

- **Findings**: [DEBT-IDs]
- **Priority and reason**:
- **Target paths**:
- **Proposed change**:
- **Prerequisites**:
- **Risk / authority required**:
- **auto_fixable**: [true | false]
- **Deterministic runner**: [exact command and exact paths, or Not applicable]
- **Expected diff class**: [format-only/generated-index/etc., or Not applicable]
- **Verification**: [exact commands]
- **Rollback**: [targeted reversal approach]
```

`auto_fixable: true` is permitted only when all target paths, preconditions,
runner, expected diff class, verification, and targeted rollback are present;
the operation intends no behavior, dependency, credential, API, schema, or
architecture change. Debug/comment/dead-code deletion and suppression removal
are not automatically eligible.

## Apply report

```markdown
---
date: [ISO timestamp with timezone]
type: tech-debt-applied
repository: [repository name]
source_commit: [paydown source commit]
applied_commit: [checkout commit before apply]
source_paydown: [path]
---

# Technical Debt Apply Report

## Baseline

- Existing worktree changes
- Drift from source commit
- Selected PAY-IDs

## Outcomes

| PAY-ID | Outcome | Paths | Diff-class check | Verification evidence |
|---|---|---|---|---|
| [ID] | [applied/skipped/stale/failed/manual] | [paths] | [result] | [commands/exits] |

## Final Diff and Verification

- Changed paths attributable to this apply
- Commands and exits
- Unrelated baseline failures
- Remaining manual work
```
