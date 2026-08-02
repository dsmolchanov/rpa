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
import hashlib
import json
import subprocess
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

**Date**: 2026-07-26T00:00:00Z
**Researcher**: Mock Researcher
**Git Commit**: deadbeef
**Branch**: mock-branch
**Repository**: mock-repo

## Research Question
Mock research question.

## Summary
Deterministic mock artifact for the preflight.

## Detailed Findings

### Mock area
- Mock finding (`mock/file.py:1`).

## Code References
- `mock/file.py:1` - Mock reference.

## Architecture Documentation
None (mock).

## Historical Context (from thoughts/)
None (mock).

## Related Research
None (mock).

## Open Questions
None (mock).
"""

ARTIFACT_BAD = """---
date: 2026-07-26T00:00:00Z
topic: "Nonconforming mock artifact"
---

# Wrong Title

Free-form text without the contract's frontmatter or sections.
"""


SCORER_RESPONSE = {
    "coverage": {
        "score": 3.5,
        "rationale": "The mock document covers the registered areas.",
    },
    "relevance": {
        "score": 2.5,
        "rationale": "The mock findings stay focused on the task.",
    },
    "synthesis": {
        "score": 2.0,
        "rationale": "The mock document connects its findings.",
    },
    "total": 8.0,
    "summary": "Deterministic valid scorer response.",
}

VERIFIER_RESPONSE = {
    "verifiable_claims": 2,
    "supported_claims": 1,
    "unsupported_claims": 1,
    "unverifiable_claims": 0,
    "claim_ledger": [
        {
            "claim": "The mock file contains the cited definition.",
            "candidate_citations": ["mock/file.py:1"],
            "status": "supported",
            "evidence": ["mock/file.py:1"],
            "rationale": "The cited line supports the claim.",
        },
        {
            "claim": "The mock file contains an additional setting.",
            "candidate_citations": ["mock/file.py:2"],
            "status": "unsupported",
            "evidence": [],
            "rationale": "The cited setting is absent from frozen evidence.",
        },
    ],
    "critical_errors": [],
    "critical_error_count": 0,
    "summary": "Deterministic valid verifier response.",
}


def emit(event):
    print(json.dumps(event), flush=True)


def write_artifact(commit=None):
    """The artifact's `git_commit` records the ACTUAL worktree checkout
    (like the real workflow's metadata script); the stale-artifact mode
    passes a wrong commit to prove the harness's run-binding check."""
    if commit is None:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True,
                text=True).stdout.strip() or "0" * 40
        except OSError:
            commit = "0" * 40
    # `repository` is DERIVED from the checkout like the prescribed
    # metadata script does (toplevel basename) — hard-coding it would
    # hide a uuid-named worktree from the run-binding gate.
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True,
            text=True).stdout.strip()
    except OSError:
        top = ""
    repo_name = Path(top).name if top else Path.cwd().name
    research = Path("thoughts/shared/research")
    research.mkdir(parents=True, exist_ok=True)
    (research / "2026-07-26-mock-research.md").write_text(
        ARTIFACT.replace("deadbeef", commit).replace("mock-repo", repo_name),
        encoding="utf-8")


def write_non_utf8_artifact():
    """Write a fresh Markdown-named artifact with invalid UTF-8 bytes."""
    research = Path("thoughts/shared/research")
    research.mkdir(parents=True, exist_ok=True)
    (research / "2026-07-26-non-utf8.md").write_bytes(
        b"---\nstatus: complete\n---\n\n# invalid utf-8: \xff\n")


def write_multiple_artifacts():
    """Write two nonempty fresh documents for population-shape testing."""
    write_artifact()
    research = Path("thoughts/shared/research")
    original = research / "2026-07-26-mock-research.md"
    (research / "2026-07-26-mock-research-extra.md").write_bytes(
        original.read_bytes())


def write_empty_artifact():
    """Write a Markdown-named file that is not a nonempty document."""
    research = Path("thoughts/shared/research")
    research.mkdir(parents=True, exist_ok=True)
    (research / "2026-07-26-empty.md").write_bytes(b" \n\t\n")


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
           "subagent_id": f"mock-sub-{uuid.uuid4().hex[:6]}",
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
    # Client-generated notice exactly like the real CLI's synthetic
    # assistant events: must be EXCLUDED from parity and accounting (the
    # declared totals below do not include it).
    emit({"type": "assistant", "session_id": session_id,
          "parent_tool_use_id": None,
          "message": {"model": "<synthetic>",
                      "usage": {},
                      "content": [{"type": "text",
                                   "text": "client notice: plugin loaded"}]}})
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
                                   "name": "Task" if i == 0 else "Read",
                                   "input": {}}
                                  for i in range(7)]}})
    # TWO messages from ONE subagent (same parent_tool_use_id): the runner
    # must count one distinct spawned subagent, not two, while still
    # summing both messages' usage into the subagent subtotal.
    emit({"type": "assistant", "session_id": session_id,
          "parent_tool_use_id": "toolu_0",
          "message": {"model": model,
                      "usage": {"input_tokens": 12,
                                "cache_creation_input_tokens": 6,
                                "cache_read_input_tokens": 2,
                                "output_tokens": 10},
                      "content": [{"type": "tool_use", "id": f"toolu_s{i}",
                                   "name": "Grep", "input": {}}
                                  for i in range(3)]}})
    emit({"type": "assistant", "session_id": session_id,
          "parent_tool_use_id": "toolu_0",
          "message": {"model": model,
                      "usage": {"input_tokens": 8,
                                "cache_creation_input_tokens": 6,
                                "cache_read_input_tokens": 6,
                                "output_tokens": 10},
                      "content": [{"type": "tool_use", "id": f"toolu_s{i}",
                                   "name": "Read", "input": {}}
                                  for i in range(3, 5)]}})
    write_artifact()
    emit({"type": "result", "subtype": "success", "session_id": session_id,
          "result": "MOCK-VERDICT: coverage 7/10, evidence 9/10"})


def judge_result(prompt):
    """Return the deterministic role-specific protocol-v2 JSON object.

    The real backend learns its role from the sealed prompt, not a special
    command-line flag. The mock follows that contract: preflight prompts carry
    one of these non-sensitive markers so one registered judge command can
    exercise both roles.
    """
    if "VERIFIER-CONTRACT" in prompt:
        return json.dumps(VERIFIER_RESPONSE, sort_keys=True)
    if "SCORER-CONTRACT" in prompt:
        return json.dumps(SCORER_RESPONSE, sort_keys=True)
    return json.dumps(SCORER_RESPONSE, sort_keys=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="version",
                        version="mock-claude 1.0.0")
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--plugin-dir")
    parser.add_argument("--judge-state-file")
    parser.add_argument("--run-state-file")
    parser.add_argument("--prompt-receipt-file")
    parser.add_argument("--transport-receipt-file")
    parser.add_argument("--child-write-file")
    parser.add_argument("--resume")
    parser.add_argument("--verbose", action="store_true")
    # Claude Code 2.1.220 treats `-p` as the non-interactive/print switch;
    # its optional positional prompt may be omitted, in which case the exact
    # prompt is read from stdin. Keep accepting the historical positional
    # form so direct transport-compatibility checks can exercise both forms.
    parser.add_argument("-p", "--print", dest="print_mode",
                        action="store_true", required=True)
    parser.add_argument("prompt_arg", nargs="?")
    parser.add_argument("--output-format", default="text")
    parser.add_argument("--json-schema")
    args = parser.parse_args()

    prompt_source = "argv" if args.prompt_arg is not None else "stdin"
    prompt = args.prompt_arg if args.prompt_arg is not None else sys.stdin.read()

    if args.output_format == "stream-json" and not args.verbose:
        parser.error(
            "When using --print, --output-format=stream-json requires "
            "--verbose")

    echo("prompt.txt", prompt)
    echo("plugin-dir.txt", args.plugin_dir)
    echo("cwd-listing.txt",
         "\n".join(sorted(p.name for p in Path(".").iterdir())))
    if args.prompt_receipt_file:
        Path(args.prompt_receipt_file).write_text(
            hashlib.sha256(prompt.encode("utf-8")).hexdigest() + "\n",
            encoding="utf-8",
        )
    if args.transport_receipt_file:
        with Path(args.transport_receipt_file).open(
                "a", encoding="utf-8") as receipt:
            receipt.write(json.dumps({
                "argv": sys.argv[1:],
                "prompt": prompt,
                "prompt_source": prompt_source,
            }, sort_keys=True) + "\n")

    if args.mode == "flaky-infra":
        # Transient fault: crash once, then behave normally. The explicit
        # CLI path is usable under protocol v2's minimal environment policy;
        # the environment fallback remains for historical v1 self-tests.
        state = args.run_state_file or os.environ.get("MOCK_STATE_FILE", "")
        if state and not Path(state).exists():
            Path(state).write_text("crashed once\n", encoding="utf-8")
            print("transient mock crash", file=sys.stderr)
            sys.exit(3)
        args.mode = "normal"

    if args.mode == "infra-crash":
        print("mock backend crashed", file=sys.stderr)
        sys.exit(3)
    if args.mode in ("slow-normal", "judge-slow-auto"):
        time.sleep(0.5)
        if args.mode == "slow-normal":
            args.mode = "normal"
    if args.mode == "slow-no-artifact":
        # Burns most of a small run-level deadline per session, never makes
        # an artifact: proves continuations share ONE deadline instead of
        # each getting the full timeout again.
        time.sleep(1.2)
        args.mode = "no-artifact"
    if args.mode == "garbage":
        print("this is not json")
        sys.exit(0)
    if args.mode == "hang-silent":
        # Hangs without emitting ANY event: a failure with zero parity
        # evidence must be invalidated (infra), never counted.
        time.sleep(30)
        sys.exit(0)

    session_id = f"mock-{uuid.uuid4().hex[:8]}"

    if args.mode == "real-stream":
        emit_real_stream(args.model, session_id)
        return

    emit({"type": "system", "session_id": session_id})

    model = (
        "unregistered-model"
        if args.mode in ("wrong-model", "abort-wrong-model")
        else args.model
    )

    if args.mode == "launch-no-child":
        # Delegation happened (subagent_launches=1) but the child died
        # before emitting anything: launch evidence alone must count.
        emit({"type": "node", "model": model, "effort": args.effort,
              "tool_calls": 7, "subagent_launches": 1,
              "usage": {"input_tokens": 100, "output_tokens": 50}})
        write_artifact()
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: coverage 7/10, evidence 9/10"})
        return
    if args.mode in {
            "bad-accounting-negative", "bad-accounting-fractional",
            "bad-accounting-typed", "bad-accounting-missing",
            "bad-accounting-zero", "abort-bad-accounting"}:
        usage = {"input_tokens": 100, "output_tokens": 50}
        tool_calls = 7
        if args.mode == "bad-accounting-negative":
            usage["input_tokens"] = -1
        elif args.mode == "bad-accounting-fractional":
            usage["output_tokens"] = 1.5
        elif args.mode == "bad-accounting-typed":
            usage = ["not", "an", "object"]
            tool_calls = True
        elif args.mode == "bad-accounting-missing":
            usage = {"input_tokens": 100}
        elif args.mode == "bad-accounting-zero":
            usage = {"input_tokens": 0, "output_tokens": 0}
        else:
            usage["input_tokens"] = "100"
        emit({"type": "node", "model": model, "effort": args.effort,
              "tool_calls": tool_calls, "usage": usage})
        if args.mode == "abort-bad-accounting":
            print("workflow aborted with malformed accounting",
                  file=sys.stderr)
            sys.exit(21)
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: malformed accounting"})
        return
    if args.mode in ("bad-assistant-message",
                     "abort-bad-assistant-message"):
        # A malformed assistant envelope must never disappear merely because
        # later events carry valid accounting.  This mirrors a truncated or
        # schema-drifted real stream event rather than a synthetic node.
        emit({"type": "assistant", "session_id": session_id,
              "message": None})
        emit_nodes(model, args.effort, args.effort)
        if args.mode == "abort-bad-assistant-message":
            print("workflow aborted after malformed assistant event",
                  file=sys.stderr)
            sys.exit(21)
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: malformed assistant envelope"})
        return
    if args.mode == "wrong-effort":
        main_effort = sub_effort = "low"
    elif args.mode == "mixed-effort":
        main_effort, sub_effort = args.effort, None
    else:
        main_effort = sub_effort = args.effort
    emit_nodes(model, main_effort, sub_effort)

    if args.mode == "abort-malformed-stream":
        # Preserve a valid first node population, then truncate another event.
        # Accepting only the valid prefix would undercount an observed abort.
        print('{"type":"node"', flush=True)
        print("workflow aborted after truncated accounting event",
              file=sys.stderr)
        sys.exit(21)

    if args.mode in ("background-child-success",
                     "judge-background-child"):
        if not args.child_write_file:
            print("--child-write-file is required", file=sys.stderr)
            sys.exit(3)
        child_code = (
            "import pathlib,time; time.sleep(1); "
            f"pathlib.Path({args.child_write_file!r}).write_text('survived')"
        )
        subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        if args.mode == "background-child-success":
            write_artifact()
            result_text = "MOCK-VERDICT: parent exited successfully"
        else:
            result_text = judge_result(prompt)
        result_event = {"type": "result", "subtype": "success",
                        "session_id": session_id, "result": result_text}
        if (args.json_schema is not None
                and args.mode == "judge-background-child"):
            result_event["structured_output"] = json.loads(result_text)
        emit(result_event)
        return

    if args.mode in ("judge-auto", "judge-slow-auto", "judge-invalid",
                     "judge-invalid-then-valid"):
        if args.mode == "judge-invalid":
            result_text = '{"coverage": {"score": 3.5}'
        elif args.mode == "judge-invalid-then-valid":
            state_name = (args.judge_state_file
                          or os.environ.get("MOCK_JUDGE_STATE_FILE", ""))
            if not state_name:
                print("--judge-state-file is required", file=sys.stderr)
                sys.exit(3)
            state = Path(state_name)
            try:
                count = int(state.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                count = 0
            state.write_text(str(count + 1), encoding="utf-8")
            result_text = ('```json\n{"total": 8}\n```'
                           if count == 0 else judge_result(prompt))
        else:
            result_text = judge_result(prompt)
        result_event = {"type": "result", "subtype": "success",
                        "session_id": session_id, "result": result_text}
        if args.json_schema is not None:
            try:
                result_event["structured_output"] = json.loads(result_text)
            except json.JSONDecodeError:
                # Invalid judge modes deliberately emulate a terminal CLI
                # result with no usable structured output.
                pass
        emit(result_event)
        return

    if args.mode == "timeout":
        # Hangs AFTER emitting accounting: the killed session's partial
        # transcript carries parity evidence, so this counts as a workflow
        # failure with its cost preserved.
        time.sleep(30)
        sys.exit(0)

    if args.mode == "timeout-with-child":
        # Spawns a long-lived tool subprocess, echoes its pid, then hangs:
        # the harness must kill the WHOLE process group on timeout, so the
        # child must not survive the recorded timeout.
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"])
        echo("child-pid.txt", str(child.pid))
        time.sleep(30)
        sys.exit(0)

    if args.mode in ("workflow-abort", "abort-wrong-model"):
        # Abort AFTER emitting accounting: the runner must preserve the
        # partial transcript's cost on this counted workflow failure —
        # and must invalidate it instead when those nodes show runtime
        # drift (abort-wrong-model).
        print("workflow aborted by evaluated agent", file=sys.stderr)
        sys.exit(21)

    if args.mode == "abort-after-stop":
        # A valid result can precede the registered abort exit. The runner
        # must retain it as the final unanswered pre-artifact stop.
        emit({"type": "result", "session_id": session_id,
              "result": "Hello. Please provide the research query."})
        print("workflow aborted after ritual stop", file=sys.stderr)
        sys.exit(21)

    if args.mode == "abort-after-artifact":
        # The workflow wrote a document and only then aborted. Protocol v2
        # must retain the abort outcome while still gating and judging the
        # document instead of deleting it with the disposable worktree.
        write_artifact()
        print("workflow aborted after writing artifact", file=sys.stderr)
        sys.exit(21)

    if args.mode == "timeout-after-artifact":
        # Same ordering as above, but exercise the timeout path.
        write_artifact()
        time.sleep(30)
        sys.exit(0)

    if args.mode == "stale-artifact":
        # Metadata claims a checkout OTHER than the run's pinned
        # target-sha: the harness must reject the run-binding mismatch as
        # a counted workflow failure.
        emit_nodes(model, args.effort, args.effort)
        write_artifact(commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: stale metadata"})
        return

    if args.mode == "bad-artifact":
        # Fresh document that VIOLATES the artifact contract: the harness
        # must reject it as a counted workflow failure, never score it.
        research = Path("thoughts/shared/research")
        research.mkdir(parents=True, exist_ok=True)
        (research / "mock-bad.md").write_text(ARTIFACT_BAD, encoding="utf-8")
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: wrote nonconforming document"})
        return

    if args.mode == "bad-utf8-artifact":
        write_non_utf8_artifact()
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: wrote non-UTF-8 document"})
        return

    if args.mode == "multiple-artifacts":
        write_multiple_artifacts()
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: wrote multiple documents"})
        return

    if args.mode == "empty-artifact":
        write_empty_artifact()
        emit({"type": "result", "session_id": session_id,
              "result": "MOCK-VERDICT: wrote only whitespace"})
        return

    if args.mode == "silent-stop":
        # First call: greet-and-wait (no artifact). Only a resumed session
        # (the driver's fixed continuation) produces the artifact.
        if args.resume:
            write_artifact()
    elif args.mode == "no-artifact":
        pass
    else:
        write_artifact()

    result_text = "MOCK-VERDICT: coverage 7/10, evidence 9/10"
    if args.mode == "silent-stop" and not args.resume:
        # Ritual stop: a question-shaped pause instead of proceeding.
        result_text = "Ready to research the mock subsystem. Shall I proceed?"
    emit({"type": "result", "session_id": session_id, "result": result_text})


if __name__ == "__main__":
    main()
