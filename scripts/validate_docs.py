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
  3. skills/*/SKILL.md — at least one; frontmatter `name` (kebab-case,
                       matching the skill directory), `description`,
                       `permission-class`, and `invocation`.
  4. .claude-plugin/plugin.json and marketplace.json — valid JSON with
                       required keys AND value shapes (non-empty strings,
                       full-spec semver version, plugins as a list of
                       {name, source}).
  5. Internal links in all *.md — extracted with the CommonMark reference
                       parser (markdown-it-py), so code fences/spans,
                       escapes, titles, angle brackets, reference links,
                       images, lists and indented code follow the spec
                       exactly. Targets are URL-normalized, must stay
                       inside the repository, and fragments are verified
                       case-sensitively against GitHub-style heading
                       anchors. Undefined reference labels are reported.

`--self-test` proves each check individually: the positive fixture tree
must pass clean, and every `tests/fixtures/docs-validate/negative/<case>/`
tree — complete except for exactly one seeded defect — must produce an
error containing the substring in that case's `EXPECTED` file.
Fixtures are excluded from normal validation.

Registered dependencies (pilot plan, prerequisite 1): PyYAML and
markdown-it-py, both pinned in CI.
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "validate_docs.py requires PyYAML: python3 -m pip install pyyaml==6.0.2",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover
    print(
        "validate_docs.py requires markdown-it-py: "
        "python3 -m pip install markdown-it-py==3.0.0",
        file=sys.stderr,
    )
    sys.exit(2)

EXCLUDED_PARTS = {".git", "node_modules"}
FIXTURES_REL = Path("tests/fixtures/docs-validate")
# The plugin subtree in the real repo; fixture repos keep components at root.
PLUGIN_REL = Path("plugins/rpa")
# The TDD session-log validator is resolved from the REAL repository that owns
# this script (not from the root being validated), so the docs-validate fixture
# roots exercise the production binding with the production validator.
SESSION_LOG_VALIDATOR = (
    Path(__file__).resolve().parents[1]
    / "plugins" / "rpa" / "skills" / "tdd" / "scripts" / "validate_session_log.py"
)
# Session logs are discovered by the contract's mandatory file name shape
# (skills/tdd/references/session-log-contract.md) AND by their H1.
SESSION_LOG_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-TDD-SESSION-.+\.md$")
SESSION_LOG_H1 = "# TDD Session:"
# Fixture cases the session-log validator must be proven against (one
# directory each under skills/tdd/scripts/fixtures/session-logs/).
SESSION_LOG_FIXTURE_CASES = (
    "valid", "valid-continuing", "missing-receipt", "unresolvable-receipt",
    "manual-as-green", "heading-order", "run-mismatch", "nonpass-disposition",
    "fenced-heading", "html-comment-heading", "broken-chain", "missing-checkpoint",
    "hollow", "uncited-attempt", "inline-comment-hidden", "standin-exit-only", "tampered-export",
    "trimmed-export", "intent-deleted", "duplicate-terminal", "ref-mismatch",
    "unsealed-complete", "achieved-mismatch", "partial-cases", "plan-mismatch",
    "export-traversal", "export-absolute", "export-symlink",
    "trailing-transcription", "baseline-runs-missing", "not-run-with-transcription",
    "colon-transcription", "disposition-transcription", "receipts-field-missing",
    "contradictory-not-run", "extra-disposition-cell",
    "receipts-label-hybrid", "test-configuration-command", "duplicate-baseline-runs",
    "attempt-after-checkpoint", "record-after-final",
)


def plugin_root(root):
    candidate = root / PLUGIN_REL
    return candidate if candidate.is_dir() else root

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
INVOCATION_VALUES = {"user", "model", "both", "none"}
PERMISSION_TOKENS = ("read_only", "workspace_write", "external")
# permission-class grammar: `+`-separated class tokens, each optionally
# qualified by a parenthesized scope, e.g. "read_only (target repo) +
# workspace_write (thoughts/shared/research/ only)".
PERMISSION_PART_RE = re.compile(
    r"^(?:read_only|workspace_write|external)(?:\s*\([^()]*\))?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Reference-style usage in rendered TEXT (i.e. left unresolved by the parser).
REF_USE_RE = re.compile(r"\[([^\]]+)\]\[([^\]]*)\]")
class _HrefExtractor(HTMLParser):
    """Extract targets only from real link-bearing attributes of real tags,
    so comments, script examples, and data-* attributes are ignored."""

    LINK_ATTRS = {
        ("a", "href"),
        ("area", "href"),
        ("link", "href"),
        ("img", "src"),
        ("source", "src"),
        ("video", "src"),
        ("audio", "src"),
        ("iframe", "src"),
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value and (tag.lower(), name.lower()) in self.LINK_ATTRS:
                self.targets.append(value)


def _iter_html_targets(html):
    parser = _HrefExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.targets

_MD = MarkdownIt("commonmark")


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


def strip_frontmatter(text):
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return "\n".join(lines[idx + 1:])
    return text


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
    directory = plugin_root(root) / "commands"
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
    directory = plugin_root(root) / "agents"
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
        tools = check_field(data, "tools", rel, errors, types=(str, list))
        if isinstance(tools, list):
            for i, item in enumerate(tools):
                if not isinstance(item, str) or not item.strip():
                    errors.append(
                        f"{rel}: frontmatter `tools[{i}]` must be a non-empty string, "
                        f"got {item!r}"
                    )
        if isinstance(name, str) and name != path.stem:
            errors.append(f"{rel}: frontmatter name `{name}` != filename `{path.stem}`")


def check_skills(root, errors):
    skills_dir = plugin_root(root) / "skills"
    skill_files = sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []
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
            parts = [p.strip() for p in permission.split("+")]
            for part in parts:
                if not part or not PERMISSION_PART_RE.match(part):
                    errors.append(
                        f"{rel}: frontmatter `permission-class` part {part!r} must be "
                        f"one of {'/'.join(PERMISSION_TOKENS)} with an optional "
                        f"parenthesized qualifier"
                    )
        invocation = check_field(data, "invocation", rel, errors)
        if isinstance(invocation, str) and invocation.strip() not in INVOCATION_VALUES:
            errors.append(
                f"{rel}: frontmatter `invocation` must be exactly one of "
                f"{sorted(INVOCATION_VALUES)} (`both` already expresses dual "
                f"invocation), got {invocation!r}"
            )


def _require_json_str(data, key, rel_path, errors, pattern=None, pattern_desc=""):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{rel_path}: `{key}` must be a non-empty string, got {value!r}")
        return
    if pattern and not pattern.match(value):
        errors.append(f"{rel_path}: `{key}` must be {pattern_desc}, got {value!r}")


def check_json_manifests(root, errors):
    plugin_base = plugin_root(root)
    plugin_path = plugin_base / ".claude-plugin/plugin.json"
    plugin_rel = str(plugin_path.relative_to(root))
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


class _DocIndex:
    """Per-file CommonMark parse results, cached."""

    def __init__(self):
        self._parses = {}
        self._anchors = {}

    def tokens_env(self, path):
        if path not in self._parses:
            env = {}
            body = strip_frontmatter(path.read_text(encoding="utf-8"))
            tokens = _MD.parse(body, env)
            self._parses[path] = (tokens, env, body)
        return self._parses[path]

    def anchors(self, path):
        """GitHub-style anchor IDs for the file's headings."""
        if path in self._anchors:
            return self._anchors[path]
        anchors = set()
        tokens, _, _ = self.tokens_env(path)
        for i, tok in enumerate(tokens):
            if tok.type != "heading_open":
                continue
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            text = ""
            if inline is not None and inline.children:
                # GitHub derives the slug from the full rendered heading
                # text, including image alt text.
                text = "".join(
                    child.content
                    for child in inline.children
                    if child.type in ("text", "code_inline", "image")
                )
            anchor = re.sub(r"[^\w\- ]", "", text.lower()).strip().replace(" ", "-")
            if not anchor:
                continue
            # GitHub dedupes against every emitted final slug, so
            # `foo, foo-1, foo` yields foo, foo-1, foo-2.
            if anchor in anchors:
                n = 1
                while f"{anchor}-{n}" in anchors:
                    n += 1
                anchor = f"{anchor}-{n}"
            anchors.add(anchor)
        self._anchors[path] = anchors
        return anchors


def _check_target(target, path, root, errors, index):
    """Resolve exactly as Markdown renders: relative to the containing file,
    or to the repo root only for absolute (`/`-prefixed) targets. Fragments
    are verified case-sensitively against the target's heading anchors."""
    if URI_SCHEME_RE.match(target) or target.startswith("//"):
        return
    clean, _, fragment = target.partition("#")
    # URL semantics: drop the query string, percent-decode path and fragment.
    clean = unquote(clean.partition("?")[0])
    fragment = unquote(fragment)
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
        # Fragment identifiers are case-sensitive: generated anchors are
        # lowercase, so `#Setup` does not navigate to `# Setup`.
        if fragment not in index.anchors(resolved):
            errors.append(f"{path.relative_to(root)}: broken anchor `{target}`")


def _normalize_ref_label(label):
    return re.sub(r"\s+", " ", label).strip().upper()


def _preceding_backslashes(text, pos):
    n, i = 0, pos - 1
    while i >= 0 and text[i] == "\\":
        n += 1
        i -= 1
    return n


def check_links(root, errors, exclude_fixtures=True):
    index = _DocIndex()
    for path in iter_markdown(root, exclude_fixtures=exclude_fixtures):
        tokens, env, body = index.tokens_env(path)
        references = env.get("references", {}) or {}
        # Reference definitions: validate each recorded destination.
        for ref in references.values():
            href = ref.get("href")
            if href:
                _check_target(href, path, root, errors, index)
        pending_refs = set()
        for tok in tokens:
            if tok.type == "html_block":
                for target in _iter_html_targets(tok.content):
                    _check_target(target, path, root, errors, index)
                continue
            if tok.type != "inline" or not tok.children:
                continue
            for child in tok.children:
                if child.type == "link_open":
                    href = child.attrGet("href")
                    if href:
                        _check_target(href, path, root, errors, index)
                elif child.type == "image":
                    src = child.attrGet("src")
                    if src:
                        _check_target(src, path, root, errors, index)
                elif child.type == "html_inline":
                    for target in _iter_html_targets(child.content):
                        _check_target(target, path, root, errors, index)
            # A reference-style usage the parser left as literal text means
            # its label has no definition. Scan the inline token's joined
            # plain text so labels containing inline formatting (split
            # across child tokens) are still seen.
            joined = "".join(
                child.content for child in tok.children if child.type == "text"
            )
            for text_part, ref_id in REF_USE_RE.findall(joined):
                label = _normalize_ref_label(ref_id or text_part)
                if label and label not in references:
                    pending_refs.add((text_part, ref_id))
        for text_part, ref_id in sorted(pending_refs):
            # The parser unescapes text, so escaped literals look identical
            # here; consult the source. For explicit ids, match any
            # unescaped `[label][id]` occurrence positionally; implicit
            # refs fall back to literal counting.
            # An occurrence counts as escaped only when the opener is
            # preceded by an ODD run of backslashes (CommonMark parity:
            # \\[ is an escaped backslash followed by a real opener).
            if ref_id:
                pattern = re.compile(r"\[[^\]]*\]\[" + re.escape(ref_id) + r"\]")
                if not any(
                    _preceding_backslashes(body, m.start()) % 2 == 0
                    for m in pattern.finditer(body)
                ):
                    continue  # every source occurrence is escaped (or absent)
            else:
                literal = f"[{text_part}][]"
                positions, start = [], 0
                while (pos := body.find(literal, start)) != -1:
                    positions.append(pos)
                    start = pos + 1
                if positions and not any(
                    _preceding_backslashes(body, p) % 2 == 0 for p in positions
                ):
                    continue
            errors.append(
                f"{path.relative_to(root)}: undefined link reference "
                f"`{ref_id or text_part}`"
            )


def check_artifact_validator(root, errors):
    """The research artifact contract is bound as an executable gate:
    the validator must accept the positive fixture and reject the negative
    one — a validator that passes everything is a silent no-op defect
    (conventions SS4)."""
    import subprocess as _sp
    import sys as _sys
    skill_root = plugin_root(root) / "skills" / "research-codebase"
    if not skill_root.is_dir():
        # not_applicable: the research skill package is absent from this
        # root (e.g. the self-test fixture repos) — there is no artifact
        # contract to bind. In the real repo the package exists and the
        # gate below is enforced.
        return
    validator = skill_root / "evals" / "public" / "validate_artifact.py"
    fixtures = validator.parent / "fixtures"
    good = fixtures / "artifact-valid.md"
    bad = fixtures / "artifact-invalid.md"
    if not (validator.is_file() and good.is_file() and bad.is_file()):
        errors.append(
            "artifact validator or its fixtures missing under "
            "skills/research-codebase/evals/public/")
        return
    ok = _sp.run([_sys.executable, str(validator), str(good)],
                 capture_output=True)
    if ok.returncode != 0:
        errors.append(
            f"artifact validator rejects the VALID fixture: "
            f"{ok.stdout.decode()[:200]}")
    ko = _sp.run([_sys.executable, str(validator), str(bad)],
                 capture_output=True)
    if ko.returncode == 0:
        errors.append(
            "artifact validator accepted the INVALID fixture — the gate "
            "is a silent no-op")
    subtle = fixtures / "artifact-subtle-invalid.md"
    if not subtle.is_file():
        errors.append("artifact-subtle-invalid.md fixture missing")
        return
    ks = _sp.run([_sys.executable, str(validator), str(subtle)],
                 capture_output=True)
    if ks.returncode == 0:
        errors.append(
            "artifact validator accepted the SUBTLE-invalid fixture "
            "(empty values / wrong status / prefix-only heading) — value "
            "and exact-heading enforcement is broken")
    fenced = fixtures / "artifact-fenced-invalid.md"
    if not fenced.is_file():
        errors.append("artifact-fenced-invalid.md fixture missing")
        return
    kf = _sp.run([_sys.executable, str(validator), str(fenced)],
                 capture_output=True)
    if kf.returncode == 0:
        errors.append(
            "artifact validator accepted headings quoted inside a code "
            "fence — structural parsing is broken")
    hollow = fixtures / "artifact-empty-sections-invalid.md"
    if not hollow.is_file():
        errors.append("artifact-empty-sections-invalid.md fixture missing")
        return
    kh = _sp.run([_sys.executable, str(validator), str(hollow)],
                 capture_output=True)
    if kh.returncode == 0:
        errors.append(
            "artifact validator accepted a document of empty sections — "
            "content enforcement is broken")
    unzoned = fixtures / "artifact-unzoned-invalid.md"
    if not unzoned.is_file():
        errors.append("artifact-unzoned-invalid.md fixture missing")
        return
    ku = _sp.run([_sys.executable, str(validator), str(unzoned)],
                 capture_output=True)
    if ku.returncode == 0:
        errors.append(
            "artifact validator accepted a timezone-less timestamp — the "
            "contract requires date and time WITH timezone")
    nometa = fixtures / "artifact-no-metablock-invalid.md"
    if not nometa.is_file():
        errors.append("artifact-no-metablock-invalid.md fixture missing")
        return
    kn = _sp.run([_sys.executable, str(validator), str(nometa)],
                 capture_output=True)
    if kn.returncode == 0:
        errors.append(
            "artifact validator accepted a document without the body "
            "metadata block (**Date**/**Researcher**/...) — template "
            "enforcement is broken")
    bodymeta = fixtures / "artifact-bodymeta-invalid.md"
    if not bodymeta.is_file():
        errors.append("artifact-bodymeta-invalid.md fixture missing")
        return
    kb = _sp.run([_sys.executable, str(validator), str(bodymeta)],
                 capture_output=True)
    if kb.returncode == 0:
        errors.append(
            "artifact validator accepted body metadata disagreeing with "
            "the frontmatter — duplicated-field cross-checks are broken")
    scattered = fixtures / "artifact-scattered-metablock-invalid.md"
    if not scattered.is_file():
        errors.append("artifact-scattered-metablock-invalid.md fixture "
                      "missing")
        return
    ks2 = _sp.run([_sys.executable, str(validator), str(scattered)],
                  capture_output=True)
    if ks2.returncode == 0:
        errors.append(
            "artifact validator accepted metadata lines scattered outside "
            "the title-adjacent block — block placement is not enforced")
    interleaved = fixtures / "artifact-interleaved-metablock-invalid.md"
    if not interleaved.is_file():
        errors.append("artifact-interleaved-metablock-invalid.md fixture "
                      "missing")
        return
    ki = _sp.run([_sys.executable, str(validator), str(interleaved)],
                 capture_output=True)
    if ki.returncode == 0:
        errors.append(
            "artifact validator accepted prose interleaved inside the "
            "metadata block — contiguity is not enforced")


def _first_h1(path):
    """First `# ` heading outside fenced code and HTML comments, or ""."""
    in_fence = None
    in_comment = False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if in_fence is not None:
            if stripped.startswith(in_fence):
                in_fence = None
            continue
        m = re.match(r"^\s{0,3}(```+|~~~+)", line)
        if m:
            in_fence = m.group(1)[0] * 3
            continue
        if stripped.startswith("<!--") and "-->" not in stripped[4:]:
            in_comment = True
            continue
        if re.match(r"^# \S", line):
            return stripped
    return ""


def _run_session_log_validator(log):
    import subprocess as _sp
    import sys as _sys
    return _sp.run([_sys.executable, str(SESSION_LOG_VALIDATOR), str(log)],
                   capture_output=True, text=True)


def check_session_log_validator(root, errors):
    """The TDD session-log contract is bound as an executable gate: the
    validator must accept every `valid*` fixture case and reject every other
    case (conventions §4). A missing case is itself an error."""
    skill_root = plugin_root(root) / "skills" / "tdd"
    if not skill_root.is_dir():
        # not_applicable: the tdd skill package is absent from this root
        # (e.g. the self-test fixture repos).
        return
    validator = skill_root / "scripts" / "validate_session_log.py"
    fixtures = skill_root / "scripts" / "fixtures" / "session-logs"
    if not validator.is_file() or not fixtures.is_dir():
        errors.append("session-log validator or its fixtures missing under "
                      "skills/tdd/scripts/")
        return
    cases = {d.name: d for d in fixtures.iterdir()
             if d.is_dir() and not d.name.startswith((".", "_"))}
    for name in SESSION_LOG_FIXTURE_CASES:
        if name not in cases:
            errors.append(f"session-log fixture case missing: {name}")
    for name, case in sorted(cases.items()):
        logs = sorted((case / "thoughts" / "shared" / "tests").glob("*-TDD-SESSION-*.md"))
        if len(logs) != 1:
            errors.append(f"session-log fixture {name}: expected exactly one log, found {len(logs)}")
            continue
        res = _run_session_log_validator(logs[0])
        if name.startswith("valid"):
            if res.returncode != 0:
                errors.append(f"session-log validator rejects the VALID fixture {name}: "
                              f"{(res.stdout + res.stderr)[:200]}")
        elif res.returncode == 0:
            errors.append(f"session-log validator accepted the INVALID fixture {name} — "
                          "the gate is a silent no-op for that check")
        elif res.returncode != 1:
            errors.append(f"session-log validator crashed on fixture {name}: "
                          f"{(res.stdout + res.stderr)[:200]}")


def check_session_logs(root, errors):
    """Every committed TDD session log validates and every committed receipt
    export is cited by one. Discovery = contract file name ∪ H1 (de-duplicated
    by path); the validator, not discovery, checks the H1 and layout."""
    tests_dir = root / "thoughts" / "shared" / "tests"
    if not tests_dir.is_dir():
        return  # not_applicable: nothing to validate
    logs = {}
    for path in sorted(tests_dir.glob("*.md")):
        if SESSION_LOG_NAME_RE.match(path.name) or _first_h1(path).startswith(SESSION_LOG_H1):
            logs[path.resolve()] = path
    receipts_dir = tests_dir / "receipts"
    receipts = sorted(receipts_dir.glob("*.json")) if receipts_dir.is_dir() else []
    if not logs and not receipts:
        return  # not_applicable
    if not SESSION_LOG_VALIDATOR.is_file():
        errors.append(f"session-log validator missing: {SESSION_LOG_VALIDATOR}")
        return
    cited = set()
    for _, log in sorted(logs.items()):
        rel = log.relative_to(root)
        res = _run_session_log_validator(log)
        if res.returncode != 0:
            lines = [l for l in (res.stdout + res.stderr).splitlines() if l.strip()] or ["rejected"]
            for line in lines:
                errors.append(f"{rel}: {line}")
        m = re.search(r"\*\*Evidence export\*\*:\s*`?([^`\s]+)", log.read_text(encoding="utf-8"))
        if m:
            cited.add((log.parent / m.group(1)).resolve())
    for rcpt in receipts:
        if rcpt.resolve() not in cited:
            errors.append(f"{rcpt.relative_to(root)}: orphan export — no session log cites it")


def validate(root, exclude_fixtures=True):
    errors = []
    check_commands(root, errors)
    check_agents(root, errors)
    check_skills(root, errors)
    check_json_manifests(root, errors)
    check_artifact_validator(root, errors)
    check_session_log_validator(root, errors)
    check_session_logs(root, errors)
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
