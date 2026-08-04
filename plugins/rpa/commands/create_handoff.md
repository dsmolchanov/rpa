---
description: Create a handoff document to transfer work context between sessions
argument-hint: "[ticket-number] [description]"
---

# Create Handoff Document Guide

This document outlines the process for creating a handoff document to transfer work between sessions.

## File Location Structure
Store handoff files at: `thoughts/shared/handoffs/ENG-XXXX/YYYY-MM-DD_HH-MM-SS_ENG-ZZZZ_description.md`

Components:
- Date: YYYY-MM-DD format
- Time: HH-MM-SS in 24-hour format
- Ticket: ENG-XXXX (use "general" if no ticket)
- Description: brief kebab-case summary

Run `scripts/spec_metadata.sh` to generate metadata automatically.

## YAML Frontmatter Template
Required fields:
- `date`: ISO format with timezone
- `researcher`: Name from thoughts status
- `git_commit`: Current commit hash
- `branch`: Current branch name
- `repository`: Repository name
- `topic`: Feature/task name with "Implementation Strategy"
- `tags`: Relevant component names
- `status`: complete
- `last_updated`: YYYY-MM-DD
- `last_updated_by`: Researcher name
- `type`: implementation_strategy

## Document Sections

**Task(s)**: Status of all work items with phase references

**Critical References**: 2-3 most important specification documents

**Recent changes**: Changes using `in line:file` syntax

**Learnings**: Important patterns, bug causes, or critical information

**Artifacts**: Exhaustive list of produced/updated files and documents

**Action Items & Next Steps**: Tasks for the next agent

**Other Notes**: Additional references and useful information

## Resume
Resume work using:
```bash
/resume_handoff path/to/handoff.md
```

## Key Principles
- Include more detail rather than less (minimum guideline only)
- Be thorough and precise with both objectives and lower-level details
- Avoid large code blocks; use file path references instead (e.g., `package/file.ext:12-24`)
