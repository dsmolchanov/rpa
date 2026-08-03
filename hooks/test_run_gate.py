#!/usr/bin/env python3
"""Focused no-network tests for the hook gate runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_gate.py"


class HookGateTests(unittest.TestCase):
    def invoke(self, gate: str, cwd: Path, payload: object = None):
        raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return subprocess.run(
            [sys.executable, str(RUNNER), gate],
            cwd=cwd,
            input=raw,
            capture_output=True,
            check=False,
        )

    def test_format_without_path_is_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.invoke("format", Path(tmp), {})
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"outcome=not_applicable", result.stdout)

    def test_malformed_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(RUNNER), "format"],
                cwd=tmp,
                input=b"[",
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"outcome=failed", result.stderr)

    def test_non_git_lint_is_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.invoke("lint", Path(tmp), {})
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"outcome=not_applicable", result.stdout)

    def test_package_without_lint_is_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "package.json").write_text(
                '{"scripts":{"test":"node test.js"}}\n', encoding="utf-8"
            )
            result = self.invoke("lint", root, {})
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"package.json has no lint script", result.stdout)

    def test_non_jest_tests_are_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "package.json").write_text(
                '{"scripts":{"test":"node test.js"}}\n', encoding="utf-8"
            )
            result = self.invoke("related-tests", root, {})
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"no Jest-backed test script", result.stdout)


if __name__ == "__main__":
    unittest.main()
