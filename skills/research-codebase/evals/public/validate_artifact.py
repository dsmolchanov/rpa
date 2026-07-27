#!/usr/bin/env python3
"""Deterministic validator for research-document artifacts.

Binds the artifact contract
(`skills/research-codebase/references/artifact-contract.md`) as an
executable gate (conventions §4): the YAML frontmatter is actually
parsed (PyYAML — the registered dependency of this repo's validation
gate), required fields must carry non-empty values of the right shape,
`status` must be `complete`, and every heading of the contract's body
template must appear as an exact line. Nonzero exit and a per-defect
report on failure. Used by the kernel's verification profile, by the
pilot's artifact-compatibility gate, and — with the fixtures under
`fixtures/` — proven non-no-op in this repo's CI.

Anonymized scoring copies (`run-<id>-anon.md`) mask fingerprint values
with `[anonymized:<id>]`; masked values satisfy the non-empty checks and
skip format checks, so the gate applies to raw and anonymized documents
alike.

Usage: validate_artifact.py <document.md> [...]
"""

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("validate_artifact: PyYAML is required (registered dependency "
          "of the docs-validate gate, pinned 6.0.2)", file=sys.stderr)
    sys.exit(2)

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

# Every heading of the contract's body template, required as an EXACT
# line (a prefix like `## SummaryFake` must not pass).
REQUIRED_EXACT_HEADINGS = (
    "## Research Question",
    "## Summary",
    "## Detailed Findings",
    "## Code References",
    "## Architecture Documentation",
    "## Historical Context (from thoughts/)",
    "## Related Research",
    "## Open Questions",
)

LAST_UPDATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _anonymized(value):
    return isinstance(value, str) and value.startswith("[anonymized:")


def validate(path):
    errors = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [f"cannot read document: {exc}"]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        errors.append("frontmatter must open with `---` on line 1")
        meta = {}
    else:
        end = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end = idx
                break
        if end is None:
            errors.append("frontmatter block is never closed with `---`")
            meta = {}
        else:
            block = "\n".join(lines[1:end])
            try:
                meta = yaml.safe_load(block)
            except yaml.YAMLError as exc:
                errors.append(f"frontmatter is not valid YAML: {exc}")
                meta = {}
            if not isinstance(meta, dict):
                if not errors:
                    errors.append("frontmatter must be a YAML mapping")
                meta = {}
    for field in REQUIRED_FRONTMATTER:
        if field not in meta:
            errors.append(f"missing frontmatter field `{field}`")
            continue
        value = meta[field]
        if field == "tags":
            if (not isinstance(value, list) or not value
                    or not all(isinstance(t, str) and t.strip()
                               for t in value)):
                errors.append(
                    "`tags` must be a non-empty list of non-empty strings")
            continue
        # YAML types scalars (dates, all-digit hashes): any non-empty
        # scalar is acceptable where the contract shows a string.
        if (value is None or isinstance(value, (list, dict))
                or not str(value).strip()):
            errors.append(
                f"frontmatter field `{field}` must carry a non-empty "
                f"scalar value")
            continue
        sval = str(value).strip()
        if field == "status" and sval != "complete":
            errors.append(f"`status` must be `complete`, got `{sval}`")
        if (field == "last_updated" and not _anonymized(sval)
                and not LAST_UPDATED_RE.match(sval)):
            errors.append(
                f"`last_updated` must be YYYY-MM-DD, got `{sval}`")
    stripped = [line.strip() for line in lines]
    title = next((s for s in stripped if s.startswith("# Research:")), None)
    if title is None or not title[len("# Research:"):].strip():
        errors.append(
            "missing document title `# Research: <topic>` (topic must be "
            "non-empty)")
    for heading in REQUIRED_EXACT_HEADINGS:
        if heading not in stripped:
            errors.append(f"missing required heading `{heading}` "
                          f"(exact line)")
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
