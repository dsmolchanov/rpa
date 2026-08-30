---
date: 2026-08-30T00:00:00Z
type: test-suite-manifest
commit: ee86cf9
---

# Test Suite Manifest

**Generated**: 2026-08-30
**Commit**: ee86cf9

## Detected Infrastructure

| Component | Value |
|-----------|-------|
| Language(s) | Python |
| Test Framework | unittest-style, script-embedded (each test file self-runnable) |
| Coverage Tool | none configured |
| Monorepo | No |

## Test Patterns

- **File Pattern**: `test_*.py`, colocated with the module under test
- **Directories**: `plugins/rpa/hooks/`, `plugins/rpa/skills/tdd/scripts/`,
  `plugins/rpa/skills/one-pager/scripts/`
- **Source-to-Test**: `<name>.py` → sibling `test_<name>.py`

## Commands

There is no single suite-level command; CI (`.github/workflows/ci.yml`,
`unit` job) runs each test file individually — the evidenced invocations:

| Test | Command |
|------|---------|
| Hook gate runner | `python3 plugins/rpa/hooks/test_run_gate.py` |
| TDD evidence kernel | `python3 plugins/rpa/skills/tdd/scripts/test_evidence.py` |
| TDD session-log validator | `python3 plugins/rpa/skills/tdd/scripts/test_validate_session_log.py` |
| One-pager | `python3 plugins/rpa/skills/one-pager/scripts/test_onepager.py` |

The docs gate (`python3 scripts/validate_docs.py --self-test` and
`--root .`) runs alongside them in the same job.

## Existing Tests

- **Total Test Files**: 4 (plus fixture trees under `tests/fixtures/` and
  skill-local `scripts/fixtures/`, which hold data, not runnable tests)

## Coverage Backend

- **Available**: No — no coverage tool or threshold is configured
  (threshold: `not_applicable — no configured threshold`)

## Next Steps

- `adopt` could add a wrapper aggregating the four script invocations,
  mirroring CI's `unit` job.
