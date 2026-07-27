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
    # Shipped installs (plugin / Quick Install) carry no dependencies:
    # the validator stays self-contained. When PyYAML (the registered
    # dependency of the repo's docs-validate CI gate) is absent, a strict
    # fallback parser accepts exactly the contract's flat mapping shape —
    # scalars plus one flow list — and REJECTS anything richer, so the
    # fallback can never be more permissive than real YAML parsing.
    yaml = None

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

HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def _anonymized(value):
    return isinstance(value, str) and value.startswith("[anonymized:")


def _parse_frontmatter_fallback(block, errors):
    """Contract-shape parser for hosts without PyYAML: flat `key: value`
    mapping, values scalars or one bracketed flow list. Anything richer is
    rejected outright — stricter than YAML, never more permissive."""
    meta = {}
    for raw in block.splitlines():
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t") or raw.lstrip().startswith("- "):
            errors.append(
                "frontmatter uses nested or multiline YAML — beyond the "
                "contract's flat mapping (install PyYAML 6.0.2 for full "
                "parsing, or flatten the frontmatter)")
            return {}
        if ":" not in raw:
            errors.append(
                f"frontmatter line is not `key: value`: `{raw.strip()[:60]}`")
            return {}
        key, _, val = raw.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [
                item.strip().strip("'\"")
                for item in val[1:-1].split(",") if item.strip()
            ]
        else:
            meta[key.strip()] = val.strip("'\"")
    return meta


def _headings_outside_fences(lines):
    """Real Markdown ATX headings only: fenced code blocks (``` / ~~~) are
    skipped, so a document QUOTING the artifact template cannot satisfy
    the structural gate."""
    headings = []
    fence = None
    for line in lines:
        stripped = line.strip()
        if fence is None and (stripped.startswith("```")
                              or stripped.startswith("~~~")):
            fence = stripped[:3]
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip()))
    return headings


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
            if yaml is not None:
                try:
                    meta = yaml.safe_load(block)
                except yaml.YAMLError as exc:
                    errors.append(f"frontmatter is not valid YAML: {exc}")
                    meta = {}
                if not isinstance(meta, dict):
                    if not errors:
                        errors.append("frontmatter must be a YAML mapping")
                    meta = {}
            else:
                meta = _parse_frontmatter_fallback(block, errors)
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
    headings = _headings_outside_fences(lines)
    title = next(((lvl, txt) for lvl, txt in headings
                  if lvl == 1 and txt.startswith("Research:")), None)
    if title is None or not title[1][len("Research:"):].strip():
        errors.append(
            "missing document title `# Research: <topic>` (a real level-1 "
            "Markdown heading with a non-empty topic)")
    required = [(2, h[3:]) for h in REQUIRED_EXACT_HEADINGS]
    pos = 0
    for req in required:
        found = None
        for idx in range(pos, len(headings)):
            if headings[idx] == req:
                found = idx
                break
        if found is None:
            if req in headings[:pos]:
                errors.append(
                    f"heading `## {req[1]}` appears out of the contract's "
                    f"section order")
            else:
                errors.append(
                    f"missing required heading `## {req[1]}` (a real "
                    f"Markdown heading outside code fences, in contract "
                    f"order)")
        else:
            pos = found + 1
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
