#!/usr/bin/env python3
"""Write a one-testcase JUnit XML report without needing pytest.

Usage: junit_stub.py --out <path> --case <classname.name>
                     --outcome pass|failure|error|skipped [--message <text>]

Exits 0 for `pass`, 1 otherwise — so the exit code and the report agree the
way a real test runner's would. Used by test_evidence.py and by the plan's
end-to-end dry run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--case", required=True, help="<classname>.<name>")
    ap.add_argument("--outcome", required=True, choices=("pass", "failure", "error", "skipped"))
    ap.add_argument("--message", default="")
    args = ap.parse_args()
    classname, _, name = args.case.rpartition(".")
    if args.outcome == "pass":
        child = ""
    else:
        child = f"<{args.outcome} message={quoteattr(args.message)}>{escape(args.message)}</{args.outcome}>"
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="stub" tests="1">'
        f'<testcase classname={quoteattr(classname)} name={quoteattr(name)}>{child}</testcase>'
        "</testsuite></testsuites>\n"
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"junit_stub: {args.case} {args.outcome} -> {out}")
    return 0 if args.outcome == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
