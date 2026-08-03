---
description: Scan codebase for technical debt and generate actionable paydown plan
argument-hint: "[apply] - Run without args to scan, with 'apply' to auto-fix safe issues"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, Bash
---

# Tech Debt Sweep

You are tasked with performing a comprehensive technical debt sweep of the codebase. This command produces two artifacts: a debt report (research) and a paydown plan.

## Usage

- `/tech_debt_sweep` - Scan and generate report + plan (no changes made)
- `/tech_debt_sweep apply` - After review, apply safe fixes automatically

The argument is available as `$ARGUMENTS`. Check if it equals "apply" to determine mode.

## Initial Response

When invoked WITHOUT `apply`:
```
Starting technical debt sweep...

I'll analyze the codebase for:
1. Dependency health (security, outdated, unused)
2. Code debt markers (TODO/FIXME, lint suppressions)
3. Architecture issues (boundaries, cycles, god modules)
4. Documentation drift (README accuracy, docstring coverage)
5. Configuration hygiene (hardcoded values, credentials)

This will generate:
- Debt Report: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-sweep.md`
- Paydown Plan: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-paydown.md`

Scanning now...
```

When invoked WITH `apply`:
```
Applying safe fixes from the most recent debt sweep...

Safe fixes include:
- Removing console.log/print debug statements
- Deleting commented-out code blocks
- Running auto-formatters (prettier, black, etc.)
- Applying lint auto-fixes (eslint --fix, etc.)

NOT included (too risky for automation):
- Dependency updates (can break builds)
- Refactoring (requires human review)
- Credential rotation (requires manual verification)

I'll create a validation report after applying fixes.
```

## Sweep Process (No Apply)

### Step 1: Detect Project Type
- Check for package managers (npm, pip, go, cargo, etc.)
- Identify linters and formatters in use
- Note test framework(s)
- Determine primary language(s)

### Step 2: Ensure Debt Directory Exists
```bash
mkdir -p thoughts/shared/debt
```

### Step 3: Run Security Audits (Optional, if tools available)

Before spawning agents, run security audit tools and capture output for agent analysis:

```bash
# Capture audit output if tools are available
npm audit --json > /tmp/npm-audit.json 2>/dev/null || true
pip-audit --format json > /tmp/pip-audit.json 2>/dev/null || true
```

### Step 4: Spawn Parallel Debt Scans

**CRITICAL**: The main command spawns agents directly via Task tool. Do NOT use parallel-worker as a subagent orchestrator (subagents cannot spawn subagents).

Use Task tool to spawn all scanners in parallel (single message with multiple Task calls):

```yaml
Task 1 - Dependencies:
  subagent_type: dependency-auditor
  Prompt: |
    Audit all dependency manifests in this project.
    Find: missing lockfiles, risky version specs, unused dependencies.
    If /tmp/npm-audit.json exists, include its findings.
    Return: prioritized list with recommended verification commands.
    Limit response to 100 lines.

Task 2 - Debt Markers:
  subagent_type: debt-scanner
  Prompt: |
    Scan for technical debt markers.
    Find: TODO/FIXME, lint suppressions, complexity hot spots, stale code.
    Return: categorized findings with file:line references.
    Limit response to 150 lines (summarize if >50 items per category).

Task 3 - Architecture:
  subagent_type: architecture-guard
  Prompt: |
    Analyze architectural health.
    Find: boundary violations, suspected circular deps, god modules.
    Return: top issues with fix recommendations.
    Limit response to 120 lines.

Task 4 - Documentation:
  subagent_type: docs-auditor
  Prompt: |
    Audit documentation accuracy.
    Find: outdated README, missing docstrings, broken examples.
    Return: issues with line numbers and fix suggestions.
    Limit response to 100 lines.

Task 5 - Configuration:
  subagent_type: config-auditor
  Prompt: |
    Scan for hardcoded configuration values.
    Find: hardcoded paths, URLs, potential credentials (REDACT these!), magic values.
    Return: prioritized findings with externalization recommendations.
    Limit response to 100 lines.

Task 6 - God Modules:
  subagent_type: god-module-finder
  Prompt: |
    Scan for God-like modules (monolithic files needing refactoring).
    Use weighted scoring: size(30) + surface(20) + fan_in(20) + fan_out(10) + smell(10) + hotspot(10)
    Classify: SEVERE (>=85), HIGH (>=70), MEDIUM (>=55), LOW (>=40)
    Flag "big but cohesive" files as false positives.
    Return: Top 10 candidates ranked by score with recommended split strategy.
    Limit response to 100 lines.
```

**Note**: test-runner is invoked separately after synthesis for verification, not as part of the scan.

### Step 5: Synthesize Findings
After all agents complete:
- Consolidate findings into unified debt report
- Calculate debt metrics
- Compare with previous sweep if exists
- Identify quick wins vs. planned work

### Step 6: Generate Debt Report
Write to: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-sweep.md`

**CRITICAL**: Include structured metrics in YAML frontmatter for reliable trends parsing.

Structure:
```markdown
---
date: [ISO timestamp]
type: tech-debt-sweep
metrics_schema: 1  # bump only when metric keys change meaning; trends uses this to detect drift
commit: [git rev-parse --short HEAD]
branch: [git branch --show-current]
previous_sweep: [path to last sweep if exists]
metrics:
  total_items: 47
  critical_items: 2
  quick_wins: 12
  debt_density: 2.3
  suppression_ratio: 1.5
  doc_coverage: 67
  config_health: 65
  dependency_health: 78
  god_modules_count: 12
  god_modules_severe: 2
  god_modules_high: 4
  god_modules_worst_score: 94
---

**Metrics schema is a stable contract** (`/tech_debt_trends` parses it):
keys may be ADDED freely; renaming or changing the meaning of an existing
key requires bumping `metrics_schema` and teaching trends both versions.

# Technical Debt Sweep Report

**Date**: YYYY-MM-DD
**Commit**: [current git commit]
**Branch**: [current branch]

## Executive Summary
- Total debt items: 47
- Critical items: 2 (credentials, security vulns)
- Quick wins available: 12
- Estimated cleanup time: 3 hours

## Debt by Category

### Dependencies
[Summary from dependency-auditor]

### Code Quality
[Summary from debt-scanner]

### Architecture
[Summary from architecture-guard]

### Documentation
[Summary from docs-auditor]

### Configuration
[Summary from config-auditor]

### God Modules
[Summary from god-module-finder]

## God Modules Shortlist

### Top 10 Refactoring Candidates

| Rank | File | Score | Severity | Action |
|------|------|-------|----------|--------|
| 1 | [worst file] | [score] | SEVERE | `/refactor [path]` |
| 2 | [second file] | [score] | SEVERE | `/refactor [path]` |
| ... | ... | ... | ... | ... |

### Newly God-like Since Last Sweep
- [file] (was [old score], now [new score]) - grew from [reason]

### God-like + Hotspot (High Churn)
These are the most painful files (big + frequently edited):
- [file] - [commits] commits, [score] score

**Next Action**: Run `/refactor_candidates` for full index or `/refactor <file>` for immediate action.

## Trends (vs Previous Sweep)
- New debt items: +X
- Resolved since last: -X
- Net change: +/-X

## Metrics (also in frontmatter for machine parsing)
- Debt density: 2.3 per 1000 LOC
- Suppression ratio: 1.5%
- Doc coverage: 67%
- Config health: 65%
- Dependency health: 78%
```

### Step 7: Generate Paydown Plan
Write to: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-paydown.md`

Structure:
```markdown
---
date: [ISO timestamp]
type: tech-debt-paydown
source_sweep: [path to debt report]
estimated_effort: 3h
auto_fixable_count: 12
---

# Technical Debt Paydown Plan

## Quick Wins (Apply Now)
These are safe to fix automatically with `/tech_debt_sweep apply`:

### Auto-Fixable (Safe)
- [ ] Remove X console.log statements
- [ ] Delete X commented-out code blocks
- [ ] Run prettier/eslint --fix on modified files

**Estimated time**: 5-10 minutes (automated)

### NOT Auto-Fixed (Review Required)
- [ ] Dependency updates (run `npm outdated` first)
- [ ] Credential rotation (manual verification required)

## This Sprint
Items to address manually this sprint:

### Priority 1: Security/Credentials (CRITICAL)
- [ ] Move API key to env var in src/api/client.ts:45
- [ ] Rotate exposed credentials and purge from git history
- [ ] Run `npm audit fix` after review

### Priority 2: Code Quality
- [ ] Add docstrings to 5 most-used undocumented functions
- [ ] Resolve 3 @ts-ignore suppressions in src/api/

**Estimated time**: 2-4 hours

## Next Sprint
Larger items requiring planning:

### Refactoring
- [ ] Split src/utils/index.ts into focused modules
- [ ] Break auth<->user circular dependency

### Configuration
- [ ] Externalize 8 hardcoded URLs to config
- [ ] Create proper .env.example template

## Out of Scope
Explicitly NOT addressing this cycle:
- Full codebase documentation overhaul
- Major version dependency upgrades
- Architectural redesign
```

### Step 8: Present Summary
```
Tech Debt Sweep Complete!

**Report**: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-sweep.md`
**Plan**: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-paydown.md`

**Summary**:
- X total debt items found
- X quick wins available
- X critical items need attention

**Quick Wins** (safe to apply now):
1. Remove X debug statements
2. Delete X dead code blocks
3. Update X patch dependencies

Run `/tech_debt_sweep apply` to auto-fix safe items.
```

## Apply Process

When `$ARGUMENTS` equals "apply":

### Step 1: Verify Clean Working Tree
```bash
# REQUIRED: Apply mode needs clean git state for rollback
if [ -n "$(git status --porcelain)" ]; then
  echo "Error: Working tree has uncommitted changes."
  echo "Please commit or stash changes before running apply mode."
  exit 1
fi
```

### Step 2: Find Latest Sweep
- Locate most recent paydown plan in `thoughts/shared/debt/`
- Verify it was generated within last 7 days
- If no recent sweep, ask user to run sweep first

### Step 3: Apply Safe Fixes ONLY
Only apply changes that:
- Are auto-fixable by tooling (prettier, eslint --fix)
- Don't change behavior (formatting, dead code removal)
- Can be verified by running tests

**NOT applied** (even if in paydown plan):
- Dependency updates
- Refactoring
- Credential changes

### Step 4: Verify Fixes
```bash
# Run tests
npm test || yarn test || pnpm test

# If tests fail, rollback
if [ $? -ne 0 ]; then
  echo "Tests failed after applying fixes. Rolling back..."
  git checkout .
  exit 1
fi
```

### Step 5: Generate Validation Report
Write to: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-applied.md`

### Step 6: Report Results
```
Safe fixes applied!

**Validation Report**: `thoughts/shared/debt/YYYY-MM-DD-tech-debt-applied.md`

**Applied**:
- Formatted 23 files
- Fixed 15 lint errors
- Removed 8 debug statements

**NOT Applied** (review manually):
- 3 dependency updates
- 2 credential externalization items

**Verification**:
- All tests pass
- No lint errors
- Type check clean

Ready to commit these changes?
```

## Agent Chaining Pattern

For complex fixes, chain agents:
1. **debt-scanner** finds issues
2. **codebase-pattern-finder** finds similar working code
3. **code-analyzer** validates the fix approach
4. Apply fix with verification

## Error Handling
- If an agent fails, continue with others and note the failure
- If no package manager detected, skip dependency audit
- If tests fail after apply, roll back and report

## Success Criteria
- [ ] All 6 specialized agents completed their scans (including god-module-finder)
- [ ] Debt report generated with metrics
- [ ] God Modules Shortlist included with top 10 candidates
- [ ] Paydown plan created with prioritized items
- [ ] Quick wins clearly identified
- [ ] (If apply) Safe fixes applied and verified
