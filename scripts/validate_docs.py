#!/usr/bin/env python3
"""Deterministic docs-validation gate for this repository.

Checks (conventions.md §4 — a silently no-op gate is a defect, so every
check fails loudly when its target set is empty):

  1. commands/*.md   — at least one file; each has YAML frontmatter (parsed
                       with a real YAML parser) whose `description` is a
                       non-empty string.
  2. agents/*.md     — at least one file; frontmatter `name` (matching the
                       filename), `description` (non-empty string), and
                       `tools` (string or list).
  3. skills/*/SKILL.md — frontmatter `name` and `description`.
  4. .claude-plugin/plugin.json and marketplace.json — valid JSON with the
                       required keys.
  5. Relative markdown links (`[text](path.md)`) in all *.md — the target
                       must exist (relative to the file, then to the repo
                       root). http(s)/mailto/# links are ignored.

`--self-test` proves each check individually: the positive fixture tree
must pass clean, and every `tests/fixtures/docs-validate/negative/<case>/`
tree — complete except for exactly one seeded defect — must produce an
error containing the substring recorded in that case's `EXPECTED` file.
Fixtures are excluded from normal validation.

Requires PyYAML (`python3 -m pip install pyyaml`).
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "validate_docs.py requires PyYAML: python3 -m pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)

EXCLUDED_PARTS = {".git", "node_modules"}
FIXTURES_REL = Path("tests/fixtures/docs-validate")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def parse_frontmatter(text):
    """Return (data, error). data is the parsed frontmatter dict on success;
    error is a human-readable string on failure."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "missing or unterminated YAML frontmatter"
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            block = "\n".join(lines[1:idx])
            try:
                data = yaml.safe_load(block)
            except yaml.YAMLError as exc:
                return None, f"invalid YAML frontmatter ({exc.__class__.__name__}: {exc})"
            if not isinstance(data, dict):
                return None, "invalid YAML frontmatter (not a mapping)"
            return data, None
    return None, "missing or unterminated YAML frontmatter"


def check_field(data, key, rel, errors, types=(str,), non_empty=True):
    if key not in data:
        errors.append(f"{rel}: frontmatter missing required key `{key}`")
        return None
    value = data[key]
    if not isinstance(value, types):
        type_names = "/".join(t.__name__ for t in types)
        errors.append(f"{rel}: frontmatter `{key}` must be {type_names}, got {type(value).__name__}")
        return None
    if non_empty and isinstance(value, str) and not value.strip():
        errors.append(f"{rel}: frontmatter `{key}` is empty")
        return None
    if non_empty and isinstance(value, list) and not value:
        errors.append(f"{rel}: frontmatter `{key}` is empty")
        return None
    return value


def iter_markdown(root, exclude_fixtures=True):
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if exclude_fixtures and rel.parts[: len(FIXTURES_REL.parts)] == FIXTURES_REL.parts:
            continue
        yield path


def check_commands(root, errors):
    directory = root / "commands"
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not files:
        errors.append("commands/: no markdown files found (empty target set fails the gate)")
        return
    for path in files:
        rel = path.relative_to(root)
        data, err = parse_frontmatter(path.read_text(encoding="utf-8"))
        if err:
            errors.append(f"{rel}: {err}")
            continue
        check_field(data, "description", rel, errors)


def check_agents(root, errors):
    directory = root / "agents"
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not files:
        errors.append("agents/: no markdown files found (empty target set fails the gate)")
        return
    for path in files:
        rel = path.relative_to(root)
        data, err = parse_frontmatter(path.read_text(encoding="utf-8"))
        if err:
            errors.append(f"{rel}: {err}")
            continue
        name = check_field(data, "name", rel, errors)
        check_field(data, "description", rel, errors)
        check_field(data, "tools", rel, errors, types=(str, list))
        if isinstance(name, str) and name != path.stem:
            errors.append(f"{rel}: frontmatter name `{name}` != filename `{path.stem}`")


def check_skills(root, errors):
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return  # skills are optional until the pilot lands them
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        errors.append("skills/: directory exists but contains no */SKILL.md")
    for path in skill_files:
        rel = path.relative_to(root)
        data, err = parse_frontmatter(path.read_text(encoding="utf-8"))
        if err:
            errors.append(f"{rel}: {err}")
            continue
        check_field(data, "name", rel, errors)
        check_field(data, "description", rel, errors)


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
                errors.append(f"{path.relative_to(root)}: broken relative link `{target}`")


def validate(root, exclude_fixtures=True):
    errors = []
    check_commands(root, errors)
    check_agents(root, errors)
    check_skills(root, errors)
    check_json_manifests(root, errors)
    check_links(root, errors, exclude_fixtures=exclude_fixtures)
    return errors


def self_test(repo_root):
    fixtures = repo_root / FIXTURES_REL
    positive = fixtures / "positive"
    negative_root = fixtures / "negative"
    failed = False

    pos_errors = validate(positive, exclude_fixtures=False)
    if pos_errors:
        failed = True
        print("self-test FAILED: positive fixture should pass but produced:", file=sys.stderr)
        for err in pos_errors:
            print(f"  {err}", file=sys.stderr)
    else:
        print("self-test: positive fixture clean")

    cases = sorted(d for d in negative_root.iterdir() if d.is_dir()) if negative_root.is_dir() else []
    if not cases:
        print("self-test FAILED: no negative fixture cases found", file=sys.stderr)
        return 1
    for case in cases:
        expected_file = case / "EXPECTED"
        if not expected_file.is_file():
            failed = True
            print(f"self-test FAILED: {case.name}: missing EXPECTED file", file=sys.stderr)
            continue
        expected = expected_file.read_text(encoding="utf-8").strip()
        errors = validate(case, exclude_fixtures=False)
        matching = [e for e in errors if expected in e]
        if matching:
            print(f"self-test: negative/{case.name}: caught ({matching[0]})")
        else:
            failed = True
            print(
                f"self-test FAILED: negative/{case.name}: expected an error containing "
                f"`{expected}`, got: {errors or '[no errors]'}",
                file=sys.stderr,
            )
    if failed:
        return 1
    print(f"self-test OK: positive clean, {len(cases)} negative cases each caught by their check")
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
