#!/usr/bin/env python3
"""Synthetic preflight for the eval-runner (pilot plan, prerequisite 5).

Proves every runner capability against the deterministic mock backend on a
throwaway task — offline, CI-runnable, zero model spend. A real-backend
preflight on the throwaway task is still required once before baseline runs.
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402

EXPECTED_TREE = {"input_tokens": 140, "output_tokens": 70, "tool_calls": 12}
EXPECTED_MAIN = {"input_tokens": 100, "output_tokens": 50, "tool_calls": 7}
EXPECTED_SUB = {"input_tokens": 40, "output_tokens": 20, "tool_calls": 5}


def build_config(workspace, mode, timeout=15):
    install = workspace / f"install-{mode}"
    install.mkdir(parents=True, exist_ok=True)
    (install / "plugin.txt").write_text("mock installation\n", encoding="utf-8")
    return {
        "arms": {
            "mock": {
                "installation_dir": str(install),
                "sha256": runner.hash_tree(install),
                "model": "opus",
                "effort": "high",
            }
        },
        "backend_cmd": [sys.executable, str(HERE / "mock_claude.py"),
                        "--mode", mode],
        "timeout_seconds": timeout,
    }, install


def fresh_dirs(workspace, label):
    repo = workspace / f"repo-{label}"
    out = workspace / f"out-{label}"
    repo.mkdir()
    return repo, out


def run_case(workspace, mode, label=None, timeout=15, tamper=False):
    label = label or mode
    config, install = build_config(workspace, mode, timeout)
    if tamper:
        (install / "plugin.txt").write_text("tampered\n", encoding="utf-8")
    repo, out = fresh_dirs(workspace, label)
    task = workspace / f"task-{label}.md"
    task.write_text("Throwaway preflight task: research the mock subsystem.\n",
                    encoding="utf-8")
    return runner.run_task(config, "mock", task, repo, out), out


def check(name, condition, notes, detail=""):
    status = "PASS" if condition else "FAIL"
    notes.append((name, status, detail))
    return condition


def run_preflight():
    notes = []
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)

        record, out = run_case(ws, "normal")
        ok &= check("hash verification (clean run unblocked)",
                    record["status"] == "completed", notes,
                    f"status={record['status']}")
        acc = record.get("accounting", {})
        ok &= check(
            "tree-wide accounting (main/subagent/tree match declared)",
            acc.get("main") == EXPECTED_MAIN
            and acc.get("subagents") == EXPECTED_SUB
            and acc.get("tree") == EXPECTED_TREE,
            notes, json.dumps(acc.get("tree")))
        ok &= check(
            "per-node model capture and validation",
            all(n["model"] == "opus" for n in record.get("nodes", []))
            and record["registered_model"] == "opus"
            and record["effort"] == "high",
            notes, f"{len(record.get('nodes', []))} nodes")
        anon_files = list(Path(out).glob("run-*-anon.md"))
        raw_files = list(Path(out).glob("run-*-raw.md"))
        anon_text = anon_files[0].read_text(encoding="utf-8") if anon_files else ""
        raw_text = raw_files[0].read_text(encoding="utf-8") if raw_files else ""
        ok &= check(
            "anonymization (fingerprints masked in scored copy only)",
            "Mock Researcher" in raw_text
            and "Mock Researcher" not in anon_text
            and "deadbeef" not in anon_text,
            notes)
        profiles = list((Path(out) / "profiles").iterdir())
        ok &= check(
            "clean profile (fresh CLAUDE_CONFIG_DIR, no ambient entries)",
            len(profiles) == 1
            and sorted(p.name for p in profiles[0].iterdir()) == ["settings.json"],
            notes)

        record, _ = run_case(ws, "normal", label="tamper", tamper=True)
        ok &= check(
            "hash verification (tampered installation blocked as infra)",
            record["status"] == "infra_failure"
            and "hash mismatch" in record.get("failure", ""),
            notes, record.get("failure", "")[:60])

        record, _ = run_case(ws, "wrong-model")
        ok &= check(
            "model parity (unregistered effective model invalidates run)",
            record["status"] == "infra_failure"
            and "differ from registered" in record.get("failure", ""),
            notes)

        record, _ = run_case(ws, "infra-crash")
        ok &= check("infra failure classified (backend crash)",
                    record["status"] == "infra_failure", notes)
        record, _ = run_case(ws, "garbage")
        ok &= check("infra failure classified (unparseable output)",
                    record["status"] == "infra_failure", notes)

        record, _ = run_case(ws, "timeout", timeout=2)
        ok &= check("workflow failure classified (timeout, not replaced)",
                    record["status"] == "workflow_failure", notes)
        record, _ = run_case(ws, "no-artifact")
        ok &= check(
            "workflow failure classified (no artifact after continuations)",
            record["status"] == "workflow_failure"
            and record["interventions"] == runner.MAX_CONTINUATIONS,
            notes)

        record, _ = run_case(ws, "silent-stop")
        ok &= check(
            "driver continuation (ritual stop answered, counted)",
            record["status"] == "completed" and record["interventions"] == 1,
            notes)

        config, _ = build_config(ws, "normal")
        docs = []
        for i in range(2):
            doc = ws / f"anon-doc-{i}.md"
            doc.write_text(f"# Anonymized doc {i}\n", encoding="utf-8")
            docs.append(doc)
        judge = ws / "judge-prompt.md"
        judge.write_text("Score this document per the sealed rubric.\n",
                         encoding="utf-8")
        judge_out = ws / "judge-out"
        judge_out.mkdir()
        results = runner.score(config, docs, judge, judge_out)
        ok &= check(
            "fresh pinned judge sessions (distinct session + profile per call)",
            len(results) == 2
            and len({r["session_id"] for r in results}) == 2
            and len({r["profile"] for r in results}) == 2,
            notes)

    width = max(len(name) for name, _, _ in notes)
    for name, status, detail in notes:
        suffix = f"  ({detail})" if detail else ""
        print(f"preflight: {name.ljust(width)}  {status}{suffix}")
    print(f"preflight {'OK' if ok else 'FAILED'}: "
          f"{sum(1 for _, s, _ in notes if s == 'PASS')}/{len(notes)} capabilities")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_preflight())
