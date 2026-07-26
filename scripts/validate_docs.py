#!/usr/bin/env python3
"""Deterministic docs-validation gate for this repository.

Checks (conventions.md §4 — a silently no-op gate is a defect, so every
check fails loudly when its target set is empty):

  1. commands/*.md   — at least one file; each has YAML frontmatter with a
                       `description` key.
  2. agents/*.md     — at least one file; each has frontmatter with `name`,
                       `description`, and `tools` keys; `name` must match
                       the filename.
  3. skills/*/SKILL.md — each has frontmatter with `name` and `description`.
  4. .claude-plugin/plugin.json and marketplace.json — valid JSON with the
                       required keys.
  5. Relative markdown links (`[text](path.md)` and friends) in all *.md —
                       the target must exist (checked relative to the file,
                       then to the repo root). http(s)/mailto/# links are
                       ignored.

`--self-test` runs the validator against the bundled positive and negative
fixtures (tests/fixtures/docs-validate/) and fails unless the positive tree
passes and the negative tree is caught. Fixtures are excluded from normal
validation.
"""

import argparse
import json
import re
import sys
from pathlib import Path

EXCLUDED_PARTS = {".git", "node_modules"}
FIXTURES_REL = Path("tests/fixtures/docs-validate")

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")


def parse_frontmatter_keys(text):
    """Return the set of top-level frontmatter keys, or None if there is no
    well-formed frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    keys = set()
    for line in lines[1:]:
        if line.strip() == "---":
            return keys
        match = KEY_RE.match(line)
        if match:
            keys.add(match.group(1))
    return None  # unterminated block


def iter_markdown(root, exclude_fixtures=True):
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if exclude_fixtures and rel.parts[: len(FIXTURES_REL.parts)] == FIXTURES_REL.parts:
            continue
        yield path


def check_frontmatter_dir(root, subdir, required, errors, name_matches_file=False):
    directory = root / subdir
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not files:
        errors.append(f"{subdir}/: no markdown files found (empty target set fails the gate)")
        return
    for path in files:
        keys = parse_frontmatter_keys(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root)
        if keys is None:
            errors.append(f"{rel}: missing or unterminated YAML frontmatter")
            continue
        for key in required:
            if key not in keys:
                errors.append(f"{rel}: frontmatter missing required key `{key}`")
        if name_matches_file and "name" in keys:
            name_line = next(
                (l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("name:")),
                "",
            )
            declared = name_line.split(":", 1)[1].strip()
            if declared and declared != path.stem:
                errors.append(f"{rel}: frontmatter name `{declared}` != filename `{path.stem}`")


def check_skills(root, errors):
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return  # skills are optional until the pilot lands them
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        errors.append("skills/: directory exists but contains no */SKILL.md")
    for path in skill_files:
        keys = parse_frontmatter_keys(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root)
        if keys is None:
            errors.append(f"{rel}: missing or unterminated YAML frontmatter")
        else:
            for key in ("name", "description"):
                if key not in keys:
                    errors.append(f"{rel}: frontmatter missing required key `{key}`")


def check_json_manifests(root, errors):
    manifests = [
        (".claude-plugin/plugin.json", ("name", "version")),
        (".claude-plugin/marketplace.json", ("name", "plugins")),
    ]
    for rel_path, required in manifests:
        path = root / rel_path
        if not path.is_file():
            errors.append(f"{rel_path}: file not found")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel_path}: invalid JSON ({exc})")
            continue
        for key in required:
            if key not in data:
                errors.append(f"{rel_path}: missing required key `{key}`")


def check_links(root, errors, exclude_fixtures=True):
    for path in iter_markdown(root, exclude_fixtures=exclude_fixtures):
        text = path.read_text(encoding="utf-8")
        in_fence = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in LINK_RE.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                clean = target.split("#", 1)[0]
                if not clean or not clean.endswith(".md"):
                    continue
                if (path.parent / clean).exists() or (root / clean).exists():
                    continue
                errors.append(
                    f"{path.relative_to(root)}: broken relative link `{target}`"
                )


def validate(root, exclude_fixtures=True):
    errors = []
    check_frontmatter_dir(root, "commands", ("description",), errors)
    check_frontmatter_dir(root, "agents", ("name", "description", "tools"), errors, name_matches_file=True)
    check_skills(root, errors)
    check_json_manifests(root, errors)
    check_links(root, errors, exclude_fixtures=exclude_fixtures)
    return errors


def self_test(repo_root):
    fixtures = repo_root / FIXTURES_REL
    positive, negative = fixtures / "positive", fixtures / "negative"
    for tree in (positive, negative):
        if not tree.is_dir():
            print(f"self-test: fixture tree missing: {tree}", file=sys.stderr)
            return 1
    pos_errors = validate(positive, exclude_fixtures=False)
    if pos_errors:
        print("self-test FAILED: positive fixture should pass but produced:", file=sys.stderr)
        for err in pos_errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    neg_errors = validate(negative, exclude_fixtures=False)
    if not neg_errors:
        print("self-test FAILED: negative fixture passed but must be caught", file=sys.stderr)
        return 1
    print(f"self-test OK: positive clean, negative caught ({len(neg_errors)} errors)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to validate")
    parser.add_argument("--self-test", action="store_true", help="run against bundled fixtures")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.self_test:
        sys.exit(self_test(root))

    errors = validate(root)
    if errors:
        print(f"docs validation FAILED: {len(errors)} error(s)", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)
    print("docs validation OK")


if __name__ == "__main__":
    main()
