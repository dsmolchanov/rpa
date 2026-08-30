# Testing Patterns Reference

Shared reference for the `tdd`, `create-test-plan`, and `test-suite` workflows (the `/test_suite` command remains a deprecated 2.x alias). Extracted from `/tdd` so workflows orchestrate while this document teaches.

## Unit Test Pattern (Jest/Vitest)

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

## API Integration Test Pattern

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

## E2E Test Pattern (Playwright)

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

## Mocking External Services

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

## Language-Specific Templates

Generation policy (strategy selection, pending-test rules, snapshot sanitization) lives in the test-suite skill package: `skills/test-suite/references/modes/init.md` and the `test-generator` contract at `skills/test-suite/references/agent-contracts/test-generator.md`. Language-specific structure follows the repository's own conventions first, then the patterns in this document.
