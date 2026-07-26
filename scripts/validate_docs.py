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
  3. skills/*/SKILL.md — at least one; frontmatter `name` and `description`.
  4. .claude-plugin/plugin.json and marketplace.json — valid JSON with
                       required keys AND value shapes (non-empty strings,
                       semver version, plugins as a list of {name, source}).
  5. Internal links in all *.md — inline links (with or without titles),
                       reference definitions, and reference usages. Any
                       relative target (md, json, scripts, images,
                       directories) must exist; http(s)/mailto/# ignored.

`--self-test` proves each check individually: the positive fixture tree
must pass clean, and every `tests/fixtures/docs-validate/negative/<case>/`
tree — complete except for exactly one seeded defect — must produce an
error containing the substring in that case's `EXPECTED` file.
Fixtures are excluded from normal validation.

Registered dependency (pilot plan, prerequisite 1): PyYAML, pinned in CI.
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
        "validate_docs.py requires PyYAML: python3 -m pip install pyyaml==6.0.2",
        file=sys.stderr,
    )
    sys.exit(2)

EXCLUDED_PARTS = {".git", "node_modules"}
FIXTURES_REL = Path("tests/fixtures/docs-validate")

INLINE_LINK_RE = re.compile(
    r"\[[^\]]*\]\(\s*(?:<([^<>]+)>|((?:[^()\s>]|\([^()\s]*\))+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?"
    r"\s*\)"
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REF_DEF_RE = re.compile(r"^\s*\[([^\]\^][^\]]*)\]:\s*(<[^<>]*>|\S+)")
REF_USE_RE = re.compile(r"\[([^\]]+)\]\[([^\]]*)\]")
# Any RFC 3986 scheme (case-insensitive) or protocol-relative URL is external.
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Official semver.org regex: forbids empty identifiers and leading zeroes in
# numeric prerelease identifiers.
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
INVOCATION_VALUES = {"user", "model", "both"}
PERMISSION_TOKENS = ("read_only", "workspace_write", "external")


def parse_frontmatter(text):
    """Return (data, error): parsed frontmatter dict, or an error string."""
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
    if non_empty and isinstance(value, (str, list)) and not (value.strip() if isinstance(value, str) else value):
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
    skill_files = sorted((root / "skills").glob("*/SKILL.md")) if (root / "skills").is_dir() else []
    if not skill_files:
        errors.append("skills/: no */SKILL.md found (empty target set fails the gate)")
        return
    for path in skill_files:
        rel = path.relative_to(root)
        data, err = parse_frontmatter(path.read_text(encoding="utf-8"))
        if err:
            errors.append(f"{rel}: {err}")
            continue
        name = check_field(data, "name", rel, errors)
        if isinstance(name, str):
            if not SKILL_NAME_RE.match(name):
                errors.append(
                    f"{rel}: frontmatter `name` must be lowercase kebab-case "
                    f"([a-z0-9-]), got {name!r}"
                )
            elif name != path.parent.name:
                errors.append(
                    f"{rel}: frontmatter name `{name}` != skill directory `{path.parent.name}`"
                )
        check_field(data, "description", rel, errors)
        permission = check_field(data, "permission-class", rel, errors)
        if isinstance(permission, str):
            words = set(re.findall(r"[a-z_]+", permission))
            if not words & set(PERMISSION_TOKENS):
                errors.append(
                    f"{rel}: frontmatter `permission-class` must contain at least one "
                    f"complete token of {'/'.join(PERMISSION_TOKENS)}, got {permission!r}"
                )
        invocation = check_field(data, "invocation", rel, errors)
        if isinstance(invocation, str):
            items = {part.strip() for part in invocation.split(",") if part.strip()}
            bad = items - INVOCATION_VALUES
            if not items or bad:
                errors.append(
                    f"{rel}: frontmatter `invocation` must be a comma-separated subset of "
                    f"{sorted(INVOCATION_VALUES)}, got {invocation!r}"
                )


def _require_json_str(data, key, rel_path, errors, pattern=None, pattern_desc=""):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{rel_path}: `{key}` must be a non-empty string, got {value!r}")
        return
    if pattern and not pattern.match(value):
        errors.append(f"{rel_path}: `{key}` must be {pattern_desc}, got {value!r}")


def check_json_manifests(root, errors):
    plugin_rel = ".claude-plugin/plugin.json"
    plugin_path = root / plugin_rel
    if not plugin_path.is_file():
        errors.append(f"{plugin_rel}: file not found")
    else:
        try:
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{plugin_rel}: invalid JSON ({exc})")
        else:
            _require_json_str(data, "name", plugin_rel, errors)
            _require_json_str(data, "version", plugin_rel, errors, SEMVER_RE, "semver (X.Y.Z)")

    market_rel = ".claude-plugin/marketplace.json"
    market_path = root / market_rel
    if not market_path.is_file():
        errors.append(f"{market_rel}: file not found")
        return
    try:
        data = json.loads(market_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{market_rel}: invalid JSON ({exc})")
        return
    _require_json_str(data, "name", market_rel, errors)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        errors.append(f"{market_rel}: `plugins` must be a list, got {type(plugins).__name__}")
        return
    for i, entry in enumerate(plugins):
        if not isinstance(entry, dict):
            errors.append(f"{market_rel}: plugins[{i}] must be an object, got {type(entry).__name__}")
            continue
        for key in ("name", "source"):
            if not isinstance(entry.get(key), str) or not entry.get(key).strip():
                errors.append(f"{market_rel}: plugins[{i}].`{key}` must be a non-empty string")


def _heading_anchors(path, cache):
    """GitHub-style anchor IDs for a markdown file's headings, following
    Markdown heading syntax: ATX (1-6 `#` + whitespace, <=3 leading spaces)
    and Setext (paragraph line underlined with `=` or `-`). Indented code
    (>=4 spaces), fenced code, and `#text` without a following space are
    not headings. YAML frontmatter is skipped."""
    if path in cache:
        return cache[path]
    anchors, counts = set(), {}

    def add(text):
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        anchor = re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")
        if not anchor:
            return
        n = counts.get(anchor, 0)
        counts[anchor] = n + 1
        anchors.add(anchor if n == 0 else f"{anchor}-{n}")

    lines = path.read_text(encoding="utf-8").splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    fence = None
    prev_paragraph = None
    for line in lines[start:]:
        stripped = line.strip()
        if fence is None and stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            prev_paragraph = None
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if len(line) - len(line.lstrip(" ")) >= 4:
            prev_paragraph = None  # indented code block line
            continue
        atx = re.match(r"^ {0,3}#{1,6}(?:\s+(.*?))?\s*#*\s*$", line)
        if atx:
            add(atx.group(1) or "")
            prev_paragraph = None
            continue
        if prev_paragraph and re.match(r"^ {0,3}(=+|-+)\s*$", line):
            add(prev_paragraph)
            prev_paragraph = None
            continue
        prev_paragraph = stripped or None
    cache[path] = anchors
    return anchors


def _check_target(target, path, root, errors, anchor_cache):
    """Resolve exactly as Markdown renders: relative to the containing file,
    or to the repo root only for absolute (`/`-prefixed) targets. Fragments
    are verified against the target file's heading anchors."""
    if URI_SCHEME_RE.match(target) or target.startswith("//"):
        return
    clean, _, fragment = target.partition("#")
    if clean:
        if clean.startswith("/"):
            resolved = root / clean.lstrip("/")
        else:
            resolved = path.parent / clean
        try:
            resolved.resolve().relative_to(root.resolve())
        except ValueError:
            errors.append(
                f"{path.relative_to(root)}: link target escapes the repository `{target}`"
            )
            return
        if not resolved.exists():
            errors.append(f"{path.relative_to(root)}: broken relative link `{target}`")
            return
    else:
        resolved = path  # same-document fragment
    if fragment and resolved.is_file() and resolved.suffix == ".md":
        if fragment.lower() not in _heading_anchors(resolved, anchor_cache):
            errors.append(f"{path.relative_to(root)}: broken anchor `{target}`")


def check_links(root, errors, exclude_fixtures=True):
    anchor_cache = {}
    for path in iter_markdown(root, exclude_fixtures=exclude_fixtures):
        text = path.read_text(encoding="utf-8")
        definitions, content_lines = {}, []
        fence = None
        for line in text.splitlines():
            stripped_line = line.strip()
            if fence is None and stripped_line.startswith(("```", "~~~")):
                fence = stripped_line[:3]
                continue
            if fence is not None:
                if stripped_line.startswith(fence):
                    fence = None
                continue
            content_lines.append(line)
            def_match = REF_DEF_RE.match(line)
            if def_match:
                label = re.sub(r"\s+", " ", def_match.group(1)).strip().lower()
                definitions[label] = def_match.group(2)
        for ref_id, target in definitions.items():
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            _check_target(target, path, root, errors, anchor_cache)
        for line in content_lines:
            if REF_DEF_RE.match(line):
                continue
            stripped = re.sub(r"`[^`]*`", "", line)  # ignore inline code spans
            for angled, plain in INLINE_LINK_RE.findall(stripped):
                _check_target(angled or plain, path, root, errors, anchor_cache)
            for text_part, ref_id in REF_USE_RE.findall(stripped):
                key = re.sub(r"\s+", " ", ref_id or text_part).strip().lower()
                if key and key not in definitions:
                    errors.append(
                        f"{path.relative_to(root)}: undefined link reference `{ref_id or text_part}`"
                    )


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
