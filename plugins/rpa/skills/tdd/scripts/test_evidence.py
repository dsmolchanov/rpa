#!/usr/bin/env python3
"""Focused no-network tests for the TDD evidence kernel (EV-01 … EV-27).

Every test builds a throwaway git repository and drives evidence.py through
subprocess exactly as an agent would. Mirrors hooks/test_run_gate.py style.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence.py"
STUB = HERE / "fixtures" / "junit_stub.py"
sys.path.insert(0, str(HERE))
import evidence  # noqa: E402  (pure helpers only: receipt_of, ledger_digest, redact)

PY = sys.executable
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *GIT_ID, *args], cwd=root, capture_output=True, text=True, check=True)


class Repo:
    """A throwaway git repository with the files the TDD convention expects."""

    def __init__(self, root: Path):
        self.root = root
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        _git(root, "commit", "-q", "--allow-empty", "-m", "init")
        (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "src").mkdir()
        (root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        (root / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (root / "plan.md").write_text("# plan\n\n| U-01 | … |\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "files")

    # -- invocation helpers -------------------------------------------------
    def ev(self, *args: str, env: dict | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        e = os.environ.copy()
        e.pop("RPA_EVIDENCE_DIR", None)
        if env:
            e.update(env)
        return subprocess.run([PY, str(EV), *args], cwd=self.root, capture_output=True,
                              text=True, env=e, timeout=timeout, check=False)

    def begin(self, plan: str = "plan.md") -> str:
        res = self.ev("begin", "--plan", plan)
        assert res.returncode == 0, res.stderr
        return res.stdout.split()[0].split("=", 1)[1]

    @property
    def store(self) -> Path:
        return self.root / ".rpa" / "evidence"

    def run_dir(self, run_id: str) -> Path:
        return self.store / "runs" / run_id

    def events(self, run_id: str) -> list:
        path = self.run_dir(run_id) / "events.jsonl"
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def last_ref(self, run_id: str) -> str:
        return self.events(run_id)[-1]["ref"]

    def last_terminal(self, run_id: str) -> dict:
        return [r for r in self.events(run_id) if r["kind"] not in ("started", "checkpoint")][-1]

    def red(self, run_id: str | None = None, case: str = "U-01", outcome: str = "failure",
            message: str = "AssertionError: boom", extra: tuple = (), literal: str = "AssertionError"):
        args = ["run", "--phase", "red", "--case", case, "--because", "red",
                "--scope", "red_inputs=tests/*.py", "--scope", "plan=plan.md",
                "--report", "r.xml", "--expect", f'test sample.test_x fail-with "{literal}"', *extra,
                "--", PY, str(STUB), "--out={report}", "--case", "sample.test_x",
                "--outcome", outcome, "--message", message]
        if run_id:
            args[1:1] = ["--run", run_id]
        return self.ev(*args)

    def green(self, requires: str, case: str = "U-01", extra: tuple = (), cmd: list | None = None):
        cmd = cmd or [PY, str(STUB), "--out={report}", "--case", "sample.test_x", "--outcome", "pass"]
        args = ["run", "--phase", "green", "--case", case, "--because", "green", "--requires", requires,
                "--report", "r.xml", "--expect", "test sample.test_x pass", *extra, "--", *cmd]
        return self.ev(*args)

    def commit(self, msg: str = "c") -> None:
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "--allow-empty", "-m", msg)

    def porcelain(self) -> str:
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                              capture_output=True, text=True).stdout


class EvidenceKernelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ev-")
        self.repo = Repo(Path(os.path.realpath(self._tmp.name)))

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers -------------------------------------------------------------
    def baseline(self) -> str:
        run_id = self.repo.begin()
        res = self.repo.ev("checkpoint", "baseline")
        self.assertEqual(res.returncode, 0, res.stderr)
        return run_id

    def red_ok(self, run_id: str, case: str = "U-01") -> str:
        res = self.repo.red(case=case)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("outcome=PASS", res.stdout)
        return self.repo.last_ref(run_id)

    def red_cp(self, run_id: str, case: str = "U-01") -> str:
        """Red PASS followed by `checkpoint red` (Green is admitted only in state red)."""
        ref = self.red_ok(run_id, case)
        res = self.repo.ev("checkpoint", "red")
        self.assertEqual(res.returncode, 0, res.stderr)
        return ref

    # -- EV-01 / EV-02 / EV-19: JUnit semantics ------------------------------
    def test_ev01_wrong_cause_red_is_surprise(self):
        self.baseline()
        res = self.repo.red(outcome="error", message="ImportError: nope")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("outcome=SURPRISE", res.stdout)

    def test_ev02_right_cause_red_and_report_substitution(self):
        run_id = self.baseline()
        res = self.repo.red()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        term = self.repo.last_terminal(run_id)
        report = self.repo.run_dir(run_id) / "reports" / "r.xml"
        self.assertTrue(report.is_file())
        self.assertEqual(term["report_sha256"], evidence.sha256_file(report))
        self.assertEqual(term["report_path"], ".rpa/evidence/runs/%s/reports/r.xml" % run_id)
        # bare {report} element form (two-argument --out)
        res2 = self.repo.ev("run", "--phase", "red", "--case", "U-02", "--scope", "red_inputs=tests/*.py",
                            "--scope", "plan=plan.md", "--report", "r2.xml",
                            "--expect", 'test sample.test_y fail-with "AssertionError"',
                            "--", PY, str(STUB), "--out", "{report}", "--case", "sample.test_y",
                            "--outcome", "failure", "--message", "AssertionError: y")
        self.assertEqual(res2.returncode, 0, res2.stdout + res2.stderr)
        self.assertTrue((self.repo.run_dir(run_id) / "reports" / "r2.xml").is_file())

    def test_ev19_junit_semantics(self):
        self.baseline()
        # pass claim but runner exits 1 with a failure -> SURPRISE
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--report", "r.xml", "--expect", "test sample.test_x pass",
                           "--", PY, str(STUB), "--out={report}", "--case", "sample.test_x", "--outcome", "failure")
        self.assertEqual(res.returncode, 1)
        # skipped -> SURPRISE for pass
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--report", "r.xml", "--expect", "test sample.test_x pass",
                           "--", PY, "-c",
                           "import sys,subprocess;subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','skipped']);sys.exit(0)"
                           % (str(STUB), "{report}"))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        # fail-with but exit 0 -> SURPRISE
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--report", "r.xml",
                           "--expect", 'test sample.test_x fail-with "AssertionError"',
                           "--", PY, "-c",
                           "import sys,subprocess;subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','failure','--message','AssertionError']);sys.exit(0)"
                           % (str(STUB), "{report}"))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("SURPRISE", res.stdout)

    # -- EV-03 / EV-04 / EV-21 / EV-27: freshness and causal chain -----------
    def test_ev03_stale_by_scope_blocks_execution(self):
        run_id = self.baseline()
        red = self.red_cp(run_id)
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 2\n", encoding="utf-8")
        marker = self.repo.root / "marker"
        res = self.repo.green(red, cmd=[PY, "-c", f"open({str(marker)!r},'w').write('x')"],
                              extra=())
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn("outcome=STALE", res.stdout)
        self.assertFalse(marker.exists())

    def test_ev04_fresh_by_scope_runs(self):
        run_id = self.baseline()
        red = self.red_cp(run_id)
        (self.repo.root / "src" / "x.py").write_text("x = 2\n", encoding="utf-8")
        res = self.repo.green(red)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_ev21_causal_chain(self):
        run_id = self.baseline()
        red_u1 = self.red_cp(run_id, "U-01")
        # wrong case
        res = self.repo.green(red_u1, case="U-02")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(self.repo.events(run_id)), 4)  # nothing appended
        # SURPRISE red as target
        bad = self.repo.red(case="U-03", outcome="error")
        self.assertEqual(bad.returncode, 1)
        res = self.repo.green(self.repo.last_ref(run_id), case="U-03")
        self.assertEqual(res.returncode, 2)
        self.assertIn("need PASS", res.stderr)
        # later n
        res = self.repo.green(f"{run_id}#99", case="U-01")
        self.assertEqual(res.returncode, 2)
        # green record as target for green
        ok = self.repo.green(red_u1)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        green_ref = self.repo.last_ref(run_id)
        res = self.repo.green(green_ref)
        self.assertEqual(res.returncode, 2)
        self.assertIn("cannot require", res.stderr)
        # HEAD drift -> STALE
        self.repo.commit("drift")
        res = self.repo.green(red_u1)
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn("head changed", res.stdout)

    def test_ev27_post_run_drift_is_stale(self):
        run_id = self.baseline()
        red = self.red_cp(run_id)
        test_file = self.repo.root / "tests" / "test_x.py"
        res = self.repo.green(red, cmd=[PY, "-c",
                                        "import subprocess,sys;open(%r,'a').write('# touched\\n');"
                                        "sys.exit(subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','pass']).returncode)"
                                        % (str(test_file), str(STUB), "{report}")])
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn("drift during execution", res.stdout)
        # Red command that rewrites the plan -> STALE
        res = self.repo.ev("run", "--phase", "red", "--case", "U-02", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--expect", "exit == 0",
                           "--", PY, "-c", "open('plan.md','a').write('more\\n')")
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)

    # -- EV-05 / EV-06 / EV-07 / EV-20: argv safety and diff -----------------
    def test_ev05_argv_is_literal(self):
        self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0",
                           "--expect", 'stdout contains "a;b"',
                           "--", PY, "-c", "print('a;b')", ";", "echo pwned", "$(touch injected)")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertFalse((self.repo.root / "injected").exists())
        self.assertFalse((self.repo.root / "pwned").exists())

    def test_ev06_store_visibility_and_gitignore_noise(self):
        run_id = self.repo.begin()
        self.assertEqual(self.repo.porcelain(), "")
        self.assertEqual((self.repo.store / ".gitignore").read_text(), "*\n")
        self.assertFalse((self.repo.root / ".rpa" / ".gitignore").exists())
        self.repo.ev("checkpoint", "baseline")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff none",
                           "--", PY, "-c", "import os;os.makedirs('__pycache__',exist_ok=True);open('__pycache__/x.pyc','w').write('x')")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.repo.porcelain(), "")
        # foreign ignore file is never overwritten
        (self.repo.store / ".gitignore").write_text("custom\n")
        res = self.repo.ev("begin", "--plan", "plan.md")
        self.assertEqual(res.returncode, 2)
        self.assertEqual((self.repo.store / ".gitignore").read_text(), "custom\n")

    def test_ev07_diff_boundary(self):
        self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff within tests/**",
                           "--", PY, "-c", "open('src/a.py','w').write('1')")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff within src/**",
                           "--", PY, "-c", "open('src/a.py','w').write('2')")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_ev20_dirty_file_modified_again(self):
        self.baseline()
        f = self.repo.root / "tests" / "test_x.py"
        f.write_text("dirty\n")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff none",
                           "--", PY, "-c", "open('tests/test_x.py','a').write('more\\n')")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("SURPRISE", res.stdout)

    # -- EV-08 / EV-12 / EV-22: prediction gate and usage errors -------------
    def test_ev08_manual_claims(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", 'manual "UI renders"', "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("machine-checkable", res.stderr)
        res = self.repo.ev("run", "--phase", "baseline", "--expect", 'manual "UI renders"',
                           "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PENDING", res.stdout)
        self.assertIn("outcome=PASS", res.stdout)
        status = self.repo.ev("status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("pending manual: manual \"UI renders\"", status.stdout)

    def test_ev12_unparseable_or_missing_claims(self):
        run_id = self.baseline()
        before = len(self.repo.events(run_id))
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "works fine", "--", PY, "-c", "open('ran','w')")
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("run", "--phase", "baseline", "--", PY, "-c", "open('ran','w')")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(self.repo.events(run_id)), before)
        self.assertFalse((self.repo.root / "ran").exists())

    def test_ev22_mandatory_and_empty_scopes(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "plan=plan.md",
                           "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("red_inputs", res.stderr)
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=nonexistent/*.py",
                           "--scope", "plan=plan.md", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("matched no files", res.stderr)
        self.assertEqual(len(self.repo.events(run_id)), 1)

    # -- EV-09 / EV-15: ledger robustness and idempotent repair --------------
    def test_ev09_partial_line_tolerance(self):
        run_id = self.baseline()
        path = self.repo.run_dir(run_id) / "events.jsonl"
        with open(path, "ab") as fh:
            fh.write(b'{"ref": "tdd-x')
        status = self.repo.ev("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("ignored partial record", status.stdout)
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)
        recs = self.repo.events(run_id)
        self.assertEqual([r["n"] for r in recs], [1, 2, 2])
        self.assertTrue(path.read_bytes().endswith(b"\n"))

    def _dead_pid(self) -> int:
        proc = subprocess.Popen([PY, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_ev15_idempotent_repair(self):
        run_id = self.baseline()
        self.red_ok(run_id)
        recs = self.repo.events(run_id)
        intent = next(r for r in recs if r["kind"] == "started")
        # (a) dangling intent + dead lease
        n = max(r["n"] for r in recs) + 1
        dangling = dict(intent, n=n, ref=f"{run_id}#{n}")
        with open(self.repo.run_dir(run_id) / "events.jsonl", "a") as fh:
            fh.write(evidence.canonical_json(dangling) + "\n")
        (self.repo.store / "active.json").write_text(json.dumps({
            "run_id": run_id, "ref": dangling["ref"], "controller_pid": self._dead_pid(),
            "start_token": "abc", "started_at_utc": "x", "child_pid": None}))
        status = self.repo.ev("status")
        self.assertIn("open intents", status.stdout)
        self.assertIn("dead", status.stdout)
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)
        recs = self.repo.events(run_id)
        interrupted = [r for r in recs if r["kind"] == "interrupted"]
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0]["n"], n)
        self.assertEqual(interrupted[0]["recovered_by"]["command"], "run")
        self.assertFalse((self.repo.store / "active.json").exists())
        # (b) terminal present + lease left behind -> lease cleared, no new terminal
        count = len(recs)
        (self.repo.store / "active.json").write_text(json.dumps({
            "run_id": run_id, "ref": recs[-1]["ref"], "controller_pid": self._dead_pid(),
            "start_token": "abc", "started_at_utc": "x", "child_pid": None}))
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.repo.events(run_id)), count)
        self.assertFalse((self.repo.store / "active.json").exists())
        # (c) lease-less dangling intent, recovered by export (d)
        n2 = max(r["n"] for r in self.repo.events(run_id)) + 1
        dangling2 = dict(intent, n=n2, ref=f"{run_id}#{n2}")
        with open(self.repo.run_dir(run_id) / "events.jsonl", "a") as fh:
            fh.write(evidence.canonical_json(dangling2) + "\n")
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 0, res.stderr)
        recs = self.repo.events(run_id)
        self.assertEqual(recs[-1]["kind"], "interrupted")
        self.assertEqual(recs[-1]["recovered_by"]["command"], "export")
        # (e) repair twice changes nothing
        count = len(recs)
        self.repo.ev("export")
        self.assertEqual(len(self.repo.events(run_id)), count)

    # -- EV-10 / EV-11: determinism, export prefix rule, sanitisation --------
    def test_ev10_receipts_and_export_prefix_rule(self):
        run_id = self.baseline()
        self.red_ok(run_id)
        out = self.repo.root / "thoughts" / "shared" / "tests" / "receipts" / f"{run_id}.json"
        self.assertEqual(self.repo.ev("export").returncode, 0)
        first = out.read_bytes()
        self.assertEqual(self.repo.ev("export").returncode, 0)
        self.assertEqual(out.read_bytes(), first)
        data = json.loads(first)
        self.assertEqual(data["run"]["state"], "open")
        for rec in data["events"]:
            if rec["kind"] != "started":
                self.assertEqual(evidence.receipt_of(rec), rec["receipt"])
        # another run -> rewrite with old events as prefix
        self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true")
        self.assertEqual(self.repo.ev("export").returncode, 0)
        data2 = json.loads(out.read_text())
        self.assertEqual(data2["events"][:len(data["events"])], data["events"])
        self.assertGreater(len(data2["events"]), len(data["events"]))
        # hand edit -> refused, file intact
        data2["events"][1]["because"] = "tampered"
        out.write_text(json.dumps(data2))
        tampered = out.read_bytes()
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not a prefix", res.stderr)
        self.assertEqual(out.read_bytes(), tampered)

    def test_ev11_sanitised_before_persistence(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--because", "token=abc",
                           "--expect", "exit == 0",
                           "--", PY, "-c", "print('TOKEN=abc123')", "--password=hunter2", "--password", "hunter2")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        raw = (self.repo.run_dir(run_id) / "events.jsonl").read_text()
        self.assertNotIn("abc123", raw)
        self.assertNotIn("hunter2", raw)
        self.assertIn("[REDACTED]", raw)
        intent = [r for r in self.repo.events(run_id) if r["kind"] == "started"][-1]
        self.assertEqual(intent["argv"][-1], "[REDACTED]")
        self.assertNotIn("hunter2", json.dumps(intent))
        term = self.repo.last_terminal(run_id)
        self.assertEqual(term["stdout_sha256"], evidence.sha256_bytes(b"TOKEN=abc123\n"))
        self.assertEqual(evidence.receipt_of(term), term["receipt"])
        self.repo.ev("export")
        exported = (self.repo.root / "thoughts" / "shared" / "tests" / "receipts" / f"{run_id}.json").read_text()
        self.assertNotIn("abc123", exported)
        self.assertNotIn("hunter2", exported)

    # -- EV-13 / EV-18: report rules and containment -------------------------
    def test_ev13_report_rules(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "test x pass", "--", "true")
        self.assertEqual(res.returncode, 2)
        # ambiguous selector
        two = ("import sys;open(%r,'w').write('<testsuite><testcase classname=\"a\" name=\"t1\"/>"
               "<testcase classname=\"a\" name=\"t2\"/></testsuite>')")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "two.xml", "--expect", "test a.t pass",
                           "--", PY, "-c", two % "{report}")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("matched 2", res.stdout)
        # report not produced
        res = self.repo.ev("run", "--phase", "baseline", "--report", "none.xml", "--expect", "test a.t pass",
                           "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not produced by this run", res.stdout)
        # tracked file refused
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/x.py", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertEqual((self.repo.root / "src" / "x.py").read_text(), "x = 1\n")
        # existing path (with a separator), not run-owned -> refused, intact
        (self.repo.root / "src" / "notes.txt").write_text("keep")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/notes.txt", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not owned by this run", res.stderr)
        self.assertEqual((self.repo.root / "src" / "notes.txt").read_text(), "keep")
        # a bare name is run-owned scratch: a same-named repo file is never touched
        (self.repo.root / "notes.txt").write_text("keep")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "notes.txt", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.repo.root / "notes.txt").read_text(), "keep")
        self.assertEqual(len([r for r in self.repo.events(run_id) if r["kind"] == "started"]), 3)

    def test_ev18_containment(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--report", "../x.xml", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("export", "--out", "/tmp/x.json")
        self.assertEqual(res.returncode, 2)
        os.symlink("/tmp", self.repo.root / "link")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "path link/foo unchanged",
                           "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(self.repo.events(run_id)), 1)
        (self.repo.store / "current").write_text("../../evil\n")
        res = self.repo.ev("status")
        self.assertEqual(res.returncode, 2)
        (self.repo.store / "current").write_text(run_id + "\n")
        # RPA_EVIDENCE_DIR inside/at/above the repo -> refused
        for bad in (str(self.repo.root), str(self.repo.root.parent), str(self.repo.root / "sub")):
            res = self.repo.ev("begin", "--plan", "plan.md", env={"RPA_EVIDENCE_DIR": bad})
            self.assertEqual(res.returncode, 2, bad)
        with tempfile.TemporaryDirectory(prefix="ev-store-") as sibling:
            res = self.repo.ev("begin", "--plan", "plan.md", env={"RPA_EVIDENCE_DIR": sibling})
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((Path(sibling) / "current").is_file())

    # -- EV-14 / EV-24 / EV-26: lifecycle, checkpoints, phase machine -------
    def test_ev14_lifecycle(self):
        r1 = self.repo.begin()
        r2 = self.repo.begin()
        self.assertNotEqual(r1, r2)
        self.assertEqual((self.repo.store / "current").read_text().strip(), r2)
        res = self.repo.ev("begin", "--resume", r1)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.repo.store / "current").read_text().strip(), r1)
        self.repo.ev("checkpoint", "baseline")
        red = self.red_ok(r1)
        # "later session": resume then green with the earlier red
        self.repo.ev("begin", "--resume", r2)
        self.assertEqual(self.repo.ev("begin", "--resume", r1).returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        res = self.repo.green(red)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for bad in ("../../x", "tdd-2026", "not-a-run"):
            self.assertEqual(self.repo.ev("begin", "--resume", bad).returncode, 2, bad)
        # index rebuild: delete run.json, a repairing command rebuilds it identically
        index_path = self.repo.run_dir(r1) / "run.json"
        before = index_path.read_text()
        index_path.unlink()
        self.assertIn("index missing", self.repo.ev("status").stdout)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        self.assertEqual(index_path.read_text(), before)
        # seal then resume / run refused
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("begin", "--resume", r1).returncode, 2)
        res = self.repo.green(red)
        self.assertEqual(res.returncode, 2)
        self.assertIn("sealed", res.stderr)
        # plan sha differs -> resume refused
        (self.repo.root / "plan.md").write_text("changed\n")
        self.assertEqual(self.repo.ev("begin", "--resume", r2).returncode, 2)

    def test_ev24_checkpoints_and_capsule(self):
        run_id = self.repo.begin()
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # not admitted before baseline
        self.assertEqual(self.repo.ev("checkpoint", "baseline").returncode, 0)
        red = self.red_ok(run_id)
        self.assertEqual(self.repo.ev("checkpoint", "red", "--next", "go green",
                                      "--open", "token=secret-open").returncode, 0)
        green = self.repo.green(red)
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        res = self.repo.ev("checkpoint", "green")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # backwards
        # green without own scopes is Verified while red inputs fresh …
        status = self.repo.ev("status").stdout
        green_ref = [r for r in self.repo.events(run_id) if r["kind"] == "finished" and r["phase"] == "green"][-1]["ref"]
        verified = status.split("## Verified")[1].split("## Open")[0]
        self.assertIn(green_ref, verified)
        # … and demoted to Open after a red input changes
        (self.repo.root / "tests" / "test_x.py").write_text("changed\n")
        status = self.repo.ev("status").stdout
        open_sec = status.split("## Open")[1].split("## Blocked")[0]
        self.assertIn(green_ref, open_sec)
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n")
        # re-run red after checkpoint red is allowed and re-checkpointed (non-decreasing)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # backwards from green
        # capsule binding: ledger_sha256 / capsule_sha256 / receipt recompute
        recs = self.repo.events(run_id)
        for cp in (r for r in recs if r["kind"] == "checkpoint"):
            self.assertEqual(cp["ledger_sha256"], evidence.ledger_digest(recs, cp["ledger_head"]))
            snap = self.repo.run_dir(run_id) / "capsules" / cp["capsule_path"]
            self.assertEqual(evidence.sha256_bytes(snap.read_bytes()), cp["capsule_sha256"])
            self.assertEqual(evidence.receipt_of(cp), cp["receipt"])
            self.assertNotIn("secret-open", json.dumps(cp))
        # sections present in the snapshot
        text = (self.repo.run_dir(run_id) / "capsules" / "0003-red.md").read_text()
        for sec in ("## Verified", "## Open", "## Blocked", "## Not applicable", "## Next"):
            self.assertIn(sec, text)
        self.assertIn("- go green", text)
        # bounds with a long history
        long_lit = "L" * 900
        for i in range(22):
            self.repo.ev("run", "--phase", "green", "--case", f"U-{i:02d}", "--expect", f'stdout contains "{long_lit}"',
                         "--", PY, "-c", f"print('{long_lit}')")
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        cps = [r for r in self.repo.events(run_id) if r["kind"] == "checkpoint"]
        snap = (self.repo.run_dir(run_id) / "capsules" / cps[-1]["capsule_path"]).read_bytes()
        self.assertLessEqual(len(snap.splitlines()), 120)
        self.assertLessEqual(len(snap), 16 * 1024)
        self.assertIn(b"older]", snap)
        # orphan snapshot removed; current.md regenerated
        orphan = self.repo.run_dir(run_id) / "capsules" / "9999-red.md"
        orphan.write_text("orphan")
        current = self.repo.run_dir(run_id) / "capsules" / "current.md"
        current.unlink()
        self.assertIn("orphan snapshots", self.repo.ev("status").stdout)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        self.assertFalse(orphan.exists())
        self.assertTrue(current.is_file())
        # seal and export capsules ordered
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        data = json.loads((self.repo.root / "thoughts/shared/tests/receipts" / f"{run_id}.json").read_text())
        self.assertEqual([c["phase"] for c in data["capsules"]], ["baseline", "red", "green", "green", "final"])
        self.assertEqual(data["run"]["state"], "sealed")
        self.assertEqual(data["run"]["achieved"], "green")

    def test_ev26_phase_machine(self):
        run_id = self.repo.begin()
        res = self.repo.red()
        self.assertEqual(res.returncode, 2)
        self.assertIn("not admitted", res.stderr)
        self.repo.ev("checkpoint", "baseline")
        red = self.red_ok(run_id)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        # green admitted in state red
        self.assertEqual(self.repo.green(red).returncode, 0)
        # a red attempt newer than the last checkpoint red blocks checkpoint green
        self.red_ok(run_id, "U-02")
        res = self.repo.ev("checkpoint", "green")
        self.assertEqual(res.returncode, 2)
        self.assertIn("newer than their checkpoint", res.stderr)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        # red not admitted after checkpoint green
        res = self.repo.red(case="U-03")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 2)
        self.assertEqual(self.repo.ev("run", "--phase", "final", "--expect", "exit == 0", "--", "true").returncode, 2)

    # -- EV-16 / EV-17 / EV-25: execution bounds and lease -------------------
    def test_ev16_timeout_kills_process_group(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--timeout", "1", "--expect", "exit == 0",
                           "--", PY, "-c", "import subprocess,time;subprocess.Popen(['sleep','30']);time.sleep(30)")
        self.assertEqual(res.returncode, 4, res.stdout + res.stderr)
        self.assertIn("outcome=TIMEOUT", res.stdout)
        term = self.repo.last_terminal(run_id)
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.killpg(term["child_pid"], 0)

    def test_ev17_bounded_output(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", 'stdout contains "NEEDLE"',
                           "--", PY, "-c", "import sys;sys.stdout.write('NEEDLE'+'x'*(1<<20))")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        term = self.repo.last_terminal(run_id)
        self.assertLessEqual(len(term["stdout_tail"].encode()), 8192)
        self.assertEqual(term["stdout_bytes"], (1 << 20) + 6)
        self.assertEqual(term["stdout_sha256"], evidence.sha256_bytes(b"NEEDLE" + b"x" * (1 << 20)))

    def test_ev25_worktree_wide_lease_fails_closed(self):
        r1 = self.baseline()
        r2 = self.repo.begin()
        self.repo.ev("checkpoint", "baseline")
        sleeper = subprocess.Popen([PY, "-c", "import time;time.sleep(60)"])
        try:
            (self.repo.store / "active.json").write_text(json.dumps({
                "run_id": r1, "ref": f"{r1}#9", "controller_pid": sleeper.pid,
                "start_token": "abc", "started_at_utc": "x", "child_pid": None}))
            for args in (("run", "--run", r1, "--phase", "baseline", "--expect", "exit == 0", "--", "true"),
                         ("checkpoint", "--run", r1, "red"),
                         ("export", "--run", r1),
                         ("run", "--run", r2, "--phase", "baseline", "--expect", "exit == 0", "--", "true"),
                         ("checkpoint", "--run", r2, "red"),
                         ("export", "--run", r2)):
                res = self.repo.ev(*args)
                self.assertEqual(res.returncode, 2, (args, res.stdout, res.stderr))
                self.assertIn("execution in progress", res.stderr)
        finally:
            sleeper.kill()
            sleeper.wait()
        res = self.repo.ev("export", "--run", r2)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.repo.store / "active.json").exists())

    # -- EV-23: relocatable package ------------------------------------------
    def test_ev23_relocatable_package(self):
        with tempfile.TemporaryDirectory(prefix="ev-copy-") as tmp:
            copy = Path(tmp) / "tdd"
            shutil.copytree(HERE.parent, copy)
            ev_copy = copy / "scripts" / "evidence.py"
            res = subprocess.run([PY, str(ev_copy), "begin", "--plan", "plan.md"], cwd=self.repo.root,
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            res = subprocess.run([PY, str(ev_copy), "run", "--phase", "baseline", "--expect", "exit == 0", "--", "true"],
                                 cwd=self.repo.root, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
