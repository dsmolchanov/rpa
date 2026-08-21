#!/usr/bin/env python3
"""Validate a TDD session log against its committed evidence export.

Usage: validate_session_log.py <thoughts/shared/tests/<date>-TDD-SESSION-<slug>.md>

Exit 0 valid; 1 invalid (one `session-log: <check> — <detail>` line per error);
2 usage (missing file, log outside the contract layout).

The log must live at <root>/thoughts/shared/tests/<name>.md; its export is
exactly <root>/thoughts/shared/tests/receipts/<run-id>.json; its test plan is
the repo-relative `**Test Plan**` header. Checks (a)–(m) are defined in
../references/evidence-contract.md and the session-log contract; this file
implements them. Stdlib only; imports only the sibling evidence.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evidence import (  # noqa: E402
    RUN_ID_RE, canonical_json, derive_index, ledger_digest, pair_records, phase_state,
    receipt_of, sha256_bytes, sha256_file,
)

HEADINGS = ["# TDD Session:", "## Baseline", "## Case Dispositions", "## Red Phase",
            "## Green Phase", "## Refactor Phase", "## Final Verification", "## Summary"]
DISPOSITIONS = {"valid Red", "Green", "refactored-green", "already covered", "blocked", "not_applicable"}
EVIDENCE_DISPOSITIONS = {"valid Red", "Green", "refactored-green"}
ACHIEVED_MAP = {"Red": "red", "Green": "green", "Refactored Green": "refactored-green", "Blocked": "blocked"}
STATE_TO_ACHIEVED_PHASE = {"red": "Red", "green": "Green", "refactor": "Refactored Green"}
RECEIPT_RE = re.compile(r"\breceipt ([0-9a-f]{12})\b")
# Receipt-only citation shape, anchored over the WHOLE entry: the argv/exit
# live in the export, never in the log — a summary may not carry backticked
# commands, `→` exit arrows, or ` · ` separators.
CITATION_RE = re.compile(r"^`receipt [0-9a-f]{12}`:\s*[^`→·\n]*\S[^`→·\n]*$")
CASE_ROW_RE = re.compile(r"^\|\s*([UIE]-\d+)\s*\|")
NOT_RUN_RE = re.compile(r"(Not run|Not applicable) — \S")
# The not-run alternative is an ENTIRE entry too: `Not run — <reason>` /
# `Not applicable — <reason>` with no backticks, exit arrows, separators, or
# receipt tokens smuggled after the reason.
NOT_RUN_ENTRY_RE = re.compile(r"^(?!.*\breceipt [0-9a-f]{12}\b)(Not run|Not applicable) — [^`→·\n]*\S$")


# Case Dispositions Evidence cell: `receipt <hex12> — <salient assertion>`
# (optionally containing the word stand-in) — same no-transcription rule.
EVIDENCE_CELL_RE = re.compile(r"^receipt [0-9a-f]{12} — [^`→·\n]*\S$")
REASON_CELL_RE = re.compile(r"^(?!.*\breceipt [0-9a-f]{12}\b)[^`→·\n]*\S$")
# `**Test configuration**`: a list of configuration FILE PATHS (comma/space
# separated, optionally backticked) — each token is path-shaped (no spaces,
# contains `/` or `.`, no shell characters) — or an anchored not-run entry.
PATH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_@+./-]+$")


NOT_APPLICABLE_ENTRY_RE = re.compile(r"^(?!.*\breceipt [0-9a-f]{12}\b)Not applicable — [^`→·\n]*\S$")


def test_configuration_ok(value: str) -> bool:
    if NOT_APPLICABLE_ENTRY_RE.match(value):
        return True
    if RECEIPT_RE.search(value) or "→" in value or "·" in value:
        return False
    tokens = [t.strip().strip("`") for t in re.split(r"[,\s]+", value) if t.strip()]
    if not tokens:
        return False
    return all(PATH_TOKEN_RE.match(t) and ("/" in t or "." in t) for t in tokens)


def entry_ok(body: str) -> bool:
    """A receipt-only citation or an anchored not-run entry — nothing else."""
    return bool(CITATION_RE.match(body) or NOT_RUN_ENTRY_RE.match(body))
PHASE_RANK = {"baseline": 0, "red": 1, "green": 2, "refactor": 3, "final": 4}
TERMINAL_KINDS = ("finished", "error", "interrupted", "timeout")
INTENT_FIELDS = ("ref", "n", "run", "workflow", "phase", "case", "because", "risk", "argv", "cwd",
                 "claims_text", "scopes", "envelope", "requires", "report_path", "timeout",
                 "tail_bytes", "lease_nonce", "at")


class Errors(list):
    def add(self, check: str, detail: str) -> None:
        self.append(f"session-log: {check} — {detail}")


# --------------------------------------------------------------------------
# structural parsing: drop fenced/indented code, HTML comments, HTML blocks


def content_lines(text: str) -> list:
    """Return (lineno, line) pairs that count as document content."""
    out = []
    lines = text.splitlines()
    in_fence = None
    in_comment = False
    in_html_block = False
    prev_nonblank = ""
    for idx, line in enumerate(lines, 1):
        # HTML comments may open anywhere on a line and close lines later:
        # strip every commented span (stateful), keep only the visible rest.
        if in_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = line[end + 3:]
            in_comment = False
        while True:
            start = line.find("<!--")
            if start < 0:
                break
            end = line.find("-->", start + 4)
            if end < 0:
                line = line[:start]
                in_comment = True
                break
            line = line[:start] + line[end + 3:]
        stripped = line.strip()
        if in_fence is not None:
            if stripped.startswith(in_fence):
                in_fence = None
            continue
        if in_html_block:
            if not stripped:
                in_html_block = False
            continue
        if not stripped and in_comment:
            continue
        m = re.match(r"^\s{0,3}(```+|~~~+)", line)
        if m:
            in_fence = m.group(1)[0] * 3
            continue
        if re.match(r"^\s{0,3}<(/?[A-Za-z][A-Za-z0-9-]*|!)", line):
            in_html_block = True
            continue
        # indented code: >=4 spaces / tab, not a continuation of a list item
        if re.match(r"^( {4,}|\t)", line) and stripped:
            if not re.match(r"^\s*([-*+]|\d+[.)])\s", prev_nonblank):
                continue
        if stripped:
            prev_nonblank = line
        out.append((idx, line))
    return out


def strip_inline_html_comments(s: str) -> str:
    return re.sub(r"<!--.*?-->", "", s)


# --------------------------------------------------------------------------
# helpers


def header_value(lines: list, key: str) -> str | None:
    pat = re.compile(r"^\*\*" + re.escape(key) + r"\*\*:\s*`?([^`]*?)`?\s*$")
    for _, line in lines:
        m = pat.match(line.strip())
        if m:
            return m.group(1).strip()
    return None


def sections(lines: list) -> dict:
    """Map heading text -> list of (lineno, line) under it (until next #/## heading)."""
    out: dict = {}
    current = None
    for no, line in lines:
        if re.match(r"^#{1,2} ", line):
            current = line.strip()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append((no, line))
    return out


def find_section(secs: dict, prefix: str) -> list:
    for key, body in secs.items():
        if key == prefix or key.startswith(prefix + " ") or key.startswith(prefix):
            if key.startswith(prefix):
                return body
    return []


def table_rows(body: list) -> list:
    """Data rows of the first pipe table in a section body (excluding header/separator)."""
    rows = []
    seen_header = False
    for _, line in body:
        s = line.strip()
        if not s.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def field_lines(body: list, label: str) -> list:
    """(lineno, value) for every top-level `- **<label>**:` line — the label is
    matched EXACTLY (colon immediately after the closing emphasis)."""
    pat = re.compile(r"^-\s*\*\*" + re.escape(label) + r"\*\*:\s*(.*)$")
    out = []
    for no, line in body:
        m = pat.match(line.strip())
        if m:
            out.append((no, m.group(1).strip()))
    return out


def has_receipts_field(body: list) -> bool:
    return len(field_lines(body, "Receipts")) == 1


def commands_bullets(body: list) -> list:
    """Nested bullets under the exact `**Receipts**:` line."""
    out, active = [], False
    for no, line in body:
        s = line.strip()
        if re.match(r"^-\s*\*\*Receipts\*\*:", s):
            active = True
            continue
        if active:
            if re.match(r"^\s{2,}-\s", line):
                out.append((no, s))
                continue
            if re.match(r"^-\s", s):
                active = False
    return out


def claim_kinds(rec: dict) -> list:
    return [c.get("kind") for c in rec.get("claims", []) if c.get("kind") != "envelope"]


def intent_view(rec: dict) -> dict:
    view = {k: rec.get(k) for k in INTENT_FIELDS if k != "claims_text"}
    view["claims_text"] = [c.get("text") for c in rec.get("claims", []) if c.get("kind") != "envelope"]
    return view


# --------------------------------------------------------------------------
# validation


def validate(log_path: Path) -> tuple[int, list]:
    errors = Errors()
    log = Path(os.path.realpath(log_path))
    if not log.is_file():
        return 2, [f"session-log: usage — log not found: {log_path}"]
    parts = log.parts
    if len(parts) < 5 or parts[-2] != "tests" or parts[-3] != "shared" or parts[-4] != "thoughts":
        return 2, [f"session-log: usage — log outside the contract layout <root>/thoughts/shared/tests/: {log_path}"]
    root = log.parents[3]
    logdir = log.parent
    text = log.read_text(encoding="utf-8")
    lines = content_lines(text)
    lines = [(no, strip_inline_html_comments(line)) for no, line in lines]

    # (a) headings
    headings = [(no, line.strip()) for no, line in lines if re.match(r"^#{1,2} ", line)]
    expected = list(HEADINGS)
    got = []
    for _, h in headings:
        if h.startswith("# TDD Session:"):
            got.append("# TDD Session:")
        else:
            got.append(h)
    if got != expected:
        missing = [h for h in expected if h not in got]
        extra = [h for h in got if h not in expected]
        dup = [h for h in set(got) if got.count(h) > 1]
        errors.add("a", "headings must be exactly " + " > ".join(expected) +
                   (f"; missing {missing}" if missing else "") +
                   (f"; extra {extra}" if extra else "") +
                   (f"; duplicated {dup}" if dup else "") +
                   (f"; got {got}" if not (missing or extra or dup) else ""))
    secs = sections(lines)
    h1_body = next((body for key, body in secs.items() if key.startswith("# TDD Session:")), [])

    # (b) header lines
    schema = header_value(h1_body, "Evidence schema")
    run_id = header_value(h1_body, "Evidence run")
    export_hdr = header_value(h1_body, "Evidence export")
    plan_hdr = header_value(h1_body, "Test Plan")
    if schema != "tdd/1":
        errors.add("b", f"`**Evidence schema**: tdd/1` header missing or wrong (got {schema!r})")
    if not run_id or not RUN_ID_RE.match(run_id):
        errors.add("b", f"`**Evidence run**` header missing or not a run id (got {run_id!r})")
    expected_export = f"receipts/{run_id}.json" if run_id else None
    if export_hdr is None:
        errors.add("b", "`**Evidence export**` header missing")
    elif expected_export and export_hdr != expected_export:
        errors.add("b", f"`**Evidence export**` must be exactly `{expected_export}` (got {export_hdr!r})")
    if not plan_hdr:
        errors.add("b", "`**Test Plan**` header missing")
    summary = find_section(secs, "## Summary")
    achieved_hdr = header_value([(n, l.strip().lstrip("- ").strip()) for n, l in summary], "Achieved phase")
    cycle_hdr = header_value([(n, l.strip().lstrip("- ").strip()) for n, l in summary], "Cycle state")
    if achieved_hdr not in ACHIEVED_MAP:
        errors.add("b", f"Summary `**Achieved phase**` missing or not one of {sorted(ACHIEVED_MAP)} (got {achieved_hdr!r})")
    if cycle_hdr not in ("continuing", "complete", "blocked"):
        errors.add("b", f"Summary `**Cycle state**` missing or not continuing|complete|blocked (got {cycle_hdr!r})")

    # (c) export and plan binding
    export = None
    if run_id and RUN_ID_RE.match(run_id):
        export_path = logdir / "receipts" / f"{run_id}.json"
        real = Path(os.path.realpath(export_path))
        if not export_path.exists() and not os.path.lexists(export_path):
            errors.add("c", f"export missing at {export_path.relative_to(root)}")
        elif os.path.islink(export_path) or real != export_path or not export_path.is_file():
            errors.add("c", f"export must be a regular file at exactly {export_path.relative_to(root)} (symlink or resolved elsewhere)")
        else:
            try:
                export = json.loads(export_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                errors.add("c", f"export is not valid JSON: {exc}")
                export = None
            if export is not None and (not isinstance(export, dict) or export.get("schema") != 1
                                       or not isinstance(export.get("run"), dict)
                                       or not isinstance(export.get("events"), list)
                                       or not isinstance(export.get("capsules"), list)):
                errors.add("c", "export does not have the schema-1 shape (run/events/capsules)")
                export = None
    if export is not None:
        run = export["run"]
        if run.get("id") != run_id:
            errors.add("c", f"export run.id {run.get('id')!r} != header run {run_id!r}")
        if plan_hdr:
            if run.get("plan_path") != plan_hdr:
                errors.add("c", f"export plan_path {run.get('plan_path')!r} != `**Test Plan**` {plan_hdr!r}")
            plan_file = root / plan_hdr
            if ".." in Path(plan_hdr).parts or Path(plan_hdr).is_absolute():
                errors.add("c", f"`**Test Plan**` must be repo-relative without '..' (got {plan_hdr!r})")
            elif not plan_file.is_file():
                errors.add("c", f"test plan not found at {plan_hdr}")
            elif sha256_file(plan_file) != run.get("plan_sha256"):
                errors.add("c", "test plan content does not match export plan_sha256")

    if export is None:
        return 1, list(errors)

    events = export["events"]
    capsules = export["capsules"]
    run = export["run"]
    records_through = export.get("records_through")

    # (d) ledger integrity
    ns = [r.get("n") for r in events]
    expected_ns = list(range(1, (records_through or 0) + 1))
    if not all(isinstance(n, int) for n in ns) or sorted(set(ns)) != expected_ns:
        errors.add("d", f"events n must be contiguous 1..{records_through}; got {sorted(set(ns))[:10]}…")
    pairs = pair_records(events)
    for n, slot in sorted((k, v) for k, v in pairs.items() if isinstance(k, int)):
        kinds = [r.get("kind") for r in events if r.get("n") == n]
        if "checkpoint" in slot:
            if len(kinds) != 1:
                errors.add("d", f"n={n}: a checkpoint n must hold exactly one record (got {kinds})")
            continue
        intents = [r for r in events if r.get("n") == n and r.get("kind") == "started"]
        terms = [r for r in events if r.get("n") == n and r.get("kind") in TERMINAL_KINDS]
        if len(intents) != 1 or len(terms) != 1:
            errors.add("d", f"n={n}: need exactly one intent and one terminal record (got {kinds})")
            continue
        intent, term = intents[0], terms[0]
        if events.index(intent) > events.index(term):
            errors.add("d", f"n={n}: terminal record precedes its intent")
        if intent.get("ref") != term.get("ref") or intent.get("run") != term.get("run"):
            errors.add("d", f"n={n}: intent/terminal ref or run mismatch")
        if intent_view(intent) != intent_view(term):
            diff = [k for k in INTENT_FIELDS if intent_view(intent).get(k) != intent_view(term).get(k)]
            errors.add("d", f"n={n}: terminal record does not repeat the intent verbatim ({', '.join(diff)})")
    derived = derive_index({k: v for k, v in run.items()
                            if k not in ("reports", "state", "achieved", "sealed_at", "phase", "records")}, events)
    for key in ("state", "achieved", "phase", "records", "reports"):
        if run.get(key) != derived.get(key):
            errors.add("d", f"export run.{key}={run.get(key)!r} disagrees with the ledger ({derived.get(key)!r})")
    # `cited` is derived ONLY from validated citation entries (collected in
    # check g / the Evidence cells); receipt tokens anywhere else are rejected.
    cited = set()
    citation_lines = set()
    # (receipt, section phase, lineno) for every validated citation — each must
    # resolve to an attempt of THAT phase (checked once by_receipt is known)
    phase_citations = []
    by_receipt = {r.get("receipt"): r for r in events if r.get("kind") in TERMINAL_KINDS + ("checkpoint",)}

    # (f) recomputation and checkpoint binding
    cap_by_path = {c.get("path"): c for c in capsules}
    for rec in events:
        if rec.get("kind") in TERMINAL_KINDS + ("checkpoint",):
            if receipt_of(rec) != rec.get("receipt"):
                errors.add("f", f"{rec.get('ref')}: receipt does not recompute")
        if rec.get("kind") == "checkpoint":
            if ledger_digest(events, rec.get("ledger_head", 0)) != rec.get("ledger_sha256"):
                errors.add("f", f"{rec.get('ref')}: ledger_sha256 does not recompute")
            cap = cap_by_path.get(rec.get("capsule_path"))
            if cap is None:
                errors.add("f", f"{rec.get('ref')}: capsule {rec.get('capsule_path')} missing from export")
            elif sha256_bytes((cap.get("text") or "").encode("utf-8")) != rec.get("capsule_sha256") \
                    or cap.get("sha256") != rec.get("capsule_sha256"):
                errors.add("f", f"{rec.get('ref')}: capsule text does not match capsule_sha256")

    # (g) commands-and-exits bullets
    phase_sections = {"red": find_section(secs, "## Red Phase"), "green": find_section(secs, "## Green Phase"),
                      "refactor": find_section(secs, "## Refactor Phase"), "final": find_section(secs, "## Final Verification")}
    baseline = find_section(secs, "## Baseline")
    # `**Test configuration**:` — exactly once, paths only (no command shapes)
    for no, line in baseline:
        if re.match(r"^-\s*\*\*Test command\(s\)\*\*", line.strip()):
            errors.add("g", f"line {no}: legacy `**Test command(s)**` field — record `**Test configuration**:` (paths only); commands are not transcribed")
    tc = field_lines(baseline, "Test configuration")
    if len(tc) != 1:
        errors.add("g", f"Baseline must carry exactly one `**Test configuration**:` line (found {len(tc)})")
    for no, val in tc:
        if not val:
            errors.add("g", f"line {no}: `**Test configuration**` is empty")
        elif not test_configuration_ok(val):
            errors.add("g", f"line {no}: `**Test configuration**` must list configuration file paths (path tokens only, e.g. `pyproject.toml`, `package.json`) or `Not applicable — <reason>`; commands, exits, and receipts are rejected (got {val[:60]!r})")
    # `**Baseline runs**:` — exactly once, every occurrence entry-shaped
    runs = field_lines(baseline, "Baseline runs")
    if len(runs) != 1:
        errors.add("g", f"Baseline must carry exactly one `**Baseline runs**:` line (found {len(runs)})")
    for no, body in runs:
        citation_lines.add(no)
        if not body:
            errors.add("g", f"line {no}: `**Baseline runs**` is empty")
        elif not entry_ok(body):
            errors.add("g", f"line {no}: `**Baseline runs**` must be `` `receipt <hex12>`: <summary> `` or `Not run — <reason>` (entire entry)")
        else:
            for rc in RECEIPT_RE.findall(body):
                cited.add(rc)
                phase_citations.append((rc, "baseline", no))
    active = False
    for bno, bline in baseline:
        bs = bline.strip()
        if re.match(r"^-\s*\*\*Baseline runs\*\*:", bs):
            active = True
            continue
        if active and re.match(r"^\s{2,}-\s", bline):
            b = re.sub(r"^-\s*", "", bs)
            citation_lines.add(bno)
            if not entry_ok(b):
                errors.add("g", f"line {bno}: baseline receipt bullet must be receipt-only or `Not run — <reason>` (entire entry)")
            else:
                for rc in RECEIPT_RE.findall(b):
                    cited.add(rc)
                    phase_citations.append((rc, "baseline", bno))
        elif active and re.match(r"^-\s", bs):
            active = False
    for name in ("red", "green", "refactor"):
        n_fields = len(field_lines(phase_sections[name], "Receipts"))
        if n_fields != 1:
            errors.add("g", f"{name} section must carry exactly one `**Receipts**:` field (found {n_fields}; the label is matched exactly)")
        for no, bullet in commands_bullets(phase_sections[name]):
            body = re.sub(r"^-\s*", "", bullet)
            citation_lines.add(no)
            if not entry_ok(body):
                errors.add("g", f"line {no}: receipt bullet must be receipt-only — `` `receipt <hex12>`: <salient result> `` "
                                f"or an entire `Not run — <reason>` / `Not applicable — <reason>` entry; argv and exits live in the export")
            else:
                for rc in RECEIPT_RE.findall(body):
                    cited.add(rc)
                    phase_citations.append((rc, name, no))
    for key in ("Focused suite", "Relevant surrounding suite"):
        found = field_lines(phase_sections["final"], key)
        if len(found) != 1:
            errors.add("g", f"Final Verification must carry exactly one `**{key}**:` line (found {len(found)})")
        for no, body in found:
            citation_lines.add(no)
            if not entry_ok(body):
                errors.add("g", f"line {no}: `**{key}**` must be `` `receipt <hex12>`: <summary> `` or an entire `Not run — <reason>` / `Not applicable — <reason>` entry")
            else:
                for rc in RECEIPT_RE.findall(body):
                    cited.add(rc)
                    phase_citations.append((rc, "final", no))
    # Evidence cells are citation locations too (validated in check j below)
    disp_body = find_section(secs, "## Case Dispositions")
    for no, line in disp_body:
        s_ = line.strip()
        if s_.startswith("|") and CASE_ROW_RE.match(s_):
            citation_lines.add(no)
            cells = [c.strip() for c in s_.strip("|").split("|")]
            if len(cells) == 4 and EVIDENCE_CELL_RE.match(cells[3]):
                cited.update(RECEIPT_RE.findall(cells[3]))
    # Receipt tokens anywhere outside a validated citation entry are rejected
    for no, line in lines:
        if no not in citation_lines and RECEIPT_RE.search(line):
            errors.add("g", f"line {no}: receipt token outside a citation field (Receipts bullets, Baseline runs, Final lines, Evidence cells) — transcriptions cannot hide in Deviations or prose")

    # A citation in a section must be an attempt of that section's phase
    for rc, phase, no in phase_citations:
        rec = by_receipt.get(rc)
        if rec is None:
            continue  # reported by (e)
        if rec.get("kind") == "checkpoint" or rec.get("phase") != phase:
            errors.add("g", f"line {no}: receipt {rc} is a {rec.get('kind')} record of phase {rec.get('phase')!r}, cited as {phase} evidence")

    # (d, tail) no citation may point beyond records_through; (e) receipts resolve
    for rc in sorted(cited):
        rec = by_receipt.get(rc)
        if rec and records_through is not None and rec.get("n", 0) > records_through:
            errors.add("d", f"receipt {rc} cites n={rec.get('n')} beyond records_through={records_through}")
    for rc in sorted(cited):
        if rc not in by_receipt:
            errors.add("e", f"receipt {rc} does not resolve to a terminal or checkpoint record")

    # (h) case completeness
    planned: list = []
    if plan_hdr and (root / plan_hdr).is_file() and ".." not in Path(plan_hdr).parts:
        plan_lines = content_lines((root / plan_hdr).read_text(encoding="utf-8"))
        for _, pl in plan_lines:
            m = CASE_ROW_RE.match(pl.strip())
            if m and m.group(1) not in planned:
                planned.append(m.group(1))
    rows = table_rows(find_section(secs, "## Case Dispositions"))
    disp_ids = [r[0] for r in rows if r]
    if not planned:
        errors.add("h", "test plan defines no `| U-xx |` / `| I-xx |` / `| E-xx |` case rows")
    if not rows:
        errors.add("h", "Case Dispositions table has no data rows")
    dup = sorted({i for i in disp_ids if disp_ids.count(i) > 1})
    if dup:
        errors.add("h", f"duplicate disposition rows for {dup}")
    missing = [c for c in planned if c not in disp_ids]
    extra = [c for c in disp_ids if c not in planned]
    if planned and rows and (missing or extra):
        errors.add("h", f"dispositions must cover exactly the planned cases; missing {missing}, unplanned {extra}")
    terminals = [r for r in events if r.get("kind") in TERMINAL_KINDS]
    ledger_cases = sorted({r.get("case") for r in terminals if r.get("phase") in ("red", "green", "refactor") and r.get("case")})
    unplanned_ledger = [c for c in ledger_cases if planned and c not in planned]
    if unplanned_ledger:
        errors.add("h", f"ledger has attempts for unplanned cases {unplanned_ledger}")
    for r in rows:
        if len(r) != 4:
            errors.add("h", f"disposition row {r[:1]} must have exactly 4 cells (Case ID | Layer | Disposition | Evidence); got {len(r)}")
            continue
        if not re.fullmatch(r"[UIE]-\d+", r[0]):
            errors.add("h", f"disposition Case ID {r[0]!r} is not U-/I-/E- shaped")
        if r[2] not in DISPOSITIONS:
            errors.add("h", f"{r[0]}: disposition {r[2]!r} not in {sorted(DISPOSITIONS)}")
        cell = r[3].strip()
        if r[2] in EVIDENCE_DISPOSITIONS:
            if not EVIDENCE_CELL_RE.match(cell):
                errors.add("j", f"{r[0]}: Evidence cell must be `receipt <hex12> — <salient assertion>` with no transcribed command/exit (got {cell[:60]!r})")
        elif not REASON_CELL_RE.match(cell):
            errors.add("h", f"{r[0]}: {r[2]} needs a plain reason in the Evidence cell (no receipt tokens, commands or exits)")
    for name in ("red", "green", "refactor"):
        bullets = [re.sub(r"^-\s*", "", b) for _, b in commands_bullets(phase_sections[name])]
        has_receipt = any(CITATION_RE.match(b) for b in bullets)
        # The skipped-phase alternative must be stated IN the Receipts bullets —
        # text elsewhere in the section (e.g. Deviations) does not count.
        marked_not_run = len(bullets) == 1 and bool(NOT_RUN_ENTRY_RE.match(bullets[0]))
        if not has_receipt and not marked_not_run:
            errors.add("h", f"{name} section has no receipt citations under `**Receipts**:` and is not a single `Not run — …` / `Not applicable — …` bullet")
        # The skipped-phase alternative is exclusive: a phase that cites receipts
        # cannot also claim it was not run.
        if has_receipt and any(NOT_RUN_ENTRY_RE.match(b) for b in bullets):
            errors.add("h", f"{name} section mixes receipt citations with `Not run — …` / `Not applicable — …` bullets; a skipped phase uses the not-run entry as its only bullet")

    # (i) coverage: every attempt of phases red/green/refactor/final is cited
    for rec in terminals:
        if rec.get("phase") in ("baseline", "red", "green", "refactor", "final") and rec.get("receipt") not in cited:
            errors.add("i", f"{rec.get('ref')} ({rec.get('phase')}/{rec.get('case') or '-'} {rec.get('outcome')}) is not cited in the log")

    # (j) disposition <-> receipt; (k) manual-as-green
    by_ref = {r.get("ref"): r for r in terminals}
    for r in rows:
        if len(r) < 4 or r[2] not in EVIDENCE_DISPOSITIONS:
            continue
        case, disp, evidence_cell = r[0], r[2], r[3]
        m = RECEIPT_RE.search(evidence_cell)
        if not m:
            errors.add("j", f"{case}: {disp} must cite a receipt in the Evidence cell")
            continue
        rec = by_receipt.get(m.group(1))
        if rec is None or rec.get("kind") == "checkpoint":
            errors.add("j", f"{case}: cited receipt {m.group(1)} is not a terminal record")
            continue
        kinds = claim_kinds(rec)
        standin = "stand-in" in evidence_cell
        if rec.get("case") != case:
            errors.add("j", f"{case}: receipt {m.group(1)} belongs to case {rec.get('case')!r}")
        if rec.get("outcome") != "PASS":
            errors.add("j", f"{case}: receipt {m.group(1)} outcome is {rec.get('outcome')}, need PASS")
        if kinds and all(k == "manual" for k in kinds) and disp == "Green":
            errors.add("k", f"{case}: Green cites a receipt whose only claims are manual")
        if disp == "valid Red":
            if rec.get("phase") != "red":
                errors.add("j", f"{case}: valid Red must cite a red receipt (got {rec.get('phase')})")
            if standin:
                if not ("exit_ne0" in kinds and "contains" in kinds):
                    errors.add("j", f"{case}: stand-in Red needs both `exit != 0` and a `contains` claim")
            elif "test_fail_with" not in kinds:
                errors.add("j", f"{case}: valid Red needs a `test … fail-with` claim (or mark the row stand-in)")
        elif disp == "Green":
            if rec.get("phase") != "green":
                errors.add("j", f"{case}: Green must cite a green receipt (got {rec.get('phase')})")
            if standin:
                if "exit_eq" not in kinds:
                    errors.add("j", f"{case}: stand-in Green needs an `exit == 0` claim")
            elif "test_pass" not in kinds and "exit_eq" not in kinds:
                errors.add("j", f"{case}: Green needs a `test … pass` (or `exit == 0`) claim")
            req = by_ref.get(rec.get("requires") or "")
            if req is None or req.get("phase") != "red" or req.get("outcome") != "PASS" \
                    or req.get("case") != case or req.get("n", 0) >= rec.get("n", 0):
                errors.add("j", f"{case}: Green receipt must `requires` an earlier PASS red receipt of the same case")
        elif disp == "refactored-green":
            if rec.get("phase") != "refactor":
                errors.add("j", f"{case}: refactored-green must cite a refactor receipt (got {rec.get('phase')})")
            chain_ok = False
            cur = rec
            seen = set()
            while cur is not None and cur.get("ref") not in seen:
                seen.add(cur.get("ref"))
                prev = by_ref.get(cur.get("requires") or "")
                if prev is None or prev.get("case") != case or prev.get("outcome") != "PASS" \
                        or prev.get("n", 0) >= cur.get("n", 0):
                    break
                if prev.get("phase") == "green":
                    chain_ok = True
                    break
                cur = prev if prev.get("phase") == "refactor" else None
            if not chain_ok:
                errors.add("j", f"{case}: refactored-green receipt must chain via `requires` to a PASS green receipt of the same case")

    # (l) phase machine
    last_cp: dict = {}
    last_attempt: dict = {}
    cp_phases = []
    for rec in events:
        if rec.get("kind") == "checkpoint":
            last_cp[rec.get("phase")] = rec.get("n", 0)
            cp_phases.append(rec.get("phase"))
        elif rec.get("kind") in TERMINAL_KINDS and rec.get("outcome") == "PASS":
            last_attempt[rec.get("phase")] = max(last_attempt.get(rec.get("phase"), 0), rec.get("n", 0))
    for ph, n in last_attempt.items():
        if last_cp.get(ph, -1) < n:
            errors.add("l", f"phase {ph} has PASS attempts (n={n}) newer than its last checkpoint ({last_cp.get(ph)})")
    ranks = [PHASE_RANK.get(p, -1) for p in cp_phases]
    if any(b < a for a, b in zip(ranks, ranks[1:])):
        errors.add("l", f"checkpoint phases are not non-decreasing: {cp_phases}")
    if "final" in cp_phases and events and events[-1].get("kind") != "checkpoint" or \
            ("final" in cp_phases and events and events[-1].get("phase") != "final"):
        errors.add("l", "checkpoint final is not the last record")
    if achieved_hdr in ACHIEVED_MAP:
        need = {"Red": "red", "Green": "green", "Refactored Green": "refactor"}.get(achieved_hdr)
        if need and need not in cp_phases:
            errors.add("l", f"Achieved phase {achieved_hdr} requires a checkpoint {need}")

    # (m) cycle state
    state = run.get("state")
    achieved = run.get("achieved")
    refactor_text = "\n".join(l for _, l in phase_sections["refactor"])
    if cycle_hdr == "continuing":
        if state != "open" or "final" in cp_phases:
            errors.add("m", "cycle state continuing requires an open run without checkpoint final")
        st = phase_state(events)
        want = STATE_TO_ACHIEVED_PHASE.get(st)
        if achieved_hdr in ACHIEVED_MAP and achieved_hdr != want:
            errors.add("m", f"continuing: Achieved phase {achieved_hdr!r} does not match ledger state {st!r}")
    elif cycle_hdr == "complete":
        if state != "sealed":
            errors.add("m", "cycle state complete requires a sealed run (checkpoint final)")
        if achieved not in ("green", "refactored-green"):
            errors.add("m", f"cycle state complete requires achieved green|refactored-green (got {achieved!r})")
        if achieved == "green" and not re.search(r"Not applicable — \S", refactor_text):
            errors.add("m", "complete at Green requires `## Refactor Phase` to read `Not applicable — <reason>`")
        if achieved_hdr in ACHIEVED_MAP and ACHIEVED_MAP[achieved_hdr] != achieved:
            errors.add("m", f"Achieved phase {achieved_hdr!r} != run.achieved {achieved!r}")
    elif cycle_hdr == "blocked":
        if state != "sealed" or achieved != "blocked":
            errors.add("m", "cycle state blocked requires a sealed run with achieved blocked")
        if achieved_hdr in ACHIEVED_MAP and achieved_hdr != "Blocked":
            errors.add("m", f"blocked: Achieved phase must be Blocked (got {achieved_hdr!r})")

    return (1 if errors else 0), list(errors)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: validate_session_log.py <log.md>", file=sys.stderr)
        return 2
    code, errors = validate(Path(argv[0]))
    for err in errors:
        print(err)
    if code == 0:
        print("session-log: OK")
    return code


if __name__ == "__main__":
    sys.exit(main())
