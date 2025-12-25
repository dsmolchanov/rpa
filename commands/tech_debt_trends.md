---
description: Analyze technical debt trends over time from sweep reports
argument-hint: "[weeks] - Number of weeks to analyze (default: 4)"
allowed-tools: Read, Glob, Grep, LS, Write
model: sonnet
---

# Tech Debt Trends

Analyze technical debt trajectory by comparing historical sweep reports. Use this monthly to understand if debt is increasing, decreasing, or stable.

## Usage

- `/tech_debt_trends` - Analyze last 4 weeks
- `/tech_debt_trends 8` - Analyze last 8 weeks

The argument is available as `$ARGUMENTS` (default: 4).

## Process

### Step 1: Find Historical Sweeps
- Search for all tech debt sweep reports in `thoughts/shared/debt/`
- Pattern: `*-tech-debt-sweep.md`
- Sort by date (newest first)
- Need at least 2 sweeps for trends

### Step 2: Extract Metrics from YAML Frontmatter
Parse the `metrics:` block from each sweep's YAML frontmatter:

```yaml
metrics:
  total_items: 47
  critical_items: 2
  quick_wins: 12
  debt_density: 2.3
  suppression_ratio: 1.5
  doc_coverage: 67
  config_health: 65
  dependency_health: 78
```

**Fallback**: If a sweep lacks structured metrics, skip it and note in report.

### Step 3: Calculate Trends
- Week-over-week change
- Month-over-month change
- Category-specific trends
- Identify improving vs. degrading areas

### Step 4: Generate Report
Write to: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-trends.md`

```markdown
---
date: [ISO timestamp]
type: tech-debt-trends
period_weeks: [weeks analyzed]
sweeps_analyzed: [count]
---

# Technical Debt Trends Report

**Period**: [oldest sweep] to [newest sweep]
**Sweeps Analyzed**: X

## Summary

| Metric | Start | Current | Change | Trend |
|--------|-------|---------|--------|-------|
| Total Items | X | X | +/-X | up/down/stable |
| Critical | X | X | +/-X | up/down/stable |
| Quick Wins | X | X | +/-X | up/down/stable |
| Debt Density | X | X | +/-X | up/down/stable |

## Trend Analysis

### Improving Areas
- Documentation coverage: +15% (3 sweeps)
- Lint suppressions: -12 (now 8 total)

### Degrading Areas
- TODO count: +23 in 4 weeks
- Large files: +2 new files over 500 LOC

### Stable Areas
- Circular dependencies: 2 (unchanged)
- Security vulnerabilities: 0 (maintained)

## Recommendations

Based on trends:
1. Focus on TODO reduction (growing fastest)
2. Celebrate doc improvements (sustain momentum)
3. Address new large files before they grow more

## Weekly Breakdown

| Week | Total Items | Critical | Quick Wins | Density |
|------|-------------|----------|------------|---------|
| 2025-01-01 | 47 | 2 | 12 | 2.3 |
| 2024-12-25 | 42 | 2 | 10 | 2.1 |
| 2024-12-18 | 38 | 1 | 8 | 1.9 |
```

### Step 5: Present Summary
```
Tech Debt Trends Report Complete!

**Report**: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-trends.md`

**Period**: [X weeks, Y sweeps]

**Key Findings**:
- Overall debt: [increasing/decreasing/stable] (X% change)
- Best improvement: [category] (-Y%)
- Needs attention: [category] (+Z%)

**Recommendations**:
1. [Top priority action]
2. [Secondary action]
```

## Edge Cases

### Fewer Than 2 Sweeps
```
Cannot generate trends report.

Found: X sweep reports
Required: At least 2

Run `/tech_debt_sweep` to generate your first (or another) sweep report.
```

### Missing Metrics in Older Sweeps
- Skip sweeps without structured metrics
- Note in report: "X sweeps skipped (missing metrics)"
- Recommend re-running sweep for historical baseline

### Very Old Data
- If sweeps are >6 months old, note they may not reflect current state
- Suggest running a fresh sweep

## Success Criteria
- [ ] Historical sweeps located and parsed
- [ ] Metrics extracted consistently
- [ ] Trends calculated accurately
- [ ] Recommendations based on data
