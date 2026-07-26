# Research document — artifact contract

Single source of truth for the `/research_codebase` output format
(conventions §9). Extracted unchanged from the frozen baseline
(`commands/research_codebase.md`, steps 5–6 at plugin SHA `a7de5f6`); the
pilot's candidate must emit documents that satisfy this same contract so
legacy `/create_plan` and `/enhance_research` keep consuming them.

## Path

`thoughts/shared/research/YYYY-MM-DD-ENG-XXXX-description.md`

- `YYYY-MM-DD` — today's date
- `ENG-XXXX` — ticket number (omit segment entirely if no ticket)
- `description` — brief kebab-case topic
- Examples: `2025-01-08-ENG-1478-parent-child-tracking.md`,
  `2025-01-08-authentication-flow.md`

Metadata comes from `~/.claude/scripts/spec_metadata.sh` — the installed
copy of this plugin's `scripts/spec_metadata.sh`, exactly as the frozen
baseline invokes it — and, if absent, is gathered manually (date, git
commit, branch, repo name).

## Frontmatter (YAML, required)

```yaml
---
date: [Current date and time with timezone in ISO format]
researcher: [Researcher name from thoughts status]
git_commit: [Current commit hash]
branch: [Current branch name]
repository: [Repository name]
topic: "[User's Question/Topic]"
tags: [research, codebase, relevant-component-names]
status: complete
last_updated: [Current date in YYYY-MM-DD format]
last_updated_by: [Researcher name]
---
```

## Body template (verbatim from the frozen baseline)

```markdown
# Research: [User's Question/Topic]

**Date**: [Current date and time with timezone from step 4]
**Researcher**: [Researcher name from thoughts status]
**Git Commit**: [Current commit hash from step 4]
**Branch**: [Current branch name from step 4]
**Repository**: [Repository name]

## Research Question
[Original user query]

## Summary
[High-level documentation of what was found, answering the user's question by describing what exists]

## Detailed Findings

### [Component/Area 1]
- Description of what exists ([file.ext:line](link))
- How it connects to other components
- Current implementation details (without evaluation)

### [Component/Area 2]
...

## Code References
- `path/to/file.py:123` - Description of what's there
- `another/file.ts:45-67` - Description of the code block

## Architecture Documentation
[Current patterns, conventions, and design implementations found in the codebase]

## Historical Context (from thoughts/)
[Relevant insights from thoughts/ directory with references]
- `thoughts/shared/something.md` - Historical decision about X
- `thoughts/local/notes.md` - Past exploration of Y
Note: Paths exclude "searchable/" even if found there

## Related Research
[Links to other research documents in thoughts/shared/research/]

## Open Questions
[Any areas that need further investigation]
```

## Permalinks

When the commit is on the default branch or pushed, local references are
replaced with GitHub permalinks
(`https://github.com/{owner}/{repo}/blob/{commit}/{file}#L{line}`).

## Follow-up semantics

Two distinct update flows, each with its own frontmatter metadata — both
preserved exactly as in the baseline:

- **Follow-up research** (`/research_codebase`, step 9 of the baseline):
  appends a `## Follow-up Research [timestamp]` section to the same
  document, updates `last_updated` and `last_updated_by`, and adds
  `last_updated_note: "Added follow-up research for [brief description]"`.
- **Enhancement** (`/enhance_research`): updates `last_updated` /
  `last_updated_by` and adds
  `enhancement_note: "Enhanced based on user feedback: [brief summary]"`.
