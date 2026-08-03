---
description: Discover and index God-like modules for refactoring candidates
argument-hint: "[path] - Directory to scan (default: repo root)"
allowed-tools: Read, Glob, Grep, LS, Task, Write, Bash(wc -l:*), Bash(git log:*), Bash(git rev-parse:*)
---

# Refactor Candidates Discovery

You are tasked with discovering and indexing God-like modules/scripts that need refactoring. This command creates a persistent artifact for trends, sharing, and CI automation.

## Usage

- `/refactor_candidates` - Scan entire repo
- `/refactor_candidates src/` - Scan specific directory
- `/refactor_candidates --monorepo` - Group by package/workspace

The target path is available as `$ARGUMENTS`.

## Initial Response

```
Scanning for God-like modules...

I'll analyze all source files and rank them by:
1. Size (lines of code)
2. Public API surface (exports)
3. Coupling (fan-in/fan-out)
4. Code smells (TODO/FIXME, suppressions)
5. Churn hotspot (if git available)

Generating index artifact...
```

## Discovery Process

### Step 1: Detect Project Type and Structure

1. **Check for monorepo markers**:
   - `packages/`, `apps/`, `libs/` directories
   - `lerna.json`, `pnpm-workspace.yaml`, `nx.json`
   - Multiple `package.json`, `go.mod`, `Cargo.toml` files

2. **Identify all source directories**:
   - Group by package/workspace if monorepo
   - Note language per directory

### Step 2: Run God Module Finder

Spawn the `god-module-finder` agent with enhanced scoring:

```yaml
Task - Find God Modules:
  subagent_type: god-module-finder
  Prompt: |
    Scan [directory] for God-like modules.
    Use weighted scoring: size(30) + surface(20) + fan_in(20) + fan_out(10) + smell(10) + hotspot(10)

    Classify each candidate:
    - SEVERE (score >= 85)
    - HIGH (score >= 70)
    - MEDIUM (score >= 55)
    - LOW (score >= 40)

    For scripts (*.sh, if __name__=="__main__"), use script weights.
    Flag "big but cohesive" files as lower priority.

    Return: Ranked list with scores, reasons, recommended split strategy.
    STRICT LIMIT: 150 lines.
```

### Step 3: Enrich with Hotspot Data (Optional)

If git is available, add churn data:

```bash
# Get files with most commits in last 6 months
git log --since="6 months ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
```

Cross-reference with God module candidates to identify "painful" files (big + hot).

### Step 4: Generate Index Artifact

Write to: `thoughts/shared/debt/YYYY-MM-DD-god-modules-index.md`

**CRITICAL**: Include YAML frontmatter for machine parsing and trends.

```markdown
---
date: [ISO timestamp]
type: god-modules-index
commit: [git rev-parse --short HEAD]
branch: [git branch --show-current]
scan_path: [directory scanned]
total_files_scanned: 234
total_candidates: 12
severe_count: 2
high_count: 4
medium_count: 6
metrics:
  average_god_score: 67.3
  worst_file: src/utils/helpers.ts
  worst_score: 94
---

# God Modules Index

**Generated**: YYYY-MM-DD HH:MM
**Commit**: [hash]
**Scan Path**: [path]

## Executive Summary

- **Files Scanned**: 234
- **Candidates Found**: 12
- **Severe (>=85)**: 2 - immediate attention needed
- **High (>=70)**: 4 - plan for this quarter
- **Medium (>=55)**: 6 - backlog items

## Candidates by Severity

### SEVERE (Score >= 85)

#### 1. `src/utils/helpers.ts` - Score: 94

| Metric | Value | Max | Contribution |
|--------|-------|-----|--------------|
| LOC | 850 | 30 | 25.5 |
| Exports | 40 | 20 | 20 |
| Fan-In | 60 | 20 | 20 |
| Fan-Out | 12 | 10 | 10 |
| Smells | 8 | 10 | 8.5 |
| Churn | 45 commits | 10 | 10 |

**Why it's God-like**:
- Kitchen sink naming (`helpers`, `utils`)
- Mixes: string manipulation, date formatting, auth helpers, API wrappers
- Imported by 60 files (coupling magnet)
- High churn (45 commits in 6 months)

**Classification**: Module (not script)
**Cohesion**: LOW - mixed domains
**Recommended Split**: Domain-first (auth, strings, dates, api)

**Next Action**: Run `/refactor src/utils/helpers.ts`

---

#### 2. `scripts/deploy.sh` - Score: 88

| Metric | Value | Max | Contribution |
|--------|-------|-----|--------------|
| LOC | 420 | 30 | 12.6 |
| Commands | 35 | 20 | 20 |
| Side Effects | 15 | 20 | 15 |
| Smells | 12 | 10 | 10 |
| Churn | 30 commits | 10 | 10 |

**Why it's God-like**:
- Does: build, test, docker, deploy, notify, cleanup
- 35 external commands
- Complex branching logic
- Hardcoded paths and credentials

**Classification**: Script (entrypoint)
**Cohesion**: LOW - pipeline stages mixed
**Recommended Split**: Pipeline modules + thin orchestrator

**Next Action**: Run `/refactor scripts/deploy.sh`

---

### HIGH (Score >= 70)

[Similar format for 4 candidates...]

### MEDIUM (Score >= 55)

[Condensed list with scores and one-line reasons...]

---

## Big But Cohesive (Not God-like)

These files are large but don't need refactoring:

| File | LOC | Why Cohesive |
|------|-----|--------------|
| src/types/schema.ts | 450 | Pure type definitions, no logic |
| src/constants/errors.ts | 320 | Error codes only, data file |
| generated/api-types.ts | 1200 | Auto-generated, don't touch |

---

## Monorepo Breakdown

(If applicable)

| Package | Candidates | Worst File | Score |
|---------|------------|------------|-------|
| @app/web | 3 | components/Form.tsx | 72 |
| @app/api | 2 | services/user.ts | 81 |
| @shared/utils | 1 | index.ts | 94 |

---

## Trend vs Previous Index

(If previous index exists)

| Metric | Previous | Current | Delta |
|--------|----------|---------|-------|
| Total Candidates | 10 | 12 | +2 |
| Severe | 1 | 2 | +1 |
| Average Score | 64.2 | 67.3 | +3.1 |

**New God Modules Since Last Scan**:
- `src/api/client.ts` (was 52, now 71) - grew from feature additions

**Resolved Since Last Scan**:
- `src/services/auth.ts` (was 78, refactored to 45)

---

## Next Actions

1. **Immediate**: Refactor `src/utils/helpers.ts` - highest impact
2. **This Week**: Address `scripts/deploy.sh` - reliability risk
3. **This Sprint**: Plan refactoring for HIGH candidates
4. **Backlog**: Monitor MEDIUM candidates for growth
```

### Step 5: Optionally Write JSON Index

For machine parsing and CI integration:

Write to: `thoughts/shared/debt/YYYY-MM-DD-god-modules-index.json`

```json
{
  "date": "2025-12-25T10:30:00Z",
  "commit": "abc1234",
  "candidates": [
    {
      "path": "src/utils/helpers.ts",
      "score": 94,
      "severity": "SEVERE",
      "metrics": {
        "loc": 850,
        "exports": 40,
        "fan_in": 60,
        "fan_out": 12,
        "smells": 8,
        "churn": 45
      },
      "classification": "module",
      "cohesion": "LOW",
      "recommended_split": "domain-first",
      "domains_detected": ["auth", "strings", "dates", "api"]
    }
  ]
}
```

### Step 6: Present Summary

```
God Modules Index Generated!

**Artifact**: `thoughts/shared/debt/YYYY-MM-DD-god-modules-index.md`
**JSON**: `thoughts/shared/debt/YYYY-MM-DD-god-modules-index.json`

## Summary
- Files scanned: 234
- Candidates found: 12
- Severe: 2 (immediate action)
- High: 4 (plan this quarter)

## Top 3 Worst Offenders
1. `src/utils/helpers.ts` - Score 94 (SEVERE)
2. `scripts/deploy.sh` - Score 88 (SEVERE)
3. `src/services/user.ts` - Score 81 (HIGH)

## Quick Actions
- `/refactor src/utils/helpers.ts` - Refactor worst file
- `/tech_debt_sweep` - Full debt analysis including these
- View trends: `cat thoughts/shared/debt/*-god-modules-index.md`
```

## Success Criteria

- [ ] All source files scanned
- [ ] Candidates ranked with consistent scoring
- [ ] YAML frontmatter includes all metrics for trends
- [ ] Monorepo candidates grouped by package
- [ ] "Big but cohesive" false positives excluded
- [ ] Previous index compared if exists
- [ ] Actionable next steps provided
