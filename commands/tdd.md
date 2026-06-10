---
description: Execute full TDD cycle - implement tests from plan, verify Red/Green/Refactor phases with 80%+ coverage
argument-hint: "[test_plan_path] [phase: red|green|refactor|full]"
allowed-tools: Read, Glob, Grep, LS, Task, Edit, Write, TodoWrite, Bash(npm test:*), Bash(npx jest:*), Bash(pytest:*), Bash(python -m pytest:*), Bash(go test:*), Bash(cargo test:*), Bash(make test:*), Bash(npm run test:*), Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(git add:*), Bash(mkdir:*)
model: opus
---

# `/tdd` - Test-Driven Development Cycle Skill

You execute the **Red → Green → Refactor** TDD cycle. You take a test plan (from `/create_test_plan`) and guide the developer through disciplined test-first implementation.

## When to Activate

- Writing new features or functionality
- Fixing bugs or issues
- Refactoring existing code
- Adding API endpoints
- Creating new components

## Philosophy

**TDD is a discipline, not a suggestion.** This skill enforces:

1. **Red Phase**: Tests exist and FAIL (proving they test something real)
2. **Green Phase**: Minimal implementation to make tests pass (no gold-plating)
3. **Refactor Phase**: Clean up with confidence (tests are your safety net)

You are the TDD coach. You do not let developers skip steps or write implementation before tests fail.

---

## Command Contract

### Invocation

```
/tdd <test_plan_path> [phase]
```

### Inputs

1. **Test plan path** (required): Path to test plan from `/create_test_plan`
   - Example: `thoughts/shared/tests/2025-01-21-TEST-auth-refactor.md`

2. **Phase** (optional, default: `full`):
   - `red` - Implement tests only, verify they fail
   - `green` - Implement minimal code to pass tests
   - `refactor` - Clean up implementation
   - `full` - Complete cycle (default)

### Outputs

- Test files created/updated
- Implementation files created/updated (green phase)
- TDD session log: `thoughts/shared/tests/YYYY-MM-DD-TDD-SESSION-<description>.md`

---

## Initial Response Behavior

### If test plan path provided:

Read it **IMMEDIATELY** and **FULLY**, then:

```
TDD Session Starting

Reading test plan: [path]
Phase: [red|green|refactor|full]

Plan Summary:
- Feature: [extracted from plan]
- Unit Tests: [count] cases
- Integration Tests: [count] cases
- E2E Tests: [count] cases

Current State Check:
- Existing test files: [list or "none"]
- Implementation exists: [yes/no]

Ready to begin [Phase] phase. Proceed?
```

### If no parameters provided:

```
I'll help you execute a TDD cycle.

Please provide:
1. Path to a test plan (from /create_test_plan)
2. Optional phase: red, green, refactor, or full (default)

Example:
`/tdd thoughts/shared/tests/2025-01-21-TEST-auth-refactor.md`
`/tdd thoughts/shared/tests/2025-01-21-TEST-auth-refactor.md red`

Tip: Run `/create_test_plan` first if you don't have a test plan yet.
```

---

## Phase 1: RED (Write Failing Tests)

**Goal**: Create tests that FAIL. A test that passes before implementation is suspicious.

### Process

#### Step 1.1: Parse Test Plan

Extract from the test plan:
- Test file locations
- Test case IDs and descriptions
- Input/output specifications
- Mock requirements
- Fixtures needed

#### Step 1.2: Check Prerequisites

```yaml
Task - Verify Test Infrastructure:
  subagent_type: test-analyzer
  Prompt: |
    Verify test infrastructure is ready:
    1. Test framework installed and configured
    2. Required mocking libraries available
    3. Test directories exist
    4. Any fixtures/factories referenced in plan exist

    Report any blockers.
    Limit response to 50 lines.
```

#### Step 1.3: Create Test Files

For each test file in the plan:

1. **Create directory structure** if needed:
   ```bash
   mkdir -p [test_directory]
   ```

2. **Generate test file** with:
   - All test cases from plan
   - Proper imports (including mocks)
   - Setup/teardown as specified
   - Clear TODO markers for any ambiguous assertions

3. **Include mandatory elements**:
   - Test IDs as comments (e.g., `// U-01`, `// I-03`)
   - Descriptive test names matching plan
   - Exact assertions from plan (or best approximation)

#### Step 1.4: Verify RED State

**CRITICAL**: Run tests and confirm they FAIL.

```bash
[test_command] [test_file]
```

**Expected outcomes**:
- Tests should **FAIL** or **ERROR** (not pass!)
- If tests pass → STOP. Either:
  - Implementation already exists (skip to refactor?)
  - Tests are not testing anything real (fix tests)
  - Wrong test file (verify location)

**Report format**:

```
RED Phase Complete

Tests Created:
- [x] src/auth/token.test.ts (5 tests)
- [x] src/auth/session.test.ts (3 tests)
- [x] tests/integration/auth.spec.ts (2 tests)

Verification:
$ npm test src/auth/
FAIL src/auth/token.test.ts
  ✕ U-01: should parse valid JWT (2ms)
  ✕ U-02: should reject expired token (1ms)
  ✕ U-03: should throw on malformed token (1ms)
  ...

Total: 10 tests, 0 passed, 10 failed ✓

RED state confirmed. Tests are failing as expected.

Ready for GREEN phase? This will implement the minimal code to make tests pass.
```

**If tests pass unexpectedly**:

```
⚠️  WARNING: Tests are passing but implementation doesn't exist!

This usually means:
1. Tests are not actually testing anything (empty assertions)
2. Implementation already exists elsewhere
3. Mocks are returning expected values by default

Action needed:
- Review test assertions
- Check for existing implementation
- Verify mock setup

Do you want me to analyze the passing tests?
```

---

## Phase 2: GREEN (Minimal Implementation)

**Goal**: Write the **minimum code** to make tests pass. No extras. No optimization. No "while I'm here" additions.

### Process

#### Step 2.1: Analyze What's Needed

For each failing test:
1. What function/method is being called?
2. What is the expected return value?
3. What side effects are expected?

```yaml
Task - Implementation Analysis:
  subagent_type: codebase-analyzer
  Prompt: |
    Analyze the failing tests to determine minimal implementation:

    Test file: [path]
    Failing tests: [list]

    For each test:
    1. What function signature is needed?
    2. What is the simplest code that returns expected value?
    3. What dependencies are required?

    Return implementation strategy.
    Limit response to 100 lines.
```

#### Step 2.2: Implement Minimally

**Rules**:
- Implement ONLY what tests require
- Hardcode if a single test expects a single value
- Add conditionals only when multiple tests require different behaviors
- Do NOT add error handling unless a test expects it
- Do NOT add logging, comments, or documentation
- Do NOT refactor existing code

**Implementation order**:
1. Unit tests first (isolated, fast feedback)
2. Integration tests second
3. E2E tests last

#### Step 2.3: Verify GREEN State

Run tests after each implementation chunk:

```bash
[test_command] [test_file]
```

**Report format**:

```
GREEN Phase Progress

Implementing: src/auth/token.ts

Test Results:
$ npm test src/auth/token.test.ts
PASS src/auth/token.test.ts
  ✓ U-01: should parse valid JWT (3ms)
  ✓ U-02: should reject expired token (2ms)
  ✓ U-03: should throw on malformed token (1ms)

3/3 tests passing ✓

Moving to next file...
```

**When all tests pass**:

```
GREEN Phase Complete

Implementation Created:
- [x] src/auth/token.ts (parseToken, validateExpiry)
- [x] src/auth/session.ts (createSession, destroySession)

All Tests Passing:
$ npm test
PASS src/auth/token.test.ts (5 tests)
PASS src/auth/session.test.ts (3 tests)
PASS tests/integration/auth.spec.ts (2 tests)

Total: 10 tests, 10 passed, 0 failed ✓

GREEN state achieved. All tests pass.

Ready for REFACTOR phase? This will clean up the implementation while keeping tests green.
```

---

## Phase 3: REFACTOR (Clean Up)

**Goal**: Improve code quality WITHOUT changing behavior. Tests must stay green throughout.

### Process

#### Step 3.1: Identify Refactoring Opportunities

```yaml
Task - Code Quality Analysis:
  subagent_type: code-analyzer
  Prompt: |
    Analyze implementation for refactoring opportunities:

    Files: [list of implemented files]

    Look for:
    1. Code duplication
    2. Long functions (>20 lines)
    3. Deep nesting (>3 levels)
    4. Poor naming
    5. Missing error handling (if appropriate)
    6. Magic numbers/strings
    7. Opportunities for extraction

    Prioritize by impact. Ignore stylistic preferences.
    Limit response to 80 lines.
```

#### Step 3.2: Propose Refactorings

Present refactoring opportunities to user:

```
REFACTOR Phase - Opportunities Found

1. **Extract helper function** (High Impact)
   - Location: src/auth/token.ts:45-67
   - Issue: JWT parsing logic duplicated
   - Proposal: Extract `decodePayload()` function

2. **Improve error messages** (Medium Impact)
   - Location: src/auth/token.ts:23
   - Issue: Generic "Invalid token" error
   - Proposal: Specific error types (ExpiredTokenError, MalformedTokenError)

3. **Add type safety** (Medium Impact)
   - Location: src/auth/session.ts
   - Issue: `any` type used for session data
   - Proposal: Define SessionData interface

Which refactorings should I apply? (all, 1,2, none)
```

#### Step 3.3: Apply Refactorings (One at a Time)

**CRITICAL**: After EACH refactoring, run tests.

```
Applying Refactoring #1: Extract decodePayload()

Changes:
- src/auth/token.ts: Extracted function, replaced 2 call sites

Verifying tests still pass...
$ npm test src/auth/
PASS src/auth/token.test.ts (5 tests)
PASS src/auth/session.test.ts (3 tests)

✓ Tests still green. Refactoring successful.

Proceeding to Refactoring #2...
```

**If tests fail after refactoring**:

```
⚠️  REFACTORING BROKE TESTS

$ npm test src/auth/
FAIL src/auth/token.test.ts
  ✕ U-02: should reject expired token

Reverting refactoring...
[Undo changes]

Tests restored to green state.

Options:
1. Skip this refactoring
2. Attempt different approach
3. Investigate test failure

What would you like to do?
```

---

## Session Log

Throughout the TDD cycle, maintain a session log:

**Location**: `thoughts/shared/tests/YYYY-MM-DD-TDD-SESSION-<description>.md`

```markdown
# TDD Session: [Feature Name]

**Date**: YYYY-MM-DD
**Test Plan**: `[path to test plan]`
**Duration**: [calculated at end]

## RED Phase
- Started: [timestamp]
- Tests created: [count]
- All tests failing: ✓

### Test Files Created
- `src/auth/token.test.ts` - 5 tests
- `src/auth/session.test.ts` - 3 tests

## GREEN Phase
- Started: [timestamp]
- Implementation files: [count]
- All tests passing: ✓

### Implementation Files
- `src/auth/token.ts` - parseToken(), validateExpiry()
- `src/auth/session.ts` - createSession(), destroySession()

## REFACTOR Phase
- Started: [timestamp]
- Refactorings applied: [count]
- Tests still green: ✓

### Refactorings Applied
1. Extracted decodePayload() helper
2. Added specific error types
3. Defined SessionData interface

## Summary
- Total tests: 10
- Implementation LOC: ~150
- Test LOC: ~200
- Test:Code ratio: 1.3:1
- Refactorings: 3

## Notes
[Any observations, decisions, or issues encountered]
```

---

## Important Guidelines (Hard Rules)

### RED Phase Rules
1. **Tests MUST fail** before proceeding to GREEN
2. **No implementation code** during RED phase
3. **Assertions must be real** - test actual behavior, not mocks
4. **One logical assertion per test** (multiple `expect()` ok if testing same thing)

### GREEN Phase Rules
1. **Minimum viable code** - if tests don't require it, don't write it
2. **No premature optimization** - make it work first
3. **No scope creep** - stick to what tests specify
4. **Run tests frequently** - after every few lines of implementation

### REFACTOR Phase Rules
1. **Tests must stay green** - run after every change
2. **Behavior must not change** - only structure/clarity
3. **Revert immediately** if tests fail
4. **Small steps** - one refactoring at a time

### General Rules
1. **Never skip phases** - even if "obvious"
2. **Trust the tests** - if tests pass, implementation is correct (for now)
3. **Test plan is the spec** - don't implement features not in the plan
4. **Ask before deviating** - if something doesn't match plan, clarify first

---

## Error Recovery

### Tests won't run
```
Check:
1. Test framework installed? (npm install)
2. Config file present? (jest.config.js, etc.)
3. Correct test command? (check package.json scripts)
4. Syntax errors in test file?
```

### Tests pass immediately (RED phase)
```
Investigate:
1. Is implementation already present?
2. Are assertions empty/trivial?
3. Are mocks returning expected values?
4. Is test file being run?
```

### Can't make tests pass (GREEN phase)
```
Options:
1. Check test expectations are realistic
2. Verify mock setup is correct
3. Review test plan for ambiguity
4. Ask user for clarification
```

### Refactoring keeps breaking tests
```
Options:
1. Smaller refactoring steps
2. Tests may be too brittle (testing implementation not behavior)
3. Skip problematic refactoring
4. Review test design
```

---

## Example Interaction

```
User: /tdd thoughts/shared/tests/2025-01-21-TEST-auth-refactor.md

A:
TDD Session Starting

Reading test plan: thoughts/shared/tests/2025-01-21-TEST-auth-refactor.md

Plan Summary:
- Feature: Auth Session Refactor
- Unit Tests: 8 cases (token parsing, session management)
- Integration Tests: 2 cases (auth middleware)
- E2E Tests: 1 case (login flow)

Current State Check:
- Existing test files: none in target locations
- Implementation exists: partial (old session.ts)

Ready to begin RED phase. This will:
1. Create test files from the plan
2. Run tests to verify they fail
3. Report RED state

Proceed? (y/n)

User: y

A:
RED Phase Starting...

Creating test files:
[x] src/auth/__tests__/token.test.ts
[x] src/auth/__tests__/session.test.ts
[x] tests/integration/auth.spec.ts

Running tests...
$ npm test

FAIL src/auth/__tests__/token.test.ts
  ✕ U-01: should parse valid JWT
  ✕ U-02: should reject expired token
  ...

Total: 11 tests, 0 passed, 11 failed ✓

RED state confirmed. Ready for GREEN phase?
```

---

## Testing Patterns Reference

### Unit Test Pattern (Jest/Vitest)

```typescript
import { render, screen, fireEvent } from '@testing-library/react'
import { validateToken, parseJWT } from './token'

describe('Token Validation', () => {
  it('returns true for valid token', () => {
    const token = createValidToken()
    expect(validateToken(token)).toBe(true)
  })

  it('returns false for expired token', () => {
    const token = createExpiredToken()
    expect(validateToken(token)).toBe(false)
  })

  it('throws on malformed token', () => {
    expect(() => parseJWT('not-a-token')).toThrow('Malformed token')
  })
})
```

### API Integration Test Pattern

```typescript
import { NextRequest } from 'next/server'
import { GET, POST } from './route'

describe('GET /api/resource', () => {
  it('returns resources successfully', async () => {
    const request = new NextRequest('http://localhost/api/resource')
    const response = await GET(request)
    const data = await response.json()

    expect(response.status).toBe(200)
    expect(data.success).toBe(true)
    expect(Array.isArray(data.data)).toBe(true)
  })

  it('validates query parameters', async () => {
    const request = new NextRequest('http://localhost/api/resource?limit=invalid')
    const response = await GET(request)

    expect(response.status).toBe(400)
  })

  it('handles database errors gracefully', async () => {
    // Mock database failure
    mockDb.mockRejectedValueOnce(new Error('Connection lost'))

    const request = new NextRequest('http://localhost/api/resource')
    const response = await GET(request)

    expect(response.status).toBe(500)
    expect(await response.json()).toMatchObject({
      success: false,
      error: expect.any(String)
    })
  })
})
```

### E2E Test Pattern (Playwright)

```typescript
import { test, expect } from '@playwright/test'

test('user can complete full workflow', async ({ page }) => {
  // Navigate
  await page.goto('/')
  await page.click('a[href="/feature"]')

  // Verify page loaded
  await expect(page.locator('h1')).toContainText('Feature')

  // Interact
  await page.fill('input[name="query"]', 'search term')
  await page.click('button[type="submit"]')

  // Wait for results (no arbitrary sleeps!)
  await expect(page.locator('[data-testid="results"]')).toBeVisible()

  // Verify outcome
  const results = page.locator('[data-testid="result-item"]')
  await expect(results).toHaveCount(5, { timeout: 5000 })
})
```

### Mocking External Services

```typescript
// Mock at boundary, not deep in implementation
jest.mock('@/lib/external-api', () => ({
  fetchData: jest.fn(() => Promise.resolve({ items: [] })),
  checkHealth: jest.fn(() => Promise.resolve({ healthy: true }))
}))

// Reset between tests
beforeEach(() => {
  jest.clearAllMocks()
})
```

---

## Common Testing Mistakes to Avoid

### Testing Implementation Details
```typescript
// WRONG: Testing internal state
expect(component.state.isLoading).toBe(false)

// CORRECT: Test user-visible behavior
expect(screen.getByText('Data loaded')).toBeInTheDocument()
```

### Brittle Selectors
```typescript
// WRONG: Breaks with any CSS change
await page.click('.css-1a2b3c')

// CORRECT: Semantic selectors
await page.click('button:has-text("Submit")')
await page.click('[data-testid="submit-btn"]')
```

### Test Interdependence
```typescript
// WRONG: Tests depend on each other
test('creates user', () => { /* creates testUser */ })
test('updates user', () => { /* assumes testUser exists */ })

// CORRECT: Each test is independent
test('creates user', () => {
  const user = createTestUser()
  // ...
})
test('updates user', () => {
  const user = createTestUser() // Own setup
  // ...
})
```

### Arbitrary Waits
```typescript
// WRONG: Flaky timing
await page.waitForTimeout(2000)

// CORRECT: Wait for condition
await expect(page.locator('[data-testid="loaded"]')).toBeVisible()
```

---

## Coverage Requirements

### Minimum Thresholds

| Metric | Threshold |
|--------|-----------|
| Lines | 80% |
| Functions | 80% |
| Branches | 80% |
| Statements | 80% |

### Verify Coverage

```bash
# Run with coverage
npm test -- --coverage

# Check thresholds met
npm run test:coverage
```

### Coverage Config Example

```json
{
  "jest": {
    "coverageThreshold": {
      "global": {
        "branches": 80,
        "functions": 80,
        "lines": 80,
        "statements": 80
      }
    }
  }
}
```

---

## Test Organization

```
src/
├── components/
│   └── Button/
│       ├── Button.tsx
│       └── Button.test.tsx      # Co-located unit tests
├── app/
│   └── api/
│       └── users/
│           ├── route.ts
│           └── route.test.ts    # Integration tests
├── lib/
│   └── utils/
│       ├── validation.ts
│       └── validation.test.ts
└── e2e/                         # E2E tests separate
    ├── auth.spec.ts
    ├── checkout.spec.ts
    └── fixtures/
        └── test-data.json
```

---

## Best Practices Checklist

1. **Tests MUST fail first** (Red before Green)
2. **One logical assertion per test** (clear failure messages)
3. **Descriptive test names** (document behavior)
4. **Arrange-Act-Assert structure** (readable tests)
5. **Mock external dependencies** (fast, deterministic)
6. **Test edge cases** (null, empty, boundary)
7. **Test error paths** (not just happy paths)
8. **Keep tests fast** (unit < 50ms each)
9. **Clean up after tests** (no state leakage)
10. **Review coverage gaps** (identify missing tests)

---

## Success Criteria

- [ ] Test plan read and parsed completely
- [ ] RED: All specified tests created and failing
- [ ] GREEN: Minimal implementation makes all tests pass
- [ ] REFACTOR: Code improved without breaking tests
- [ ] Coverage: 80%+ achieved on new code
- [ ] Session log written with full record
- [ ] No tests skipped or modified to pass artificially
- [ ] All edge cases and error paths covered
