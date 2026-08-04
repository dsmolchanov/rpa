# Research enhancement record — artifact contract

For substantive changes, add one section at the end of the research document.
This is a concise audit trail, not a second findings report.

## Shape

```markdown
## Enhancement Notes (YYYY-MM-DD)

**Feedback considered**:

- [Source or concise theme]

**Verified changes**:

- Corrected: [previous claim] — [verified current description and citation]
- Added: [missing area] — [finding and citation]
- Rejected: [feedback theme] — [evidence-backed reason]

**Checkout context**: [same checkout as the original artifact, or the current
commit and how later drift was distinguished]
```

Use only disposition categories that occurred. If an enhancement-notes section
already exists for another date, append a new dated section; never overwrite
prior history. Keep implementation detail in `## Detailed Findings`, code
locations in `## Code References`, and historical material in
`## Historical Context`.

The frontmatter update is defined only in the owning research artifact
contract: update `last_updated` and `last_updated_by`, and set
`enhancement_note` to a brief summary of this pass.
