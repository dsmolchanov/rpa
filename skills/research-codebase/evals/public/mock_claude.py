#!/usr/bin/env python3
"""Deterministic mock backend for the eval-runner preflight.

Emulates the headless-backend contract the runner depends on (stream-json
node/accounting lines, a session id, a result text, an artifact written
under thoughts/shared/research/ in the cwd worktree) with fixed, declared
numbers so the preflight can assert exact tree-wide accounting. Failure
modes are selected with --mode.

Echo files: when MOCK_ECHO_DIR is set, the received prompt and --plugin-dir
value are written there (`prompt.txt`, `plugin-dir.txt`) so the preflight
can assert what actually reached the backend even after the disposable
worktree is removed.

Declared accounting per invocation:
  main node:     model=<--model>, input 100, output 50, tool_calls 7
  subagent node: model=<--model>, input  40, output 20, tool_calls 5
"""

import argparse
import json
import os
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


def echo(name, value):
    echo_dir = os.environ.get("MOCK_ECHO_DIR")
    if echo_dir:
        Path(echo_dir).mkdir(parents=True, exist_ok=True)
        (Path(echo_dir) / name).write_text(value or "", encoding="utf-8")


def emit_nodes(model, main_effort, sub_effort):
    """`None` for either effort emits that node without an effort field
    (mixed-effort mode proves broken-capture rejection)."""
    main = {"type": "node", "model": model, "tool_calls": 7,
            "usage": {"input_tokens": 100, "output_tokens": 50}}
    sub = {"type": "node", "model": model, "subagent": True, "tool_calls": 5,
           "usage": {"input_tokens": 40, "output_tokens": 20}}
    if main_effort is not None:
        main["effort"] = main_effort
    if sub_effort is not None:
        sub["effort"] = sub_effort
    emit(main)
    emit(sub)


def emit_real_stream(model, session_id):
    """Emit the real Claude Code headless stream schema with the same
    declared accounting: `assistant` events with usage/model nested in
    `message`, tool calls as `tool_use` content blocks, a non-null
    `parent_tool_use_id` marking the subagent node, and a `result` event.
    No per-node effort field — exactly like the real CLI."""
    emit({"type": "system", "subtype": "init", "session_id": session_id,
          "model": model})
    # Input usage is split across the real CLI's three categories (fresh +
    # cache creation + cache read); the declared totals stay 100/40, so the
    # preflight only passes if the parser sums ALL input categories.
    emit({"type": "assistant", "session_id": session_id,
          "parent_tool_use_id": None,
          "message": {"model": model,
                      "usage": {"input_tokens": 60,
                                "cache_creation_input_tokens": 30,
                                "cache_read_input_tokens": 10,
                                "output_tokens": 50},
                      "content": [{"type": "tool_use", "id": f"toolu_{i}",
                                   "name": "Read", "input": {}}
                                  for i in range(7)]}})
    emit({"type": "assistant", "session_id": session_id,
          "parent_tool_use_id": "toolu_0",
          "message": {"model": model,
                      "usage": {"input_tokens": 20,
                                "cache_creation_input_tokens": 12,
                                "cache_read_input_tokens": 8,
                                "output_tokens": 20},
                      "content": [{"type": "tool_use", "id": f"toolu_s{i}",
                                   "name": "Grep", "input": {}}
                                  for i in range(5)]}})
    write_artifact()
    emit({"type": "result", "subtype": "success", "session_id": session_id,
          "result": "MOCK-VERDICT: coverage 7/10, evidence 9/10"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--plugin-dir")
    parser.add_argument("--resume")
    parser.add_argument("-p", dest="prompt", required=True)
    parser.add_argument("--output-format", default="stream-json")
    args = parser.parse_args()

    echo("prompt.txt", args.prompt)
    echo("plugin-dir.txt", args.plugin_dir)
    echo("cwd-listing.txt",
         "\n".join(sorted(p.name for p in Path(".").iterdir())))

    if args.mode == "flaky-infra":
        # Transient fault: crash once (recorded via MOCK_STATE_FILE), then
        # behave normally, so the runner's auto-retry can be proven.
        state = os.environ.get("MOCK_STATE_FILE", "")
        if state and not Path(state).exists():
            Path(state).write_text("crashed once\n", encoding="utf-8")
            print("transient mock crash", file=sys.stderr)
            sys.exit(3)
        args.mode = "normal"

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

    if args.mode == "real-stream":
        emit_real_stream(args.model, session_id)
        return

    emit({"type": "system", "session_id": session_id})

    model = "unregistered-model" if args.mode == "wrong-model" else args.model
    if args.mode == "wrong-effort":
        main_effort = sub_effort = "low"
    elif args.mode == "mixed-effort":
        main_effort, sub_effort = args.effort, None
    else:
        main_effort = sub_effort = args.effort
    emit_nodes(model, main_effort, sub_effort)

    if args.mode == "workflow-abort":
        # Abort AFTER emitting accounting: the runner must preserve the
        # partial transcript's cost on this counted workflow failure.
        print("workflow aborted by evaluated agent", file=sys.stderr)
        sys.exit(21)

    if args.mode == "silent-stop":
        # First call: greet-and-wait (no artifact). Only a resumed session
        # (the driver's fixed continuation) produces the artifact.
        if args.resume:
            write_artifact()
    elif args.mode == "no-artifact":
        pass
    else:
        write_artifact()

    emit({"type": "result", "session_id": session_id,
          "result": "MOCK-VERDICT: coverage 7/10, evidence 9/10"})


if __name__ == "__main__":
    main()
