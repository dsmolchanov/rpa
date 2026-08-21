#!/usr/bin/env python3
"""Focused no-network tests for the TDD evidence kernel (EV-01 … EV-38).

Every test builds a throwaway git repository and drives evidence.py through
subprocess exactly as an agent would. Mirrors hooks/test_run_gate.py style.
"""

from __future__ import annotations

import json
import os
import shutil
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
import evidence  # noqa: E402  (pure helpers only: receipt_of, ledger_digest, sha256_*)

PY = sys.executable
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]
LONG = "L" * 900


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *GIT_ID, *args], cwd=root, capture_output=True, text=True, check=True)


def _stub_cmd(outcome: str, case: str = "sample.test_x", message: str = "AssertionError: boom") -> list:
    return [PY, str(STUB), "--out={report}", "--case", case, "--outcome", outcome, "--message", message]


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
    def ev(self, *args: str, env: dict | None = None, timeout: int = 120, because: bool = True):
        """Run evidence.py; `run` invocations get a default --because unless one is given."""
        args = list(args)
        if because and args and args[0] == "run" and "--because" not in args:
            args[1:1] = ["--because", "t"]
        e = os.environ.copy()
        e.pop("RPA_EVIDENCE_DIR", None)
        if env:
            e.update(env)
        return subprocess.run([PY, str(EV), *args], cwd=self.root, capture_output=True,
                              text=True, env=e, timeout=timeout, check=False)

    def popen(self, *args: str) -> subprocess.Popen:
        e = os.environ.copy()
        e.pop("RPA_EVIDENCE_DIR", None)
        return subprocess.Popen([PY, str(EV), *args], cwd=self.root, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=e)

    def begin(self, plan: str = "plan.md", env: dict | None = None) -> str:
        res = self.ev("begin", "--plan", plan, env=env)
        assert res.returncode == 0, res.stderr
        return res.stdout.split()[0].split("=", 1)[1]

    @property
    def store(self) -> Path:
        return self.root / ".rpa" / "evidence"

    def run_dir(self, run_id: str, store: Path | None = None) -> Path:
        return (store or self.store) / "runs" / run_id

    def events(self, run_id: str, store: Path | None = None) -> list:
        path = self.run_dir(run_id, store) / "events.jsonl"
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

    def red(self, case: str = "U-01", outcome: str = "failure", message: str = "AssertionError: boom",
            extra: tuple = (), literal: str = "AssertionError", cmd: list | None = None):
        return self.ev("run", "--phase", "red", "--case", case, "--because", "red",
                       "--scope", "red_inputs=tests/*.py", "--scope", "plan=plan.md",
                       "--report", "r.xml", "--expect", f'test sample.test_x fail-with "{literal}"', *extra,
                       "--", *(cmd or _stub_cmd(outcome, message=message)))

    def green(self, requires: str, case: str = "U-01", extra: tuple = (), cmd: list | None = None):
        return self.ev("run", "--phase", "green", "--case", case, "--because", "green",
                       "--requires", requires, "--report", "r.xml",
                       "--expect", "test sample.test_x pass", *extra, "--", *(cmd or _stub_cmd("pass")))

    def commit(self, msg: str = "c") -> None:
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "--allow-empty", "-m", msg)

    def porcelain(self) -> str:
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                              capture_output=True, text=True).stdout

    def write_lease(self, run_id: str, ref: str, controller_pid: int, child_pid=None, child_pid_file=None):
        (self.store / "active.json").write_text(json.dumps({
            "run_id": run_id, "ref": ref, "controller_pid": controller_pid, "lease_nonce": "abc",
            "started_at_utc": "x", "child_pid": child_pid, "child_pid_file": child_pid_file}))


def _dead_pid() -> int:
    proc = subprocess.Popen([PY, "-c", "pass"])
    proc.wait()
    return proc.pid


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


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
        run_id = self.baseline()
        red = self.red_cp(run_id)
        # pass claim but runner exits 1 with a failure -> SURPRISE
        res = self.repo.green(red, cmd=_stub_cmd("failure"))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        # skipped -> SURPRISE for pass
        res = self.repo.green(red, cmd=[PY, "-c",
                                        "import sys,subprocess;subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','skipped']);sys.exit(0)"
                                        % (str(STUB), "{report}")])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        # fail-with but exit 0 -> SURPRISE
        res = self.repo.red(cmd=[PY, "-c",
                                 "import sys,subprocess;subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','failure','--message','AssertionError']);sys.exit(0)"
                                 % (str(STUB), "{report}")])
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("SURPRISE", res.stdout)

    # -- EV-03 / EV-04 / EV-21 / EV-27 / EV-29: freshness and causal chain --
    def test_ev03_stale_by_scope_blocks_execution(self):
        run_id = self.baseline()
        red = self.red_cp(run_id)
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 2\n", encoding="utf-8")
        marker = self.repo.root / "marker"
        res = self.repo.green(red, cmd=[PY, "-c", f"open({str(marker)!r},'w').write('x')"])
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
        res = self.repo.green(red_u1, case="U-02")  # wrong case
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(self.repo.events(run_id)), 4)  # nothing appended
        bad = self.repo.red(case="U-03", outcome="error")  # SURPRISE red as target
        self.assertEqual(bad.returncode, 1)
        res = self.repo.green(self.repo.last_ref(run_id), case="U-03")
        self.assertEqual(res.returncode, 2)
        self.assertIn("need PASS", res.stderr)
        res = self.repo.green(f"{run_id}#99", case="U-01")  # later n
        self.assertEqual(res.returncode, 2)
        ok = self.repo.green(red_u1)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        green_ref = self.repo.last_ref(run_id)
        res = self.repo.green(green_ref)  # green record as target for green
        self.assertEqual(res.returncode, 2)
        self.assertIn("cannot require", res.stderr)
        self.repo.commit("drift")  # HEAD drift -> STALE
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
        res = self.repo.red(case="U-02", cmd=[PY, "-c",
                                               "import subprocess,sys;open('plan.md','a').write('more\\n');"
                                               "sys.exit(subprocess.run([sys.executable,%r,'--out=%s','--case','sample.test_x','--outcome','failure','--message','AssertionError']).returncode)"
                                               % (str(STUB), "{report}")])
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)

    def test_ev29_child_scope_cannot_erase_inherited_freshness(self):
        run_id = self.baseline()
        red = self.red_cp(run_id)
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 3\n", encoding="utf-8")
        # Same scope name AND same globs re-declared by the child: the inherited
        # digest must still be checked -> STALE, not PASS.
        res = self.repo.green(red, extra=("--scope", "red_inputs=tests/*.py"))
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertIn("red_inputs", res.stdout)
        # Restore, then a green that re-declares the scope with identical content passes
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        res = self.repo.green(red, extra=("--scope", "red_inputs=tests/*.py"))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        term = self.repo.last_terminal(run_id)
        self.assertIn("red_inputs", term["envelope"]["scopes"])
        # different globs under the same name keep BOTH entries
        res = self.repo.green(red, extra=("--scope", "red_inputs=tests/*.py,src/*.py"))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        term = self.repo.last_terminal(run_id)
        self.assertTrue(any(k.startswith("red_inputs@") for k in term["envelope"]["scopes"]))

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
        self.repo.begin()
        self.assertEqual(self.repo.porcelain(), "")
        self.assertEqual((self.repo.store / ".gitignore").read_text(), "*\n")
        self.assertFalse((self.repo.root / ".rpa" / ".gitignore").exists())
        self.repo.ev("checkpoint", "baseline")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff none",
                           "--", PY, "-c", "import os;os.makedirs('__pycache__',exist_ok=True);open('__pycache__/x.pyc','w').write('x')")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.repo.porcelain(), "")
        (self.repo.store / ".gitignore").write_text("custom\n")  # foreign ignore file is never overwritten
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
        (self.repo.root / "tests" / "test_x.py").write_text("dirty\n")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "diff none",
                           "--", PY, "-c", "open('tests/test_x.py','a').write('more\\n')")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("SURPRISE", res.stdout)

    # -- EV-08 / EV-12 / EV-22 / EV-28: prediction gate and usage errors -----
    def test_ev08_manual_claims(self):
        self.baseline()
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
                           "--report", "r.xml", "--expect", 'test x fail-with "A"', "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("red_inputs", res.stderr)
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--report", "r.xml", "--expect", 'test x fail-with "A"', "--", "true")
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=nonexistent/*.py",
                           "--scope", "plan=plan.md", "--report", "r.xml", "--expect", 'test x fail-with "A"', "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("matched no files", res.stderr)
        self.assertEqual(len(self.repo.events(run_id)), 1)

    def test_ev28_phase_aware_claims(self):
        run_id = self.baseline()
        # lone `exit != 0` is never Red
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--expect", "exit != 0", "--", "false")
        self.assertEqual(res.returncode, 2)
        self.assertIn("stand-in", res.stderr)
        # the stand-in pair is Red
        res = self.repo.ev("run", "--phase", "red", "--case", "U-01", "--scope", "red_inputs=tests/*.py",
                           "--scope", "plan=plan.md", "--expect", "exit != 0",
                           "--expect", 'stderr contains "AssertionError"',
                           "--", PY, "-c", "import sys;sys.stderr.write('AssertionError: x\\n');sys.exit(1)")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        red = self.repo.last_ref(run_id)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        # empty literals are refused
        for claim in ('stdout contains ""', 'test x fail-with ""', 'manual "  "'):
            res = self.repo.ev("run", "--phase", "baseline", "--expect", claim, "--expect", "exit == 0", "--", "true")
            self.assertEqual(res.returncode, 2, claim)
        # green without --requires / without a pass claim
        res = self.repo.ev("run", "--phase", "green", "--case", "U-01", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--requires", res.stderr)
        res = self.repo.ev("run", "--phase", "green", "--case", "U-01", "--requires", red,
                           "--expect", "diff none", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("exit == 0", res.stderr)
        res = self.repo.ev("run", "--phase", "green", "--case", "U-01", "--requires", red,
                           "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        # no --because, bad --workflow
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true", because=False)
        self.assertEqual(res.returncode, 2)
        self.assertIn("--because", res.stderr)
        res = self.repo.ev("run", "--phase", "baseline", "--workflow", "Bad Flow", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)

    # -- EV-09 / EV-15 / EV-33: ledger robustness and idempotent repair ------
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
        self.repo.write_lease(run_id, dangling["ref"], _dead_pid())
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
        self.repo.write_lease(run_id, recs[-1]["ref"], _dead_pid())
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

    def test_ev33_cross_run_repair_truncates_torn_ledger_first(self):
        r_a = self.baseline()
        r_b = self.repo.begin()
        self.repo.ev("checkpoint", "baseline")
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)
        recs_b = self.repo.events(r_b)
        intent = next(r for r in recs_b if r["kind"] == "started")
        n = max(r["n"] for r in recs_b) + 1
        dangling = dict(intent, n=n, ref=f"{r_b}#{n}")
        ledger_b = self.repo.run_dir(r_b) / "events.jsonl"
        with open(ledger_b, "a") as fh:
            fh.write(evidence.canonical_json(dangling) + "\n")
            fh.write('{"torn": tr')  # no newline: torn tail
        self.repo.write_lease(r_b, dangling["ref"], _dead_pid())
        # A command on run A must reconcile run B safely first.
        res = self.repo.ev("export", "--run", r_a)
        self.assertEqual(res.returncode, 0, res.stderr)
        raw = ledger_b.read_text()
        for line in raw.splitlines():
            json.loads(line)  # every line parses: torn bytes were truncated before the append
        recs_b = self.repo.events(r_b)
        self.assertEqual(recs_b[-1]["kind"], "interrupted")
        self.assertEqual(recs_b[-1]["n"], n)
        self.assertEqual(recs_b[-1]["recovered_by"]["command"], "export")
        self.assertFalse((self.repo.store / "active.json").exists())
        index_b = json.loads((self.repo.run_dir(r_b) / "run.json").read_text())
        self.assertEqual(index_b["records"], len(recs_b))

    # -- EV-10 / EV-11 / EV-30: determinism, sanitisation, export ------------
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
        self.repo.ev("run", "--phase", "baseline", "--expect", "exit == 0", "--", "true")
        self.assertEqual(self.repo.ev("export").returncode, 0)
        data2 = json.loads(out.read_text())
        self.assertEqual(data2["events"][:len(data["events"])], data["events"])
        self.assertGreater(len(data2["events"]), len(data["events"]))
        data2["events"][1]["because"] = "tampered"  # hand edit -> refused, file intact
        out.write_text(json.dumps(data2))
        tampered = out.read_bytes()
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not a prefix", res.stderr)
        self.assertEqual(out.read_bytes(), tampered)

    def test_ev11_sanitised_before_persistence_live(self):
        run_id = self.baseline()
        proc = self.repo.popen("run", "--phase", "baseline", "--because", "token=abc", "--expect", "exit == 0",
                               "--", PY, "-c", "import time;print('TOKEN=abc123',flush=True);time.sleep(3)",
                               "--password=hunter2", "--password", "hunter2")
        try:
            deadline = time.monotonic() + 10
            live = None
            while time.monotonic() < deadline:
                recs = self.repo.events(run_id)
                started = [r for r in recs if r["kind"] == "started" and r["n"] == 2]
                if started:
                    live = started[0]
                    break
                time.sleep(0.1)
            self.assertIsNotNone(live, "intent record was not written before the command finished")
            self.assertEqual(live["argv"][-1], "[REDACTED]")
            self.assertNotIn("hunter2", json.dumps(live))
            self.assertNotIn("abc", live["because"])
            self.assertTrue((self.repo.store / "active.json").is_file())
        finally:
            out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out + err)
        raw = (self.repo.run_dir(run_id) / "events.jsonl").read_text()
        self.assertNotIn("abc123", raw)
        self.assertNotIn("hunter2", raw)
        term = self.repo.last_terminal(run_id)
        self.assertEqual(term["stdout_sha256"], evidence.sha256_bytes(b"TOKEN=abc123\n"))
        self.assertEqual(evidence.receipt_of(term), term["receipt"])
        self.repo.ev("export")
        exported = (self.repo.root / "thoughts" / "shared" / "tests" / "receipts" / f"{run_id}.json").read_text()
        self.assertNotIn("abc123", exported)
        self.assertNotIn("hunter2", exported)

    def test_ev30_export_fails_closed(self):
        run_id = self.baseline()
        self.red_ok(run_id)
        out = self.repo.root / "thoughts" / "shared" / "tests" / "receipts" / f"{run_id}.json"
        out.parent.mkdir(parents=True)
        out.write_text("{}")  # foreign JSON is never treated as an empty prefix
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not an export", res.stderr)
        self.assertEqual(out.read_text(), "{}")
        out.unlink()
        os.symlink(self.repo.root / "src" / "x.py", out)  # symlink target is never written through
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertEqual((self.repo.root / "src" / "x.py").read_text(), "x = 1\n")
        out.unlink()
        self.assertEqual(self.repo.ev("export").returncode, 0)
        # missing or tampered capsule snapshot -> refuse
        snap = self.repo.run_dir(run_id) / "capsules" / "0001-baseline.md"
        original = snap.read_text()
        snap.write_text(original + "tampered\n")
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertIn("does not match", res.stderr)
        snap.unlink()
        res = self.repo.ev("export")
        self.assertEqual(res.returncode, 2)
        self.assertIn("missing", res.stderr)

    # -- EV-13 / EV-18: report rules and containment -------------------------
    def test_ev13_report_rules(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "test x pass", "--", "true")
        self.assertEqual(res.returncode, 2)
        two = ("import sys;open(%r,'w').write('<testsuite><testcase classname=\"a\" name=\"t1\"/>"
               "<testcase classname=\"a\" name=\"t2\"/></testsuite>')")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "two.xml", "--expect", "test a.t pass",
                           "--", PY, "-c", two % "{report}")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("matched 2", res.stdout)
        res = self.repo.ev("run", "--phase", "baseline", "--report", "none.xml", "--expect", "test a.t pass", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not produced by this run", res.stdout)
        # stale report deletion: a previously produced run-owned report must not satisfy a new run
        self.red_ok(run_id)
        owned = self.repo.run_dir(run_id) / "reports" / "r.xml"
        self.assertTrue(owned.is_file())
        res = self.repo.ev("run", "--phase", "baseline", "--report", "r.xml", "--expect", "test sample.test_x pass", "--", "true")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("not produced by this run", res.stdout)
        self.assertFalse(owned.exists())
        # a run-owned path swapped for a symlink is refused, target intact
        self.red_ok(run_id)
        owned.unlink()
        os.symlink(self.repo.root / "src" / "x.py", owned)
        res = self.repo.ev("run", "--phase", "baseline", "--report", "r.xml", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not a regular file", res.stderr)
        self.assertEqual((self.repo.root / "src" / "x.py").read_text(), "x = 1\n")
        owned.unlink()
        # tracked file refused
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/x.py", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertEqual((self.repo.root / "src" / "x.py").read_text(), "x = 1\n")
        # explicit path that exists and is not run-owned -> refused, intact
        (self.repo.root / "src" / "notes.txt").write_text("keep")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/notes.txt", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not owned by this run", res.stderr)
        self.assertEqual((self.repo.root / "src" / "notes.txt").read_text(), "keep")
        # a missing report never confers ownership: a later user file at that path is refused
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/out.xml", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIsNone(self.repo.last_terminal(run_id)["report_sha256"])
        (self.repo.root / "src" / "out.xml").write_text("user data")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "src/out.xml", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        self.assertEqual((self.repo.root / "src" / "out.xml").read_text(), "user data")
        # a bare name is run-owned scratch: a same-named repo file is never touched
        (self.repo.root / "notes.txt").write_text("keep")
        res = self.repo.ev("run", "--phase", "baseline", "--report", "notes.txt", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.repo.root / "notes.txt").read_text(), "keep")

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
        self.repo.ev("begin", "--resume", r2)  # "later session"
        self.assertEqual(self.repo.ev("begin", "--resume", r1).returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        res = self.repo.green(red)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for bad in ("../../x", "tdd-2026", "not-a-run"):
            self.assertEqual(self.repo.ev("begin", "--resume", bad).returncode, 2, bad)
        index_path = self.repo.run_dir(r1) / "run.json"  # derived index rebuilds identically
        before = index_path.read_text()
        index_path.unlink()
        self.assertIn("index missing", self.repo.ev("status").stdout)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        self.assertEqual(index_path.read_text(), before)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("begin", "--resume", r1).returncode, 2)
        res = self.repo.green(red)
        self.assertEqual(res.returncode, 2)
        self.assertIn("sealed", res.stderr)
        (self.repo.root / "plan.md").write_text("changed\n")
        self.assertEqual(self.repo.ev("begin", "--resume", r2).returncode, 2)

    def test_ev24_checkpoints_and_capsule(self):
        run_id = self.repo.begin()
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # not admitted before baseline
        self.assertEqual(self.repo.ev("checkpoint", "baseline").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # admitted, but no PASS red yet
        red = self.red_ok(run_id)
        self.assertEqual(self.repo.ev("checkpoint", "red", "--next", "go green",
                                      "--open", "token=secret-open").returncode, 0)
        snap_red = (self.repo.run_dir(run_id) / "capsules" / "0003-red.md").read_text()
        self.assertIn("- state: red", snap_red)  # capsule describes the state AFTER the checkpoint
        green = self.repo.green(red)
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 2)  # backwards
        status = self.repo.ev("status").stdout
        green_ref = [r for r in self.repo.events(run_id) if r["kind"] == "finished" and r["phase"] == "green"][-1]["ref"]
        self.assertIn(green_ref, status.split("## Verified")[1].split("## Open")[0])
        (self.repo.root / "tests" / "test_x.py").write_text("changed\n")  # demoted after a red input changes
        status = self.repo.ev("status").stdout
        self.assertIn(green_ref, status.split("## Open")[1].split("## Blocked")[0])
        (self.repo.root / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n")
        recs = self.repo.events(run_id)
        for cp in (r for r in recs if r["kind"] == "checkpoint"):
            self.assertEqual(cp["ledger_sha256"], evidence.ledger_digest(recs, cp["ledger_head"]))
            snap = self.repo.run_dir(run_id) / "capsules" / cp["capsule_path"]
            self.assertEqual(evidence.sha256_bytes(snap.read_bytes()), cp["capsule_sha256"])
            self.assertEqual(evidence.receipt_of(cp), cp["receipt"])
            self.assertNotIn("secret-open", json.dumps(cp))
        for sec in ("## Verified", "## Open", "## Blocked", "## Not applicable", "## Next"):
            self.assertIn(sec, snap_red)
        self.assertIn("- go green", snap_red)
        # bounds with a long history (final-phase runs are admitted in state green)
        for i in range(4):
            res = self.repo.ev("run", "--phase", "final", "--expect", f'stdout contains "{LONG}"',
                               "--", PY, "-c", f"print('{LONG}')")
            self.assertEqual(res.returncode, 0, res.stderr)
        many_open = [a for i in range(130) for a in ("--open", f"open item {i} " + "o" * 90)]
        self.assertEqual(self.repo.ev("checkpoint", "green", *many_open).returncode, 0)
        cps = [r for r in self.repo.events(run_id) if r["kind"] == "checkpoint"]
        snap = (self.repo.run_dir(run_id) / "capsules" / cps[-1]["capsule_path"]).read_bytes()
        self.assertLessEqual(len(snap.splitlines()), 120)
        self.assertLessEqual(len(snap), 16 * 1024)
        self.assertIn(b"older]", snap)
        # a single oversized item cannot blow the bound
        self.assertEqual(self.repo.ev("checkpoint", "green", "--open", "X" * 20000).returncode, 0)
        cps = [r for r in self.repo.events(run_id) if r["kind"] == "checkpoint"]
        snap = (self.repo.run_dir(run_id) / "capsules" / cps[-1]["capsule_path"]).read_bytes()
        self.assertLessEqual(len(snap), 16 * 1024)
        # orphan snapshot removed; current.md regenerated
        orphan = self.repo.run_dir(run_id) / "capsules" / "9999-red.md"
        orphan.write_text("orphan")
        current = self.repo.run_dir(run_id) / "capsules" / "current.md"
        current.unlink()
        self.assertIn("orphan snapshots", self.repo.ev("status").stdout)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        self.assertFalse(orphan.exists())
        self.assertTrue(current.is_file())
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("export").returncode, 0)
        data = json.loads((self.repo.root / "thoughts/shared/tests/receipts" / f"{run_id}.json").read_text())
        self.assertEqual([c["phase"] for c in data["capsules"]], ["baseline", "red", "green", "green", "green", "final"])
        self.assertEqual(data["run"]["state"], "sealed")
        self.assertEqual(data["run"]["achieved"], "green")

    def test_ev26_phase_machine(self):
        run_id = self.repo.begin()
        res = self.repo.red()
        self.assertEqual(res.returncode, 2)
        self.assertIn("not admitted", res.stderr)
        self.repo.ev("checkpoint", "baseline")
        res = self.repo.ev("run", "--phase", "final", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)  # final runs not admitted before red
        red = self.red_ok(run_id)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        res = self.repo.ev("run", "--phase", "final", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 0, res.stderr)  # final runs admitted in state red
        self.assertEqual(self.repo.green(red).returncode, 0)
        self.red_ok(run_id, "U-02")  # a red attempt newer than the last checkpoint red blocks checkpoint green
        res = self.repo.ev("checkpoint", "green")
        self.assertEqual(res.returncode, 2)
        self.assertIn("newer than their checkpoint", res.stderr)
        self.assertEqual(self.repo.ev("checkpoint", "red").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 0)
        res = self.repo.red(case="U-03")  # red not admitted after checkpoint green
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("checkpoint", "final", "--achieved", "refactored-green")  # state green < refactor
        self.assertEqual(res.returncode, 2)
        self.assertIn("requires state", res.stderr)
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "green").returncode, 0)
        self.assertEqual(self.repo.ev("checkpoint", "green").returncode, 2)
        self.assertEqual(self.repo.ev("run", "--phase", "final", "--expect", "exit == 0", "--", "true").returncode, 2)
        # blocked may seal from baseline; evidence-less achievements cannot
        r2 = self.repo.begin()
        self.repo.ev("checkpoint", "baseline")
        res = self.repo.ev("checkpoint", "final", "--achieved", "red")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(self.repo.ev("checkpoint", "final", "--achieved", "blocked").returncode, 0)
        self.assertEqual(json.loads((self.repo.run_dir(r2) / "run.json").read_text())["achieved"], "blocked")

    # -- EV-16 / EV-17 / EV-25 / EV-31 / EV-32 / EV-34: execution & bounds ---
    def test_ev16_timeout_kills_process_group(self):
        run_id = self.baseline()
        t0 = time.monotonic()
        res = self.repo.ev("run", "--phase", "baseline", "--timeout", "1", "--expect", "exit == 0",
                           "--", PY, "-c", "import subprocess,time;subprocess.Popen(['sleep','30']);time.sleep(30)")
        self.assertEqual(res.returncode, 4, res.stdout + res.stderr)
        self.assertIn("outcome=TIMEOUT", res.stdout)
        self.assertLess(time.monotonic() - t0, 20)
        term = self.repo.last_terminal(run_id)
        time.sleep(0.5)
        self.assertFalse(evidence._group_alive(term["child_pid"]), "process group still has live members")

    def test_ev31_descendants_cannot_outlive_or_hang(self):
        run_id = self.baseline()
        # leader exits immediately; a descendant keeps stdout open
        t0 = time.monotonic()
        res = self.repo.ev("run", "--phase", "baseline", "--timeout", "3", "--expect", "exit == 0",
                           "--", PY, "-c", "import subprocess;subprocess.Popen(['sleep','60'])")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertLess(time.monotonic() - t0, 15)
        term = self.repo.last_terminal(run_id)
        self.assertTrue(term["stragglers_terminated"])
        time.sleep(0.5)
        self.assertFalse(evidence._group_alive(term["child_pid"]), "process group still has live members")
        # controller death between Popen and lease rewrite: the pid file tracks the child
        sleeper = subprocess.Popen([PY, "-c", "import time;time.sleep(60)"], start_new_session=True)
        try:
            recs = self.repo.events(run_id)
            intent = next(r for r in recs if r["kind"] == "started")
            n = max(r["n"] for r in recs) + 1
            dangling = dict(intent, n=n, ref=f"{run_id}#{n}")
            with open(self.repo.run_dir(run_id) / "events.jsonl", "a") as fh:
                fh.write(evidence.canonical_json(dangling) + "\n")
            pid_file = self.repo.run_dir(run_id) / "child.pid"
            pid_file.write_text(str(sleeper.pid))
            self.repo.write_lease(run_id, dangling["ref"], _dead_pid(), child_pid=None, child_pid_file=str(pid_file))
            res = self.repo.ev("export")
            self.assertEqual(res.returncode, 0, res.stderr)
            try:
                sleeper.wait(timeout=5)  # killed by repair (reaped here)
            except subprocess.TimeoutExpired:
                self.fail("untracked mutator survived repair")
            self.assertEqual(self.repo.events(run_id)[-1]["kind"], "interrupted")
        finally:
            with contextlib_suppress():
                sleeper.kill()
                sleeper.wait()

    def test_ev17_bounded_output(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", 'stdout contains "NEEDLE"',
                           "--", PY, "-c", "import sys;sys.stdout.write('NEEDLE'+'x'*(1<<20))")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        term = self.repo.last_terminal(run_id)
        self.assertLessEqual(len(term["stdout_tail"].encode()), 8192)
        self.assertEqual(term["stdout_bytes"], (1 << 20) + 6)
        self.assertEqual(term["stdout_sha256"], evidence.sha256_bytes(b"NEEDLE" + b"x" * (1 << 20)))

    def test_ev34_bounds_are_validated(self):
        self.baseline()
        for value in ("0", "-1", "100000"):
            res = self.repo.ev("run", "--phase", "baseline", "--tail-bytes", value, "--expect", "exit == 0", "--", "true")
            self.assertEqual(res.returncode, 2, value)
            self.assertIn("--tail-bytes", res.stderr)
        res = self.repo.ev("run", "--phase", "baseline", "--timeout", "0", "--expect", "exit == 0", "--", "true")
        self.assertEqual(res.returncode, 2)
        res = self.repo.ev("run", "--phase", "baseline", "--tail-bytes", "16", "--expect", "exit == 0",
                           "--", PY, "-c", "print('y'*1000)")
        self.assertEqual(res.returncode, 0, res.stderr)
        run_id = (self.repo.store / "current").read_text().strip()
        self.assertLessEqual(len(self.repo.last_terminal(run_id)["stdout_tail"].encode()), 16)

    def test_ev25_worktree_wide_lease_fails_closed(self):
        r1 = self.baseline()
        r2 = self.repo.begin()
        self.repo.ev("checkpoint", "baseline")
        sleeper = subprocess.Popen([PY, "-c", "import time;time.sleep(60)"])
        try:
            # (b) pre-Popen shape: controller alive, child_pid absent -> live
            self.repo.write_lease(r1, f"{r1}#9", sleeper.pid, child_pid=None)
            for args in (("run", "--run", r1, "--phase", "baseline", "--expect", "exit == 0", "--", "true"),
                         ("checkpoint", "--run", r1, "red"),
                         ("export", "--run", r1),
                         ("run", "--run", r2, "--phase", "baseline", "--expect", "exit == 0", "--", "true"),
                         ("checkpoint", "--run", r2, "red"),
                         ("export", "--run", r2)):
                res = self.repo.ev(*args)
                self.assertEqual(res.returncode, 2, (args, res.stdout, res.stderr))
                self.assertIn(f"execution in progress: {r1}#9", res.stderr)
        finally:
            sleeper.kill()
            sleeper.wait()
        res = self.repo.ev("export", "--run", r2)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((self.repo.store / "active.json").exists())

    def test_ev32_store_override_shares_the_worktree_lease(self):
        with tempfile.TemporaryDirectory(prefix="ev-store-a-") as store_a, \
                tempfile.TemporaryDirectory(prefix="ev-store-b-") as store_b:
            r_a = self.repo.begin(env={"RPA_EVIDENCE_DIR": store_a})
            r_b = self.repo.begin(env={"RPA_EVIDENCE_DIR": store_b})
            # lease lives in the canonical coordination root inside the worktree
            self.assertTrue((self.repo.store / "lock").exists())
            sleeper = subprocess.Popen([PY, "-c", "import time;time.sleep(60)"])
            try:
                self.repo.write_lease(r_a, f"{r_a}#1", sleeper.pid)
                res = self.repo.ev("run", "--run", r_b, "--phase", "baseline", "--expect", "exit == 0", "--", "true",
                                   env={"RPA_EVIDENCE_DIR": store_b})
                self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
                self.assertIn("execution in progress", res.stderr)
                res = self.repo.ev("checkpoint", "--run", r_a, "baseline", env={"RPA_EVIDENCE_DIR": store_a})
                self.assertEqual(res.returncode, 2)
            finally:
                sleeper.kill()
                sleeper.wait()
            res = self.repo.ev("checkpoint", "--run", r_b, "baseline", env={"RPA_EVIDENCE_DIR": store_b})
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((Path(store_b) / "runs" / r_b / "events.jsonl").is_file())

    # -- EV-35 … EV-38: Codex review round (PR #17) ---------------------------
    def test_ev35_exec_failure_detected_independently_of_tail(self):
        run_id = self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--tail-bytes", "1", "--expect", "exit == 127",
                           "--", "does-not-exist-command-xyz")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("could not start", res.stdout)
        term = self.repo.last_terminal(run_id)
        self.assertEqual(term["kind"], "error")
        self.assertEqual(term["outcome"], "ERROR")
        self.assertNotIn("hunter", json.dumps(term))

    def test_ev36_symlinked_coordination_root_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="ev-foreign-") as foreign:
            # .rpa itself is a pre-planted symlink
            os.symlink(foreign, self.repo.root / ".rpa")
            res = self.repo.ev("begin", "--plan", "plan.md")
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn("symlink", res.stderr)
            self.assertEqual(os.listdir(foreign), [])
            os.unlink(self.repo.root / ".rpa")
            # .rpa/evidence is a pre-planted symlink
            (self.repo.root / ".rpa").mkdir()
            os.symlink(foreign, self.repo.root / ".rpa" / "evidence")
            res = self.repo.ev("begin", "--plan", "plan.md")
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertEqual(os.listdir(foreign), [])

    def test_ev37_path_claim_never_certifies_a_symlink(self):
        self.baseline()
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "path link created",
                           "--", PY, "-c", "import os;os.symlink('/etc/passwd','link')")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("symlink", res.stdout)
        res = self.repo.ev("run", "--phase", "baseline", "--expect", "path src/new.txt created",
                           "--", PY, "-c", "open('src/new.txt','w').write('x')")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_ev38_report_ancestors_rechecked_after_execution(self):
        run_id = self.baseline()
        reports = self.repo.run_dir(run_id) / "reports"
        with tempfile.TemporaryDirectory(prefix="ev-rep-") as outside:
            swap = ("import os,shutil,subprocess,sys;shutil.rmtree(%r);os.symlink(%r,%r);"
                    "sys.exit(subprocess.run([sys.executable,%r,'--out=%s','--case','sample.x','--outcome','pass']).returncode)"
                    % (str(reports), outside, str(reports), str(STUB), "{report}"))
            res = self.repo.ev("run", "--phase", "baseline", "--report", "r.xml", "--expect", "test sample.x pass",
                               "--", PY, "-c", swap)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn("rejected after execution", res.stdout)
            os.unlink(reports)
            reports.mkdir()

    # -- EV-23: relocatable package ------------------------------------------
    def test_ev23_relocatable_package(self):
        with tempfile.TemporaryDirectory(prefix="ev-copy-") as tmp:
            copy = Path(tmp) / "tdd"
            shutil.copytree(HERE.parent, copy)
            ev_copy = copy / "scripts" / "evidence.py"
            res = subprocess.run([PY, str(ev_copy), "begin", "--plan", "plan.md"], cwd=self.repo.root,
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            res = subprocess.run([PY, str(ev_copy), "run", "--because", "t", "--phase", "baseline",
                                  "--expect", "exit == 0", "--", "true"],
                                 cwd=self.repo.root, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


if __name__ == "__main__":
    unittest.main(verbosity=1)
