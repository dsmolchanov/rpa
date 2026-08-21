# TDD session log — artifact contract

## Path

`thoughts/shared/tests/YYYY-MM-DD-TDD-SESSION-description.md`

Use the current local date and a short kebab-case description matching the test
plan. Resume the same log for continuation of the same cycle; do not create one
log per command retry. The log's receipt export is committed next to it as
`thoughts/shared/tests/receipts/<run-id>.json`; `scripts/validate_session_log.py`
accepts no other layout.

## Required body

```markdown
# TDD Session: [Feature Name]

**Date**: [ISO date/time with timezone]
**Test Plan**: `[repo-relative path — binding: the export's plan_path and plan sha must match]`
**Requested Phase**: `[red | green | refactor | full]`
**Repository State**: `[branch and commit at start]`
**Evidence schema**: `tdd/1`
**Evidence run**: `[run id from evidence.py begin]`
**Evidence export**: `receipts/<run-id>.json`

## Baseline

- **Pre-existing worktree changes**: [paths, or None]
- **Relevant implementation state**: [existing/partial/absent with evidence]
- **Test configuration**: [repository files that define the test commands, e.g. `pyproject.toml`, `package.json` scripts, `Makefile` — paths only, no command strings]
- **Baseline runs**: `receipt <hex12>`: [salient result] (or Not run — reason)
- **Pre-existing relevant failures**: [evidence, or None observed]

## Case Dispositions

| Case ID | Layer | Disposition | Evidence |
|---|---|---|---|
| U-01 | unit | valid Red / Green / refactored-green / already covered / blocked / not_applicable | receipt <hex12> — salient assertion; "stand-in" when the plan declared a stand-in claim; or the reason for already covered / blocked / not_applicable |

## Red Phase

- **Files changed**: [paths]
- **Receipts**:
  - `receipt <hex12>`: [expected failure signal]
- **Deviations**: [plan drift/duplicate/blocked case, or None]

## Green Phase

- **Files changed**: [paths]
- **Receipts**:
  - `receipt <hex12>`: [test summary]
- **Deviations**: [or Not run — reason]

## Refactor Phase

- **Refactorings applied**: [behavior-preserving changes, or Not applicable — reason]
- **Receipts**:
  - `receipt <hex12>`: [test summary] (or Not run — reason / Not applicable — reason)

## Final Verification

- **Focused suite**: `receipt <hex12>`: [summary] (or Not run — reason)
- **Relevant surrounding suite**: `receipt <hex12>`: [summary] (or Not applicable — reason)
- **Coverage policy**: [measured result and configured threshold, or Not applicable — reason]
- **Manual verification**: [outcome, pending authority, or Not applicable — reason]

## Summary

- **Achieved phase**: [Red / Green / Refactored Green / Blocked]
- **Cycle state**: `[continuing | complete | blocked]`
- **Source files changed**: [paths]
- **Test files changed**: [paths]
- **Remaining blockers or follow-ups**: [items, or None]
```

## Evidence rules

- Every executed verification is a receipt from `scripts/evidence.py`, run
  with the phase and case it belongs to; the log cites the receipt and the
  exported receipt file. Citations are **receipt-only**: `` `receipt <hex12>`:
  <salient result> `` — the whole entry; the summary carries no backticked
  commands, no `→` exit arrows, no ` · ` separators — because the argv, exit
  status, outputs, and timestamps are persisted by the kernel in the export
  and are never transcribed into the log. The alternative is likewise an
  entire entry — `Not run — <reason>` / `Not applicable — <reason>` with no
  receipt tokens, backticks or arrows after the reason. `**Baseline runs**`
  is mandatory and has the same shape; baseline receipts are cited there. **Every** attempt in the export is cited — a receipt that is `STALE`,
  `SURPRISE`, `TIMEOUT` or `INTERRUPTED` is evidence of a corrected belief,
  not something to omit.
- Exactly one Case Dispositions row per case id in the test plan's §3 tables;
  an Evidence cell is `receipt <hex12> — <salient assertion>` (the word
  `stand-in` may appear) or, for `already covered` / `blocked` /
  `not_applicable`, a plain reason — never a transcribed command or exit.
  Rows have exactly four cells. Every phase section carries the
  `**Receipts**:` field; a skipped phase states `Not run — <reason>` as that
  field's **only** bullet — a phase that cites receipts may not also carry a
  not-run bullet. Field labels are matched **exactly** (`- **Label**:`, colon
  immediately after the emphasis) and each mandatory field appears exactly
  once: `**Test configuration**:` (paths only — no commands, exits, or
  receipts), `**Baseline runs**:`, `**Receipts**:` per phase, `**Focused
  suite**:` and `**Relevant surrounding suite**:`.
  `valid Red` cites a `red` receipt of that case with `outcome PASS` and a
  `test … fail-with` claim (or, marked `stand-in`, the pair `exit != 0` +
  `contains`); `Green` cites a `green` receipt of that case whose `--requires`
  names the earlier `PASS` Red; `refactored-green` cites a `refactor` receipt
  chaining to the `PASS` Green. `already covered`, `blocked`, and
  `not_applicable` carry a reason instead of a receipt.
- Do not claim every test failed in Red when only new target assertions needed
  to fail. Record each planned case's actual disposition.
- Do not estimate duration, LOC, test ratios, coverage, or flake rate. Include
  them only when measured by a named command or timestamp source.
- Preserve prior evidence when resuming. Append new attempts or update a case's
  disposition with both the prior and current evidence; do not erase a failed
  transition.
- A skipped phase is explicit (`Not run — reason`), not silently omitted; a
  phase that does not apply is `Not applicable — reason`.
- One evidence run per test plan across sessions: a continuation session runs
  `evidence.py begin --resume <run id from this header>`. Checkpoint at each
  phase boundary (re-checkpoint a phase after re-running it); seal with
  `checkpoint final --achieved <phase>` when the cycle ends (Refactored Green,
  Green with Refactor `Not applicable — reason`, or Blocked) and set
  `**Cycle state**` to `complete` or `blocked`; otherwise `continuing`.
  `evidence.py export` before finishing **every** session; the export is
  committed with the log and never edited by hand.
- The claim grammar, receipt format, and export schema are defined once in
  [`evidence-contract.md`](evidence-contract.md); the validator is
  `python3 <skill-dir>/scripts/validate_session_log.py <log>`.
