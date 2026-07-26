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

Metadata comes from `scripts/spec_metadata.sh` when available, otherwise
gathered manually (date, git commit, branch, repo name).

## Frontmatter (YAML, required)

```yaml
---
date: [Current date and time with timezone in ISO format]
researcher: [Researcher name]
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

## Body sections (in order)

1. `# Research: [Topic]` — header block repeating date, researcher,
   git commit, branch, repository.
2. `## Research Question` — the original user query.
3. `## Summary` — high-level answer describing what exists.
4. `## Detailed Findings` — per component/area; every claim carries a
   `file.ext:line` reference; description without evaluation.
5. `## Code References` — `path/to/file.py:123` list with one-line
   descriptions.
6. `## Architecture Documentation` — patterns and conventions found.
7. `## Historical Context (from thoughts/)` — insights with `thoughts/`
   paths (paths exclude `searchable/`).
8. `## Related Research` — links to other docs in
   `thoughts/shared/research/`.
9. `## Open Questions` — areas needing further investigation.

## Permalinks

When the commit is on the default branch or pushed, local references are
replaced with GitHub permalinks
(`https://github.com/{owner}/{repo}/blob/{commit}/{file}#L{line}`).

## Follow-up semantics

Follow-up research appends to the same document and updates frontmatter
`last_updated`, `last_updated_by`, and (on enhancement) an
`enhancement_note` — see `/enhance_research`.
