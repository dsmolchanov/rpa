#!/usr/bin/env python3
"""Tests for validate_session_log.py against the fixtures under
fixtures/session-logs/ (VL-01 … VL-33). Each invalid case must be rejected
naming the contract check it violates; the two valid cases must pass."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate_session_log.py"
FIXTURES = HERE / "fixtures" / "session-logs"
PY = sys.executable

# (VL id, case directory, expected check letter or None for valid)
CASES = [
    ("VL-01", "valid", None),
    ("VL-02", "valid-continuing", None),
    ("VL-03", "missing-receipt", "g"),
    ("VL-04", "unresolvable-receipt", "e"),
    ("VL-05", "manual-as-green", "k"),
    ("VL-06", "heading-order", "a"),
    ("VL-07", "run-mismatch", "c"),
    ("VL-08", "nonpass-disposition", "j"),
    ("VL-09", "fenced-heading", "a"),
    ("VL-10", "html-comment-heading", "a"),
    ("VL-11", "broken-chain", "j"),
    ("VL-12", "missing-checkpoint", "l"),
    ("VL-13", "hollow", "h"),
    ("VL-14", "uncited-attempt", "i"),
    ("VL-15", "standin-exit-only", "j"),
    ("VL-16", "tampered-export", "f"),
    ("VL-17", "trimmed-export", "d"),
    ("VL-18", "intent-deleted", "d"),
    ("VL-19", "duplicate-terminal", "d"),
    ("VL-20", "ref-mismatch", "d"),
    ("VL-21", "unsealed-complete", "m"),
    ("VL-22", "achieved-mismatch", "m"),
    ("VL-23", "partial-cases", "h"),
    ("VL-24", "plan-mismatch", "c"),
    ("VL-25", "export-traversal", "b"),
    ("VL-26", "export-absolute", "b"),
    ("VL-27", "export-symlink", "c"),
    ("VL-28", "attempt-after-checkpoint", "l"),
    ("VL-29", "record-after-final", "l"),
    ("VL-31", "inline-comment-hidden", "i"),
    ("VL-32", "trailing-transcription", "g"),
    ("VL-33", "baseline-runs-missing", "g"),
]


def log_of(case: str) -> Path:
    logs = sorted((FIXTURES / case / "thoughts" / "shared" / "tests").glob("*-TDD-SESSION-*.md"))
    assert len(logs) == 1, (case, logs)
    return logs[0]


def run_validator(log: Path) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(VALIDATOR), str(log)], capture_output=True, text=True, check=False)


class SessionLogValidatorTests(unittest.TestCase):
    def test_fixture_cases(self):
        for vl, case, letter in CASES:
            with self.subTest(vl=vl, case=case):
                res = run_validator(log_of(case))
                if letter is None:
                    self.assertEqual(res.returncode, 0, f"{vl} {case}: {res.stdout}{res.stderr}")
                    self.assertIn("session-log: OK", res.stdout)
                else:
                    self.assertEqual(res.returncode, 1, f"{vl} {case}: {res.stdout}{res.stderr}")
                    self.assertIn(f"session-log: {letter} —", res.stdout, f"{vl} {case}: {res.stdout}")

    def test_every_fixture_directory_is_classified(self):
        # Every case directory is either valid (accepted) or invalid (rejected)
        # — a fixture that drifts into the wrong class fails here, not silently.
        names = sorted(d.name for d in FIXTURES.iterdir() if d.is_dir() and not d.name.startswith(("_", ".")))
        self.assertEqual(names, sorted(c for _, c, _ in CASES))
        for name in names:
            res = run_validator(log_of(name))
            if name.startswith("valid"):
                self.assertEqual(res.returncode, 0, f"{name}: {res.stdout}{res.stderr}")
            else:
                self.assertEqual(res.returncode, 1, f"{name}: {res.stdout}{res.stderr}")

    def test_vl30_log_outside_layout_is_usage_error(self):
        with tempfile.TemporaryDirectory(prefix="vl-") as tmp:
            copy = Path(tmp) / "copied-log.md"
            shutil.copy(log_of("valid"), copy)
            res = run_validator(copy)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertIn("outside the contract layout", res.stdout + res.stderr)
        res = subprocess.run([PY, str(VALIDATOR), str(FIXTURES / "nope.md")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        res = subprocess.run([PY, str(VALIDATOR)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)

    def test_valid_fixture_is_a_complete_export(self):
        import json
        case = FIXTURES / "valid" / "thoughts" / "shared" / "tests"
        export = json.loads(next((case / "receipts").glob("*.json")).read_text())
        ns = sorted({e["n"] for e in export["events"]})
        self.assertEqual(ns, list(range(1, export["records_through"] + 1)))
        outcomes = {e["outcome"] for e in export["events"] if e["kind"] not in ("started", "checkpoint")}
        self.assertIn("STALE", outcomes)  # the valid log cites a failed attempt, not only successes
        self.assertEqual(export["run"]["state"], "sealed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
