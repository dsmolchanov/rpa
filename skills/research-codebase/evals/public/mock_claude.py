#!/usr/bin/env python3
"""Deterministic mock backend for the eval-runner preflight.

Emulates the headless-backend contract the runner depends on (stream-json
node/accounting lines, a session id, an artifact written under
thoughts/shared/research/) with fixed, declared numbers so the preflight can
assert exact tree-wide accounting. Failure modes are selected with --mode.

Declared accounting per invocation:
  main node:     model=<--model>, input 100, output 50, tool_calls 7
  subagent node: model=<--model>, input  40, output 20, tool_calls 5
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ARTIFACT = """---
date: 2026-07-26T00:00:00Z
researcher: Mock Researcher
git_commit: deadbeef
branch: mock-branch
repository: mock-repo
topic: "Mock topic"
tags: [research]
status: complete
last_updated: 2026-07-26
last_updated_by: Mock Researcher
---

# Research: Mock topic

**Date**: 2026-07-26
**Researcher**: Mock Researcher
**Git Commit**: deadbeef
**Branch**: mock-branch
**Repository**: mock-repo

## Summary
Deterministic mock artifact for the preflight.
"""


def emit(event):
    print(json.dumps(event), flush=True)


def write_artifact():
    research = Path("thoughts/shared/research")
    research.mkdir(parents=True, exist_ok=True)
    (research / "mock-research.md").write_text(ARTIFACT, encoding="utf-8")


def emit_nodes(model):
    emit({"type": "node", "model": model, "tool_calls": 7,
          "usage": {"input_tokens": 100, "output_tokens": 50}})
    emit({"type": "node", "model": model, "subagent": True, "tool_calls": 5,
          "usage": {"input_tokens": 40, "output_tokens": 20}})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--resume")
    parser.add_argument("-p", dest="prompt", required=True)
    parser.add_argument("--output-format", default="stream-json")
    args = parser.parse_args()

    if args.mode == "infra-crash":
        print("mock backend crashed", file=sys.stderr)
        sys.exit(3)
    if args.mode == "garbage":
        print("this is not json")
        sys.exit(0)
    if args.mode == "timeout":
        time.sleep(30)
        sys.exit(0)

    session_id = f"mock-{uuid.uuid4().hex[:8]}"
    emit({"type": "system", "session_id": session_id})

    model = "unregistered-model" if args.mode == "wrong-model" else args.model
    emit_nodes(model)

    if args.mode == "silent-stop":
        # First call: greet-and-wait (no artifact). Only a resumed session
        # (the driver's fixed continuation) produces the artifact.
        if args.resume:
            write_artifact()
    elif args.mode == "no-artifact":
        pass
    else:
        write_artifact()

    emit({"type": "result", "session_id": session_id})


if __name__ == "__main__":
    main()
