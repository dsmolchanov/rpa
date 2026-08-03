# Plan enhancement record — artifact contract

Append one record to the end of the enhanced plan for each synthesis pass. This
is a decision trail, not a copy of the reviews.

## Shape

```markdown
## Enhancement History

### YYYY-MM-DD Enhancement

**Feedback considered**:

- [Source or concise feedback theme]

**Decisions**:

- Accepted: [theme] — [evidence-backed reason]
- Adapted: [theme] — [what changed and why]
- Rejected: [theme] — [evidence-backed reason]

**Plan changes**:

- [Section/phase changed and resulting improvement]
```

If `## Enhancement History` already exists, append only the dated subsection;
do not create a second top-level heading. Use only disposition categories that
occurred. Multiple suggestions with the same substance may share one theme,
but every material feedback item must map to a recorded theme.

Keep the record concise:

- Reference feedback documents by path or stable link when available.
- Summarize conversational feedback; do not reproduce it verbatim.
- Give reasons that point to repository evidence, the plan's stated objective,
  or an explicit user decision.
- Put implementation detail in the affected plan sections, not in the history.
- Preserve prior history unchanged except to repair a demonstrable factual or
  structural error that the user asked to correct.
