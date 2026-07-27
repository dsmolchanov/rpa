#!/usr/bin/env python3
"""Deterministic validator for research-document artifacts.

Binds the artifact contract
(`skills/research-codebase/references/artifact-contract.md`) as an
executable gate (conventions §4): frontmatter fields and required body
headings are checked mechanically, with a nonzero exit and a per-defect
report on failure. Used by the kernel's verification profile, by the
pilot's artifact-compatibility gate, and — with the positive/negative
fixtures under `fixtures/` — proven non-no-op in this repo's CI.

Usage: validate_artifact.py <document.md> [...]
"""

import sys
from pathlib import Path

REQUIRED_FRONTMATTER = (
    "date",
    "researcher",
    "git_commit",
    "branch",
    "repository",
    "topic",
    "tags",
    "status",
    "last_updated",
    "last_updated_by",
)

REQUIRED_HEADINGS = (
    "# Research:",
    "## Research Question",
    "## Summary",
    "## Detailed Findings",
    "## Code References",
)


def validate(path):
    errors = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [f"cannot read document: {exc}"]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        errors.append("frontmatter must open with `---` on line 1")
        keys = set()
    else:
        keys = set()
        closed = False
        for line in lines[1:]:
            if line.strip() == "---":
                closed = True
                break
            if ":" in line and not line.startswith((" ", "\t", "-")):
                keys.add(line.split(":", 1)[0].strip().lower())
        if not closed:
            errors.append("frontmatter block is never closed with `---`")
    for field in REQUIRED_FRONTMATTER:
        if field not in keys:
            errors.append(f"missing frontmatter field `{field}`")
    for heading in REQUIRED_HEADINGS:
        if not any(line.strip().startswith(heading) for line in lines):
            errors.append(f"missing required heading `{heading}`")
    return errors


def main():
    if len(sys.argv) < 2:
        print("usage: validate_artifact.py <document.md> [...]",
              file=sys.stderr)
        return 2
    failed = False
    for path in sys.argv[1:]:
        errors = validate(path)
        if errors:
            failed = True
            for err in errors:
                print(f"{path}: {err}")
        else:
            print(f"{path}: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
