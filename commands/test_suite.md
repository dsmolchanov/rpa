---
description: Create, update, and maintain test suites with coverage tracking
argument-hint: "[audit|init|update|gaps|run|ci] [options]"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(npm test:*), Bash(npx jest:*), Bash(pytest:*), Bash(python -m pytest:*), Bash(go test:*), Bash(cargo test:*), Bash(make test:*), Bash(git diff:*), Bash(git log:*), Bash(git rev-parse:*), Bash(mkdir:*)
model: opus
---

# Test Suite Management

You manage test suites: creation, maintenance, coverage tracking, and CI integration.

## Usage Modes

- `/test_suite audit` - Detect test infrastructure, produce manifest
- `/test_suite init [apply]` - Scaffold tests (plan by default)
- `/test_suite update [apply]` - Sync tests with code changes
- `/test_suite gaps [--runtime] [apply]` - Find and fill coverage holes
- `/test_suite run` - Execute and report results
- `/test_suite ci [--github|--gitlab]` - Generate CI configuration

The subcommand is available as `$ARGUMENTS`.

## Safety Philosophy

All subcommands produce **plans** by default. Add `apply` to make changes.
Assertion changes always require human approval.

---

## Subcommand: audit

Detect test infrastructure and produce a Test Harness Manifest.

### Initial Response

```
Starting test infrastructure audit...

I'll analyze your project for:
1. Test framework detection (Jest, pytest, go test, etc.)
2. Test file conventions (naming, location)
3. Coverage backend availability
4. Monorepo structure (if applicable)

This will generate:
- Manifest: `thoughts/shared/test-suite/test-suite-manifest.json`
- Summary: `thoughts/shared/test-suite/test-suite-manifest.md`

Scanning now...
```

### Process

#### Step 1: Ensure Directory Exists

```bash
mkdir -p thoughts/shared/test-suite
```

#### Step 2: Get Git Info

```bash
git rev-parse --short HEAD 2>/dev/null || echo "no-git"
```

#### Step 3: Spawn Test Analyzer

Use Task tool to spawn the analyzer:

```yaml
Task - Infrastructure Analysis:
  subagent_type: test-analyzer
  Prompt: |
    Analyze the test infrastructure for this project.

    Detect:
    1. Primary language(s) and test framework(s)
    2. Test file patterns (naming conventions, directories)
    3. Coverage backend availability and configuration
    4. Monorepo structure if present
    5. Existing test count and locations

    Return a complete Test Harness Manifest in JSON format.
    Include brief explanation of detected patterns.
    Limit response to 150 lines.
```

#### Step 4: Parse and Write Manifest

After agent completes:
1. Extract JSON manifest from response
2. Write to `thoughts/shared/test-suite/test-suite-manifest.json`
3. Generate human-readable summary

#### Step 5: Write Summary

Write to `thoughts/shared/test-suite/test-suite-manifest.md`:

```markdown
---
date: [ISO timestamp]
type: test-suite-manifest
commit: [git commit]
---

# Test Suite Manifest

**Generated**: [date]
**Commit**: [commit]

## Detected Infrastructure

| Component | Value |
|-----------|-------|
| Language(s) | TypeScript |
| Test Framework | Jest |
| Coverage Tool | Istanbul |
| Monorepo | No |

## Test Patterns

- **File Pattern**: `*.test.ts`, `*.spec.ts`
- **Directories**: `__tests__/`, co-located with source
- **Naming Convention**: `{module}.test.ts`
- **Source-to-Test**: `src/foo.ts` → `src/foo.test.ts`

## Commands

| Action | Command |
|--------|---------|
| Run All Tests | `npm test` |
| Run Single Test | `npx jest {file}` |
| Run with Coverage | `npm test -- --coverage` |
| Run Related | `npx jest --findRelatedTests {file}` |

## Existing Tests

- **Total Test Files**: 42
- **Locations**: [list of directories]

## Coverage Backend

- **Available**: Yes
- **Tool**: Istanbul
- **Output**: `coverage/coverage-summary.json`

## Next Steps

1. Run `/test_suite gaps` to identify untested code
2. Run `/test_suite init` to scaffold missing tests
3. Run `/test_suite run` to execute tests
```

#### Step 6: Present Results

```
Test Infrastructure Audit Complete!

**Manifest**: `thoughts/shared/test-suite/test-suite-manifest.json`
**Summary**: `thoughts/shared/test-suite/test-suite-manifest.md`

**Detected**:
- Framework: Jest (TypeScript)
- Pattern: Co-located tests (*.test.ts)
- Coverage: Istanbul available
- Tests: 42 test files found

**Test Command**: `npm test`
**Coverage Command**: `npm test -- --coverage`

**Next Steps**:
- `/test_suite gaps` - Find untested code
- `/test_suite init` - Scaffold missing tests
- `/test_suite run` - Execute and report
```

### Idempotency

`audit` always overwrites the manifest (it's a point-in-time snapshot).

---

## Subcommand: init [apply]

Scaffold tests for uncovered code following repo conventions.

### Initial Response (Plan Mode)

```
Starting test scaffolding analysis...

I'll analyze your code to generate test scaffolds:
1. Read manifest for conventions (or run audit first)
2. Identify untested files/functions
3. Analyze dependencies for mock strategy
4. Generate test plan

This will create:
- Plan: `thoughts/shared/test-suite/YYYY-MM-DD-test-init-plan.md`

No files will be modified until you run `/test_suite init apply`.
```

### Process

#### Step 1: Check for Manifest

Read `thoughts/shared/test-suite/test-suite-manifest.json`:
- If missing: Run audit first automatically
- If stale (>7 days): Suggest re-running audit

#### Step 2: Find Untested Files

Use static analysis to find source files without tests:
- Map source files to expected test locations
- Identify files with no corresponding test file
- Prioritize by importance (exports, fan-in)

#### Step 3: Spawn Analysis Agents (Parallel)

For each untested file (or top 10 by priority):

```yaml
Task 1 - Mock Architecture:
  subagent_type: test-architect
  Prompt: |
    Analyze [file] for test mock strategy.

    Classify dependencies:
    - Pure: No external deps → test directly
    - Impure: Network/DB/FS → generate mocks
    - Async: Special handling needed

    Return: mock scaffolding strategy per function.
    Limit response to 80 lines.

Task 2 - Test Generation:
  subagent_type: test-generator
  Prompt: |
    Generate test scaffolds for [file].

    Follow conventions from manifest:
    - Pattern: [from manifest]
    - Framework: [from manifest]
    - Location: [from manifest]

    Use mock strategy from architect.
    Include placeholder assertions (TODO comments).
    Sanitize any snapshots (dates, UUIDs).

    Return: complete test file content.
    Limit response to 150 lines.
```

#### Step 4: Generate Init Plan

Write to `thoughts/shared/test-suite/YYYY-MM-DD-test-init-plan.md`:

```markdown
---
date: [ISO timestamp]
type: test-init-plan
source_manifest: thoughts/shared/test-suite/test-suite-manifest.json
files_to_create: 5
---

# Test Init Plan

## Summary

- Files to scaffold: 5
- Framework: Jest
- Pattern: Co-located (*.test.ts)

## Files to Create

### 1. `src/utils/auth.test.ts`

**Source**: `src/utils/auth.ts`
**Functions**: login, logout, validateToken
**Mock Strategy**: Mock fetch for API calls

```typescript
// Scaffold preview
import { login, logout, validateToken } from './auth';

describe('auth', () => {
  describe('login', () => {
    it('should authenticate valid credentials', async () => {
      // TODO: Implement test
    });

    it('should reject invalid credentials', async () => {
      // TODO: Implement test
    });
  });
  // ...
});
```

### 2. `src/services/user.test.ts`
[Similar structure...]

## Apply Instructions

Run `/test_suite init apply` to create these files.
```

#### Step 5 (Apply Mode): Create Test Files

If `apply` argument present:
1. Verify git is clean (or warn)
2. Create each test file
3. Run tests to verify they compile
4. Report results

```
Test Scaffolds Created!

**Files Created**:
- src/utils/auth.test.ts
- src/services/user.test.ts
- src/api/payments.test.ts

**Verification**:
- TypeScript: PASS (no compile errors)
- Tests: 5 passing (placeholder assertions)

**Next Steps**:
1. Implement actual assertions in TODO comments
2. Run `/test_suite run` to verify
```

### Idempotency

`init` errors if test file already exists. Use `--force` to overwrite.

---

## Subcommand: run

Execute tests and report results.

### Process

1. Read manifest for test command
2. Execute tests
3. Parse results
4. Report with file:line references

### Output

```
Test Execution Results

**Command**: npm test
**Duration**: 12.5s

## Summary
- Total: 142
- Passed: 140
- Failed: 2
- Skipped: 0

## Failures

### `src/utils/auth.test.ts:45` - should validate token

**Error**: Expected token to be valid
**Expected**: { valid: true }
**Actual**: { valid: false, error: 'expired' }

**Suggested Fix**: Check token expiration logic in validateToken()

### `src/api/payments.test.ts:78` - should process refund

**Error**: Timeout after 5000ms
**Suggested Fix**: Add mock for payment gateway API call

## Recommendations

1. Fix token validation logic
2. Add payment gateway mock
3. Consider adding timeout configuration
```

---

## Subcommand: gaps [--runtime] [apply]

Identify untested code using static analysis (default) or runtime coverage.

### Initial Response

```
Starting coverage gap analysis...

I'll identify untested code using:
1. Static analysis (default): No coverage tools required
2. Runtime analysis (--runtime): Uses actual coverage data

Mode: [Static/Runtime based on flags]

This will generate:
- Gap Report: `thoughts/shared/test-suite/YYYY-MM-DD-gaps-report.md`

Analyzing now...
```

### Process

#### Step 1: Check for Manifest

Read `thoughts/shared/test-suite/test-suite-manifest.json`:
- If missing: Run audit first
- Extract test patterns and conventions

#### Step 2: Spawn Impact Mapper (Static Mode)

```yaml
Task - Gap Analysis:
  subagent_type: test-impact-mapper
  Prompt: |
    Analyze the codebase for test coverage gaps using static analysis.

    Find:
    1. Source files without corresponding test files
    2. Exported functions not referenced in any test
    3. Error handling paths without test coverage
    4. High fan-in modules with insufficient tests

    Calculate priority scores using:
    - Fan-in (30%): How many files import this
    - Churn (20%): Recent git changes
    - Complexity (20%): Branch count
    - Security (20%): auth/crypto/validate in name
    - Zero test (10%): No tests at all

    Return: Prioritized gap list with scores.
    Limit response to 150 lines.
```

#### Step 3: Spawn Coverage Reporter (Runtime Mode)

If `--runtime` flag present:

```yaml
Task - Runtime Coverage:
  subagent_type: coverage-reporter
  Prompt: |
    Parse coverage data and identify gaps.

    1. Locate coverage output (from manifest)
    2. Parse coverage data (Istanbul/pytest-cov/go cover)
    3. Identify uncovered lines and functions
    4. Cross-reference with priority scoring
    5. Generate gap report

    Return: Coverage gaps with line numbers and priority.
    Limit response to 150 lines.
```

#### Step 4: Generate Gap Report

Write to `thoughts/shared/test-suite/YYYY-MM-DD-gaps-report.md`

#### Step 5 (Apply Mode): Generate Test Scaffolds

If `apply` argument present:
1. Take top 10 gaps by priority
2. Spawn test-architect + test-generator for each
3. Create test files
4. Report results

### Priority Tiers

| Score | Tier | Action |
|-------|------|--------|
| 85-100 | Critical | Test immediately |
| 70-84 | High | Test this sprint |
| 55-69 | Medium | Plan for testing |
| <55 | Low | Defer |

### Output

```
Coverage Gaps Analysis

**Mode**: Static (use --runtime for actual coverage)
**Report**: `thoughts/shared/test-suite/YYYY-MM-DD-gaps-report.md`

## Critical Priority (Score 85+)

- [ ] `src/auth/login.ts:validateToken()` (95) - auth + high fan-in + zero test
- [ ] `src/api/payments.ts:processRefund()` (90) - payment + high churn

## High Priority (Score 70-84)

- [ ] `src/services/user.ts:createUser()` (78) - high fan-in (12 imports)
- [ ] `src/utils/validation.ts` (75) - No test file exists

## Medium Priority (Score 55-69)

- [ ] `src/helpers/format.ts:formatCurrency()` (62) - moderate fan-in
- [ ] `src/helpers/date.ts` (58) - Partial coverage (4/10 functions)

## Summary

| Priority | Count | Action |
|----------|-------|--------|
| Critical | 2 | Test immediately |
| High | 4 | This sprint |
| Medium | 6 | Plan |
| Low | 8 | Defer |

## Recommendations

1. Add tests for validateToken() - security critical
2. Create test file for validation.ts
3. Expand coverage for format helpers

Run `/test_suite gaps apply` to generate test scaffolds for critical/high gaps.
```

### Idempotency

`gaps` is additive - won't duplicate existing gaps in report.

---

## Subcommand: update [apply]

Sync tests with code changes non-destructively.

### Initial Response

```
Starting test update analysis...

I'll sync tests with recent code changes:
1. Detect file renames, moves, signature changes
2. Categorize as safe (auto-fix) or needs approval
3. Generate update plan

This will generate:
- Update Plan: `thoughts/shared/test-suite/YYYY-MM-DD-test-update-plan.md`

No changes will be made until you run `/test_suite update apply`.

Analyzing changes...
```

### Safe Auto-Updates

- File renames/moves → update import paths
- Function renames → update test names
- Signature changes (params) → update test calls
- Deleted functions → mark tests for removal

### Requires Approval

- Assertion value changes
- Snapshot updates
- Logic changes in test

### Process

#### Step 1: Get Changed Files

```bash
git diff HEAD~1 --name-status
```

#### Step 2: Spawn Test Updater

```yaml
Task - Update Analysis:
  subagent_type: test-updater
  Prompt: |
    Analyze code changes and their impact on tests.

    Changed files: [list from git diff]

    For each change:
    1. Find corresponding test files
    2. Detect change type (rename, move, signature, delete)
    3. Categorize as safe-auto or needs-approval
    4. Generate specific update instructions

    Safe (auto-apply):
    - File/function renames → update imports/names
    - Parameter renames → update test calls

    Needs approval:
    - Assertion value changes
    - Expected error message changes
    - Return type changes

    Return: Categorized update plan with diffs.
    Limit response to 180 lines.
```

#### Step 3: Spawn Impact Mapper

```yaml
Task - Impact Mapping:
  subagent_type: test-impact-mapper
  Prompt: |
    Map changed files to impacted tests.

    Changed files: [list from git diff]

    Trace import chains to find:
    1. Direct tests for changed files
    2. Tests that import changed modules
    3. Integration tests affected

    Return: List of tests that should run.
    Limit response to 100 lines.
```

#### Step 4: Generate Update Plan

Write to `thoughts/shared/test-suite/YYYY-MM-DD-test-update-plan.md`:

```markdown
---
date: [ISO timestamp]
type: test-update-plan
changed_files: 5
affected_tests: 8
safe_updates: 12
approval_needed: 3
deletions: 1
---

# Test Update Plan

## Summary
- Changed Files: 5
- Affected Tests: 8
- Safe Updates: 12
- Approval Needed: 3
- Suggested Deletions: 1

## Safe Updates
[Auto-applicable changes]

## Requires Approval
[Changes needing human review]

## Suggested Deletions
[Tests for removed code]
```

#### Step 5 (Apply Mode): Apply Safe Updates

If `apply` argument present:
1. Apply only safe updates
2. Skip approval-needed items
3. Present deletions for confirmation
4. Run tests to verify

### Output

```
Test Update Analysis

**Changed Files**: 5
**Affected Tests**: 8
**Plan**: `thoughts/shared/test-suite/YYYY-MM-DD-test-update-plan.md`

## Safe Updates (12 total - Auto-Apply)

- [ ] Rename: `src/utils/auth.ts` → `src/auth/index.ts`
  - Update import in `src/auth/index.test.ts`

- [ ] Function: `getUser` → `fetchUser`
  - Update 3 describe blocks
  - Update 5 function calls

- [ ] Signature: `login(user, pass)` → `login(credentials)`
  - Update 3 test calls in `auth.test.ts`

## Requires Approval (3 total)

### 1. Assertion Value Change

**File**: `src/api/payments.test.ts:45`
**Reason**: Return value changed in source

```diff
- expect(calculateTotal([10, 20])).toBe(30);
+ expect(calculateTotal([10, 20])).toBe(33); // +10% tax
```

**Question**: Is this intentional behavior change?

### 2. Error Message Change

**File**: `src/utils/auth.test.ts:78`

```diff
- expect(() => validate(null)).toThrow('Invalid input');
+ expect(() => validate(null)).toThrow('Input required');
```

## Suggested Deletions (1 total)

- [ ] `validateOldToken()` removed from `auth.ts`
  - Test at `auth.test.ts:78-95`
  - Options: Delete / Skip / Archive

## Tests to Run After Update

```bash
npm test -- src/auth/index.test.ts src/api/payments.test.ts
```

Run `/test_suite update apply` to apply safe updates.
```

### Idempotency

Running update multiple times:
- Safe updates are idempotent (re-applying = no-op)
- Approval items re-presented until resolved
- Deletions tracked but not auto-applied

---

## Subcommand: ci [--github|--gitlab]

Generate CI/CD workflow configurations.

### Process

1. Read manifest for test commands
2. Detect CI platform (or use flag)
3. Generate workflow file
4. Include coverage threshold check

### GitHub Actions Output

`.github/workflows/test.yml`:

```yaml
name: Test Suite
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm test -- --coverage
      - name: Check coverage threshold
        run: |
          COVERAGE=$(jq '.total.lines.pct' coverage/coverage-summary.json)
          echo "Coverage: $COVERAGE%"
          if [ $(echo "$COVERAGE < 80" | bc -l) -eq 1 ]; then
            echo "Coverage $COVERAGE% is below 80% threshold"
            exit 1
          fi
```

---

## Error Handling

- If no manifest: Run audit first
- If no tests exist: Suggest init
- If tests fail: Report with suggestions
- If coverage unavailable: Fall back to static analysis

## Success Criteria

- [ ] Subcommand correctly identified from $ARGUMENTS
- [ ] Manifest read/created as needed
- [ ] Appropriate agents spawned
- [ ] Plan generated in plan mode
- [ ] Changes applied only with `apply` flag
- [ ] Results clearly reported
