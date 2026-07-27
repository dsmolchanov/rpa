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

Raw artifacts are validated STRICTLY by default: format and run-binding
checks apply to every value, and an `[anonymized:...]` marker in a raw
document is itself a violation (a raw artifact carrying markers would
dodge the pinned-checkout binding). Anonymized scoring copies
(`run-<id>-anon.md`) are validated with the explicit
`--allow-anonymized` mode, which exempts masked values from format and
binding checks only. The runtime filename contract
(`YYYY-MM-DD[-ENG-XXXX]-description.md`) is enforced when the caller
opts in (`--enforce-filename`; the eval harness always does) — the
standalone fixtures under `fixtures/` are deliberately outside that
mode.

Usage: validate_artifact.py [--allow-anonymized] [--enforce-filename]
       [--expect-commit SHA] [--expect-repo NAME] <document.md> [...]
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

# Sections that must carry non-whitespace content, not just a heading.
CONTENT_REQUIRED_SECTIONS = ("Research Question", "Summary",
                             "Detailed Findings")

HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")
# The contract requires "date and time with timezone in ISO format":
# the timezone part is MANDATORY, an unzoned timestamp is ambiguous.
DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
ARTIFACT_BASENAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-(ENG-\d+-)?[a-z0-9][a-z0-9-]*\.md$")


def _canonical_repo(name):
    return str(name).strip().rstrip("/").rsplit("/", 1)[-1].lower()


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
    for line_idx, line in enumerate(lines):
        open_match = FENCE_OPEN_RE.match(line)
        if fence is None and open_match:
            # The FULL delimiter is tracked: only a closing fence of the
            # same character and at least the opener's length ends the
            # block, so a 4+-char fence quoting inner ``` lines cannot be
            # closed early and leak quoted headings into the structure.
            fence = open_match.group(1)
            continue
        if fence is not None:
            close_match = FENCE_CLOSE_RE.match(line)
            if (close_match and close_match.group(1)[0] == fence[0]
                    and len(close_match.group(1)) >= len(fence)):
                fence = None
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip(),
                             line_idx))
    return headings


def validate(path, expected_git_commit=None, expected_repository=None,
             enforce_filename=False, allow_anonymized=False):
    errors = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [f"cannot read document: {exc}"]
    if enforce_filename and not ARTIFACT_BASENAME_RE.match(Path(path).name):
        errors.append(
            f"artifact basename `{Path(path).name}` violates the contract "
            f"pattern `YYYY-MM-DD[-ENG-XXXX]-description.md`")
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
        if not allow_anonymized and _anonymized(sval):
            # Raw artifacts record REAL values: a pre-anonymized field
            # would dodge format and run-binding checks entirely.
            errors.append(
                f"frontmatter field `{field}` carries an anonymization "
                f"marker in a raw artifact — raw documents must record "
                f"real values")
            continue
        if field == "status" and sval != "complete":
            errors.append(f"`status` must be `complete`, got `{sval}`")
        exempt = allow_anonymized and _anonymized(sval)
        if (field == "last_updated" and not exempt
                and not LAST_UPDATED_RE.match(sval)):
            errors.append(
                f"`last_updated` must be YYYY-MM-DD, got `{sval}`")
        if field == "date" and not exempt \
                and not DATE_RE.match(sval):
            errors.append(
                f"`date` must be an ISO date-time (with timezone), "
                f"got `{sval}`")
        if field == "git_commit" and not exempt:
            if not GIT_COMMIT_RE.match(sval):
                errors.append(
                    f"`git_commit` must be a 7-40 char hex sha, "
                    f"got `{sval}`")
            elif expected_git_commit is not None and not (
                    sval == expected_git_commit
                    or (len(sval) >= 7
                        and expected_git_commit.startswith(sval))
                    or (len(expected_git_commit) >= 7
                        and sval.startswith(expected_git_commit))):
                errors.append(
                    f"`git_commit` `{sval}` does not match the run's "
                    f"pinned target-sha `{expected_git_commit}`")
        if (field == "repository" and not exempt
                and expected_repository is not None
                and _canonical_repo(sval)
                != _canonical_repo(expected_repository)):
            errors.append(
                f"`repository` `{sval}` does not match the run's "
                f"target-repo `{expected_repository}`")
    headings = _headings_outside_fences(lines)
    title = next((h for h in headings
                  if h[0] == 1 and h[1].startswith("Research:")), None)
    if title is None or not title[1][len("Research:"):].strip():
        errors.append(
            "missing document title `# Research: <topic>` (a real level-1 "
            "Markdown heading with a non-empty topic)")
    required = [(2, h[3:]) for h in REQUIRED_EXACT_HEADINGS]
    keys = [(lvl, txt) for lvl, txt, _ in headings]
    matched = {}
    pos = 0
    for req in required:
        found = None
        for idx in range(pos, len(headings)):
            if keys[idx] == req:
                found = idx
                break
        if found is None:
            if req in keys[:pos]:
                errors.append(
                    f"heading `## {req[1]}` appears out of the contract's "
                    f"section order")
            else:
                errors.append(
                    f"missing required heading `## {req[1]}` (a real "
                    f"Markdown heading outside code fences, in contract "
                    f"order)")
        else:
            matched[req[1]] = found
            pos = found + 1
    # Headings alone are not a document: the load-bearing sections must
    # carry non-whitespace content (subsections count as content for
    # Detailed Findings). The tail sections may legitimately be a bare
    # "None" note, which is still content.
    for section in CONTENT_REQUIRED_SECTIONS:
        if section not in matched:
            continue
        h_idx = matched[section]
        start_line = headings[h_idx][2] + 1
        end_line = len(lines)
        for later in headings[h_idx + 1:]:
            if later[0] <= 2:
                end_line = later[2]
                break
        body_lines = lines[start_line:end_line]
        if not any(l.strip() for l in body_lines):
            errors.append(
                f"section `## {section}` is empty — headings alone do not "
                f"answer the research task")
    return errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="+")
    parser.add_argument("--expect-commit",
                        help="run-bound target sha the artifact's "
                             "git_commit must match")
    parser.add_argument("--expect-repo",
                        help="run-bound target repo the artifact's "
                             "repository must match (canonical name)")
    parser.add_argument("--enforce-filename", action="store_true",
                        help="require the contract basename pattern "
                             "(the eval harness always does)")
    parser.add_argument("--allow-anonymized", action="store_true",
                        help="anonymized-copy mode: exempt masked values "
                             "from format/binding checks (never used on "
                             "raw artifacts)")
    args = parser.parse_args()
    failed = False
    for path in args.documents:
        errors = validate(path, expected_git_commit=args.expect_commit,
                          expected_repository=args.expect_repo,
                          enforce_filename=args.enforce_filename,
                          allow_anonymized=args.allow_anonymized)
        if errors:
            failed = True
            for err in errors:
                print(f"{path}: {err}")
        else:
            print(f"{path}: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
