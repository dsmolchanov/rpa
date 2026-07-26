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
4. `## Detailed Findings` — one subsection per component/area, each
   documenting (as in the frozen template): a description of what exists
   with its `file.ext:line` reference; **how it connects to other
   components**; and **current implementation details** — all without
   evaluation.
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

Two distinct update flows, each with its own frontmatter metadata — both
preserved exactly as in the baseline:

- **Follow-up research** (`/research_codebase`, step 9 of the baseline):
  appends a `## Follow-up Research [timestamp]` section to the same
  document, updates `last_updated` and `last_updated_by`, and adds
  `last_updated_note: "Added follow-up research for [brief description]"`.
- **Enhancement** (`/enhance_research`): updates `last_updated` /
  `last_updated_by` and records an `enhancement_note` describing the
  synthesis applied.
