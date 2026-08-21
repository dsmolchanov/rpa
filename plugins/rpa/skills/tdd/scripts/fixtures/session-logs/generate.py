#!/usr/bin/env python3
"""Regenerate the session-log validator fixtures.

Every fixture case is a mini repository root: <case>/thoughts/shared/tests/
holding the session log, the test plan it binds to, and receipts/<run-id>.json.
The `valid*` exports are produced by evidence.py itself in a throwaway git
repository (never hand-edited); every invalid case is derived from a valid
one by exactly one mutation, listed in MUTATIONS below.

Usage: generate.py [--out <dir>] [--docs-positive <root>]
  --out            fixture directory (default: this directory)
  --docs-positive  also write one valid layout under <root>/thoughts/shared/tests/
                   (the docs-validate positive fixture root)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
EV = SCRIPTS / "evidence.py"
STUB = HERE.parent / "junit_stub.py"
sys.path.insert(0, str(SCRIPTS))
import evidence  # noqa: E402

PY = sys.executable
DATE = "2026-08-21"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]

PLAN_TEMPLATE = """# {title} Test Plan

**Date**: {date}T00:00:00+00:00
**Source**: synthetic fixture for the session-log validator

## 1. Scope

Synthetic two-case plan. Not a real feature.

## 3. Red-Phase Test Specification

### Unit Tests

**Location**: `tests/test_x.py`

| ID | Behavior | Setup / input | Expected observable result | Dependencies / fixtures | Evidence claims |
|---|---|---|---|---|---|
| U-01 | sample.test_x fails for the missing behavior | stub | AssertionError | junit_stub | Red: test sample.test_x fail-with "AssertionError" · Green: test sample.test_x pass |
| U-02 | sample.test_y fails for the missing behavior | stub | AssertionError | junit_stub | Red: test sample.test_y fail-with "AssertionError" · Green: test sample.test_y pass |

### Integration Tests

Not applicable — synthetic fixture.

### End-to-End Tests

Not applicable — synthetic fixture.
"""


def sh(args, cwd, check=True, env=None):
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check and res.returncode != 0:
        raise SystemExit(f"command failed ({res.returncode}): {args}\n{res.stdout}\n{res.stderr}")
    return res


class Scenario:
    def __init__(self, slug: str):
        self.slug = slug
        self.tmp = tempfile.TemporaryDirectory(prefix=f"fx-{slug}-")
        self.root = Path(os.path.realpath(self.tmp.name))
        sh(["git", "init", "-q"], self.root)
        sh(["git", *GIT_ID, "commit", "-q", "--allow-empty", "-m", "init"], self.root)
        (self.root / "tests").mkdir()
        (self.root / "src").mkdir()
        (self.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n")
        (self.root / "src" / "x.py").write_text("x = 1\n")
        self.tests_dir = self.root / "thoughts" / "shared" / "tests"
        self.tests_dir.mkdir(parents=True)
        self.plan_rel = f"thoughts/shared/tests/{DATE}-TEST-{slug}.md"
        (self.root / self.plan_rel).write_text(PLAN_TEMPLATE.format(title=slug, date=DATE))
        sh(["git", "add", "-A"], self.root)
        sh(["git", *GIT_ID, "commit", "-q", "-m", "files"], self.root)
        self.head = sh(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        env = os.environ.copy()
        env.pop("RPA_EVIDENCE_DIR", None)
        self.env = env
        out = sh([PY, str(EV), "begin", "--plan", self.plan_rel], self.root, env=env).stdout
        self.run_id = out.split()[0].split("=", 1)[1]

    def ev(self, *args, ok=(0,)):
        res = sh([PY, str(EV), *args], self.root, check=False, env=self.env)
        if res.returncode not in ok:
            raise SystemExit(f"evidence {args} -> {res.returncode}\n{res.stdout}\n{res.stderr}")
        return res

    def ledger(self):
        path = self.root / ".rpa" / "evidence" / "runs" / self.run_id / "events.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def last(self):
        return self.ledger()[-1]

    def red(self, case, test):
        self.ev("run", "--phase", "red", "--case", case, "--because", f"red {case}",
                "--scope", "red_inputs=tests/*.py", "--scope", f"plan={self.plan_rel}",
                "--report", "r.xml", "--expect", f'test {test} fail-with "AssertionError"',
                "--", PY, str(STUB), "--out={report}", "--case", test, "--outcome", "failure",
                "--message", "AssertionError: missing behavior")
        return self.last()

    def green(self, case, test, requires, ok=(0,)):
        self.ev("run", "--phase", "green", "--case", case, "--because", f"green {case}",
                "--requires", requires, "--report", "r.xml", "--expect", f"test {test} pass",
                "--", PY, str(STUB), "--out={report}", "--case", test, "--outcome", "pass", ok=ok)
        return self.last()

    def export(self):
        self.ev("export")
        return json.loads((self.tests_dir / "receipts" / f"{self.run_id}.json").read_text())


def bullet(rec, summary):
    # Receipt-only: argv/exit live in the export, never in the log.
    return f"  - `receipt {rec['receipt']}`: {summary}"


def log_text(sc: Scenario, *, title, rows, red, green, refactor, final_focused, achieved, cycle,
             files_red="tests/test_x.py", files_green="src/x.py"):
    lines = [
        f"# TDD Session: {title}",
        "",
        f"**Date**: {DATE}T00:00:00+00:00",
        f"**Test Plan**: `{sc.plan_rel}`",
        "**Requested Phase**: `full`",
        f"**Repository State**: `master {sc.head[:12]}`",
        "**Evidence schema**: `tdd/1`",
        f"**Evidence run**: `{sc.run_id}`",
        f"**Evidence export**: `receipts/{sc.run_id}.json`",
        "",
        "## Baseline",
        "",
        "- **Pre-existing worktree changes**: None",
        "- **Relevant implementation state**: absent (synthetic fixture)",
        "- **Test command(s)**: `python3 junit_stub.py --out={report} --case <case> --outcome <outcome>`",
        "- **Baseline runs**: Not run — synthetic fixture",
        "- **Pre-existing relevant failures**: None observed",
        "",
        "## Case Dispositions",
        "",
        "| Case ID | Layer | Disposition | Evidence |",
        "|---|---|---|---|",
        *rows,
        "",
        "## Red Phase",
        "",
        f"- **Files changed**: {files_red}",
        "- **Receipts**:",
        *red,
        "- **Deviations**: None",
        "",
        "## Green Phase",
        "",
    ]
    if green:
        lines += [f"- **Files changed**: {files_green}", "- **Receipts**:", *green, "- **Deviations**: None"]
    else:
        lines += ["- **Files changed**: None", "- **Receipts**:",
                  "  - Not run — phase red requested", "- **Deviations**: Not run — phase red requested"]
    lines += ["", "## Refactor Phase", "", f"- **Refactorings applied**: {refactor}",
              "- **Receipts**:", f"  - {refactor}", "", "## Final Verification", "",
              f"- **Focused suite**: {final_focused}",
              "- **Relevant surrounding suite**: Not applicable — synthetic fixture",
              "- **Coverage policy**: Not applicable — no threshold defined",
              "- **Manual verification**: Not applicable — no manual cases",
              "", "## Summary", "",
              f"- **Achieved phase**: {achieved}",
              f"- **Cycle state**: `{cycle}`",
              f"- **Source files changed**: {files_green if green else 'None'}",
              f"- **Test files changed**: {files_red}",
              "- **Remaining blockers or follow-ups**: None", ""]
    return "\n".join(lines)


def write_case(out: Path, name: str, sc: Scenario, text: str, export: dict | None = None,
               extra_files: dict | None = None):
    case = out / name
    if case.exists():
        shutil.rmtree(case)
    tests = case / "thoughts" / "shared" / "tests"
    (tests / "receipts").mkdir(parents=True)
    (tests / Path(sc.plan_rel).name).write_text((sc.root / sc.plan_rel).read_text())
    (tests / f"{DATE}-TDD-SESSION-{name}.md").write_text(text)
    exp = export if export is not None else json.loads((sc.tests_dir / "receipts" / f"{sc.run_id}.json").read_text())
    (tests / "receipts" / f"{sc.run_id}.json").write_text(evidence.canonical_json(exp) + "\n")
    for rel, content in (extra_files or {}).items():
        p = tests / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return case


def build_valid(out: Path, name: str = "valid"):
    sc = Scenario(name)
    sc.ev("checkpoint", "baseline")
    r1 = sc.red("U-01", "sample.test_x")
    r2 = sc.red("U-02", "sample.test_y")
    sc.ev("checkpoint", "red", "--next", "implement x then y")
    test_file = sc.root / "tests" / "test_x.py"
    original = test_file.read_text()
    test_file.write_text(original + "# edited during green\n")
    stale = sc.green("U-01", "sample.test_x", r1["ref"], ok=(3,))
    test_file.write_text(original)
    g1 = sc.green("U-01", "sample.test_x", r1["ref"])
    g2 = sc.green("U-02", "sample.test_y", r2["ref"])
    sc.ev("run", "--phase", "final", "--because", "focused suite", "--expect", "exit == 0",
          "--expect", 'stdout contains "ok"', "--", PY, "-c", "print('ok')")
    f1 = sc.last()
    sc.ev("checkpoint", "green", "--next", "refactor not needed; seal")
    sc.ev("checkpoint", "final", "--achieved", "green", "--not-applicable", "refactor: green code is minimal")
    export = sc.export()
    rows = [f"| U-01 | unit | Green | receipt {g1['receipt']} — sample.test_x passes |",
            f"| U-02 | unit | Green | receipt {g2['receipt']} — sample.test_y passes |"]
    red = [bullet(r1, "AssertionError: missing behavior"), bullet(r2, "AssertionError: missing behavior")]
    green = [bullet(stale, "red inputs changed during Green; restored and re-ran"),
             bullet(g1, "1 passed"), bullet(g2, "1 passed")]
    text = log_text(sc, title=f"{name} fixture", rows=rows, red=red, green=green,
                    refactor="Not applicable — Green code is already minimal",
                    final_focused=f"`receipt {f1['receipt']}`: ok",
                    achieved="Green", cycle="complete")
    return sc, text, export, {"r1": r1, "r2": r2, "stale": stale, "g1": g1, "g2": g2, "f1": f1}


def build_continuing(out: Path, name: str = "valid-continuing", checkpoint_red=True, red_after_cp=False):
    sc = Scenario(name)
    sc.ev("checkpoint", "baseline")
    r1 = sc.red("U-01", "sample.test_x")
    if checkpoint_red and red_after_cp:
        sc.ev("checkpoint", "red")
        r2 = sc.red("U-02", "sample.test_y")
    else:
        r2 = sc.red("U-02", "sample.test_y")
        if checkpoint_red:
            sc.ev("checkpoint", "red", "--next", "implement x then y")
    export = sc.export()
    rows = [f"| U-01 | unit | valid Red | receipt {r1['receipt']} — AssertionError at the assertion |",
            f"| U-02 | unit | valid Red | receipt {r2['receipt']} — AssertionError at the assertion |"]
    red = [bullet(r1, "AssertionError: missing behavior"), bullet(r2, "AssertionError: missing behavior")]
    text = log_text(sc, title=f"{name} fixture", rows=rows, red=red, green=[],
                    refactor="Not run — phase red requested",
                    final_focused="Not run — phase red requested", achieved="Red", cycle="continuing")
    return sc, text, export, {"r1": r1, "r2": r2}


def recompute(rec: dict) -> dict:
    rec = dict(rec)
    rec["receipt"] = evidence.receipt_of(rec)
    return rec


def edit_pair(export: dict, ref: str, fn) -> tuple[dict, str, str]:
    """Apply fn to both records of `ref`; returns (export, old_receipt, new_receipt)."""
    old_receipt = new_receipt = None
    events = []
    for rec in export["events"]:
        if rec.get("ref") == ref:
            rec = dict(rec)
            fn(rec)
            if rec["kind"] != "started":
                old_receipt = rec["receipt"]
                rec = recompute(rec)
                new_receipt = rec["receipt"]
        events.append(rec)
    export = dict(export, events=events)
    return export, old_receipt, new_receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--docs-positive")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sc, text, export, refs = build_valid(out)
    write_case(out, "valid", sc, text, export)
    g1, r1, r2, stale, f1 = refs["g1"], refs["r1"], refs["r2"], refs["stale"], refs["f1"]

    # --- log-only mutations of valid -------------------------------------------
    def log_mut(name, fn):
        write_case(out, name, sc, fn(text), export)

    log_mut("missing-receipt", lambda t: t.replace(f"  - `receipt {g1['receipt']}`: ", "  - ", 1))
    log_mut("unresolvable-receipt", lambda t: t.replace(f"receipt {r1['receipt']}", "receipt deadbeef0000"))
    log_mut("heading-order", lambda t: t.replace("## Red Phase", "@@G@@").replace("## Green Phase", "## Red Phase").replace("@@G@@", "## Green Phase"))
    log_mut("nonpass-disposition", lambda t: t.replace(
        f"| U-01 | unit | Green | receipt {g1['receipt']}", f"| U-01 | unit | Green | receipt {stale['receipt']}"))
    log_mut("fenced-heading", lambda t: t.replace("## Refactor Phase\n", "```\n## Refactor Phase\nreceipt abcdefabcdef\n```\n"))
    log_mut("html-comment-heading", lambda t: t.replace(
        "## Refactor Phase\n", "<!-- ## Refactor Phase -->\n<div>\n## Refactor Phase\nreceipt abcdefabcdef\n</div>\n"))
    log_mut("uncited-attempt", lambda t: "\n".join(l for l in t.splitlines() if stale["receipt"] not in l) + "\n")
    # the STALE attempt's bullet is hidden inside a comment that OPENS inline
    log_mut("inline-comment-hidden", lambda t: "\n".join(
        (f"- **Deviations**: None <!--" if False else l) for l in t.splitlines()).replace(
        f"  - `receipt {stale['receipt']}`", f"  - visible prose <!--\n  - `receipt {stale['receipt']}`", 1).replace(
        f"  - `receipt {g1['receipt']}`", f"  -->\n  - `receipt {g1['receipt']}`", 1))
    log_mut("achieved-mismatch", lambda t: t.replace("- **Achieved phase**: Green", "- **Achieved phase**: Refactored Green"))
    log_mut("partial-cases", lambda t: "\n".join(l for l in t.splitlines() if not l.startswith("| U-02 |")) + "\n")
    log_mut("export-traversal", lambda t: t.replace(f"`receipts/{sc.run_id}.json`", f"`../receipts/{sc.run_id}.json`"))
    log_mut("export-absolute", lambda t: t.replace(f"`receipts/{sc.run_id}.json`", f"`/tmp/receipts/{sc.run_id}.json`"))

    hollow = log_text(sc, title="hollow fixture", rows=[], red=[], green=[],
                      refactor="Not applicable — nothing", final_focused="Not run — nothing", achieved="Green", cycle="complete")
    hollow = hollow.replace("  - Not run — phase red requested\n", "").replace("- **Deviations**: Not run — phase red requested", "- **Deviations**: None")
    write_case(out, "hollow", sc, hollow, export)

    # plan-mismatch: header names another, different plan file that exists
    other_plan = PLAN_TEMPLATE.format(title="other", date=DATE) + "\n<!-- different content -->\n"
    write_case(out, "plan-mismatch", sc, text.replace(sc.plan_rel, f"thoughts/shared/tests/{DATE}-TEST-other.md"), export,
               extra_files={f"{DATE}-TEST-other.md": other_plan})

    # export-symlink: the export path is a symlink to the real file elsewhere
    case = write_case(out, "export-symlink", sc, text, export)
    tests = case / "thoughts" / "shared" / "tests"
    real = tests / "receipts" / f"{sc.run_id}.json"
    moved = tests / f"{sc.run_id}.real.json"
    real.rename(moved)
    os.symlink(f"../{moved.name}", real)

    # --- export mutations of valid -----------------------------------------------
    def exp_mut(name, new_export, new_text=None):
        write_case(out, name, sc, new_text or text, new_export)

    e, old, new = edit_pair(export, g1["ref"], lambda r: r.update(claims=[
        {"text": 'manual "looks right"', "kind": "manual"} if r["kind"] == "started"
        else {"text": 'manual "looks right"', "kind": "manual", "outcome": "PENDING", "detail": "looks right"}]))
    exp_mut("manual-as-green", e, text.replace(old, new))

    e = dict(export, run=dict(export["run"], id="tdd-20260101-000000-00000000-000000"))
    exp_mut("run-mismatch", e)

    e, old, new = edit_pair(export, g1["ref"], lambda r: r.update(requires=r2["ref"]))
    exp_mut("broken-chain", e, text.replace(old, new))

    def tamper(rec):
        if rec["kind"] != "started":
            rec["exit"] = 7
    events = [dict(r) for r in export["events"]]
    for r in events:
        if r["ref"] == g1["ref"]:
            tamper(r)  # receipt NOT recomputed
    exp_mut("tampered-export", dict(export, events=events))

    events = [r for r in export["events"] if r["ref"] != f1["ref"]]
    exp_mut("trimmed-export", dict(export, events=events, run=dict(export["run"], records=len(events))))

    events = [r for r in export["events"] if not (r["ref"] == r1["ref"] and r["kind"] == "started")]
    exp_mut("intent-deleted", dict(export, events=events, run=dict(export["run"], records=len(events))))

    events = list(export["events"])
    dup = next(r for r in events if r["ref"] == r1["ref"] and r["kind"] != "started")
    events.insert(events.index(dup) + 1, dict(dup))
    exp_mut("duplicate-terminal", dict(export, events=events, run=dict(export["run"], records=len(events))))

    events = []
    for r in export["events"]:
        r = dict(r)
        if r["ref"] == r1["ref"] and r["kind"] != "started":
            r["argv"] = ["tampered-argv"]
            r = recompute(r)
        events.append(r)
    exp_mut("ref-mismatch", dict(export, events=events), text.replace(
        r1["receipt"], next(r["receipt"] for r in events if r["ref"] == r1["ref"] and r["kind"] != "started")))

    # record-after-final: an intent+terminal pair appended after checkpoint final
    last_n = export["records_through"]
    pair = [dict(r) for r in export["events"] if r["ref"] == f1["ref"]]
    for r in pair:
        r["n"] = last_n + 1
        r["ref"] = f"{sc.run_id}#{last_n + 1}"
    pair[1] = recompute(pair[1])
    events = list(export["events"]) + pair
    e = dict(export, events=events, records_through=last_n + 1, run=dict(export["run"], records=len(events)))
    exp_mut("record-after-final", e, text + f"\n<!-- {pair[1]['receipt']} -->\n" if False else text.replace(
        f"- **Remaining blockers or follow-ups**: None",
        f"- **Remaining blockers or follow-ups**: None (extra attempt `receipt {pair[1]['receipt']}`)"))

    # --- continuing-based cases ------------------------------------------------------
    sc2, text2, export2, refs2 = build_continuing(out)
    write_case(out, "valid-continuing", sc2, text2, export2)
    write_case(out, "unsealed-complete", sc2, text2.replace("- **Cycle state**: `continuing`", "- **Cycle state**: `complete`"), export2)
    r1b = refs2["r1"]
    e, old, new = edit_pair(export2, r1b["ref"], lambda r: r.update(claims=[
        {"text": "exit != 0", "kind": "exit_ne0"} if r["kind"] == "started"
        else {"text": "exit != 0", "kind": "exit_ne0", "outcome": "PASS", "detail": "exit=1"}]))
    write_case(out, "standin-exit-only", sc2,
               text2.replace(old, new).replace(f"receipt {new} — AssertionError at the assertion",
                                               f"receipt {new} — stand-in: non-zero exit"), e)

    sc3, text3, export3, _ = build_continuing(out, "missing-checkpoint", checkpoint_red=False)
    write_case(out, "missing-checkpoint", sc3, text3, export3)

    sc4, text4, export4, _ = build_continuing(out, "attempt-after-checkpoint", checkpoint_red=True, red_after_cp=True)
    write_case(out, "attempt-after-checkpoint", sc4, text4, export4)

    if args.docs_positive:
        root = Path(args.docs_positive)
        sc5, text5, export5, _ = build_valid(out, "docs-positive")
        tests5 = root / "thoughts" / "shared" / "tests"
        if tests5.exists():
            shutil.rmtree(tests5)
        with tempfile.TemporaryDirectory(prefix="fx-docs-") as tmp_out:
            tmp_case = write_case(Path(tmp_out), "docs-positive", sc5, text5, export5)
            # the contract file name AND the H1 both match: union de-duplication
            shutil.copytree(tmp_case / "thoughts" / "shared" / "tests", tests5)

    print(f"fixtures written under {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
