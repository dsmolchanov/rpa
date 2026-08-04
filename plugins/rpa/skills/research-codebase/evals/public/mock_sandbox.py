#!/usr/bin/env python3
"""Mock sandbox wrapper for the synthetic preflight.

Records the workdir it was asked to confine (via MOCK_ECHO_DIR, like the
mock backend's other echo files), then replaces itself with the wrapped
command unchanged. A real deployment registers an actual sandbox (bwrap,
sandbox-exec, ...) as `sandbox_cmd`; this stub only proves the harness
wires the wrapper around every evaluated and judge session.

Usage: mock_sandbox.py <workdir> -- <cmd> [args...]
"""

import os
import sys
from pathlib import Path


def main():
    workdir = sys.argv[1]
    if sys.argv[2] != "--":
        print("mock_sandbox: expected `--` separator", file=sys.stderr)
        sys.exit(2)
    echo_dir = os.environ.get("MOCK_ECHO_DIR")
    if echo_dir:
        Path(echo_dir).mkdir(parents=True, exist_ok=True)
        (Path(echo_dir) / "sandbox.txt").write_text(
            workdir + "\n", encoding="utf-8"
        )
    os.execv(sys.argv[3], sys.argv[3:])


if __name__ == "__main__":
    main()
