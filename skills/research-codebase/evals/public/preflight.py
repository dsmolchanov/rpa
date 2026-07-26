#!/usr/bin/env python3
"""Synthetic preflight for the eval-runner (pilot plan, prerequisite 5).

Proves every runner capability against the deterministic mock backend on a
throwaway task — offline, CI-runnable, zero model spend. A real-backend
preflight on the throwaway task is still required once before baseline runs.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402

EXPECTED_TREE = {"input_tokens": 140, "output_tokens": 70, "tool_calls": 12}
EXPECTED_MAIN = {"input_tokens": 100, "output_tokens": 50, "tool_calls": 7}
EXPECTED_SUB = {"input_tokens": 40, "output_tokens": 20, "tool_calls": 5}
SECRET = "SECRET-GROUND-TRUTH-MARKER"


def make_git_repo(workspace, label, seed_research=False):
    repo = Path(workspace) / f"repo-{label}"
    repo.mkdir()
    def git(*args):
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=preflight",
             "-c", "user.email=preflight@example.invalid", *args],
            check=True, capture_output=True,
        )
    git("init", "-q")
    (repo / "README.md").write_text("# Throwaway preflight repo\n", encoding="utf-8")
    if seed_research:
        research = repo / "thoughts" / "shared" / "research"
        research.mkdir(parents=True)
        (research / "pre-existing.md").write_text(
            "# Pre-existing research (must be ignored)\n", encoding="utf-8"
        )
    git("add", "-A")
    git("commit", "-q", "-m", "preflight seed")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return repo, sha


def build_config(workspace, mode, timeout=20):
    install = Path(workspace) / f"install-{mode}"
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
                        "--mode", mode, "--plugin-dir", "{installation}"],
        "timeout_seconds": timeout,
    }, install


def write_task(workspace, label, sha):
    task = Path(workspace) / f"task-{label}.md"
    task.write_text(
        f"---\ntask-id: preflight-{label}\ntarget-sha: {sha}\nset: preflight\n---\n\n"
        f"## Task prompt\n\nThrowaway preflight task: research the mock subsystem.\n\n"
        f"## Ground truth\n\n{SECRET}\n",
        encoding="utf-8",
    )
    return task


def run_case(workspace, mode, label=None, timeout=20, tamper=False,
             sha_override=None, seed_research=False):
    label = label or mode
    config, install = build_config(workspace, mode, timeout)
    if tamper:
        (install / "plugin.txt").write_text("tampered\n", encoding="utf-8")
    repo, sha = make_git_repo(workspace, label, seed_research=seed_research)
    task = write_task(workspace, label, sha_override or sha)
    out = Path(workspace) / f"out-{label}"
    echo_dir = Path(workspace) / f"echo-{label}"
    os.environ["MOCK_ECHO_DIR"] = str(echo_dir)
    try:
        record = runner.run_task(config, "mock", task, repo, out)
    finally:
        os.environ.pop("MOCK_ECHO_DIR", None)
    return record, out, echo_dir, sha


def check(name, condition, notes, detail=""):
    notes.append((name, "PASS" if condition else "FAIL", detail))
    return bool(condition)


def run_preflight():
    notes = []
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)

        record, out, echo_dir, sha = run_case(ws, "normal")
        ok &= check("clean run completes", record["status"] == "completed",
                    notes, f"status={record['status']}")
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
        prompt_echo = (echo_dir / "prompt.txt").read_text(encoding="utf-8")
        ok &= check(
            "prompt extraction (ground truth never reaches the session)",
            "Throwaway preflight task" in prompt_echo
            and SECRET not in prompt_echo,
            notes)
        plugin_echo = (echo_dir / "plugin-dir.txt").read_text(encoding="utf-8").strip()
        ok &= check(
            "installation mounted into profile and passed to backend",
            plugin_echo
            and Path(plugin_echo).name == "mock"
            and "profiles" in plugin_echo
            and runner.hash_tree(plugin_echo) == record["installation_sha256"],
            notes, Path(plugin_echo).name if plugin_echo else "missing")
        ok &= check(
            "worktree isolation (pinned sha recorded, disposable removed)",
            record.get("target_sha") == sha
            and record.get("worktree")
            and not Path(record["worktree"]).exists(),
            notes)
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
            "clean profile (only settings.json + mounted installation)",
            len(profiles) == 1
            and sorted(p.name for p in profiles[0].iterdir())
            == ["plugins", "settings.json"],
            notes)

        record, _, _, _ = run_case(ws, "normal", label="tamper", tamper=True)
        ok &= check(
            "hash verification (tampered installation blocked as infra)",
            record["status"] == "infra_failure"
            and "hash mismatch" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "normal", label="wrong-sha",
                                   sha_override="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
        ok &= check(
            "wrong target-sha blocked as infra (no run on wrong revision)",
            record["status"] == "infra_failure", notes,
            record.get("failure", "")[:50])

        record, _, _, _ = run_case(ws, "wrong-model")
        ok &= check(
            "model parity (unregistered effective model invalidates run)",
            record["status"] == "infra_failure"
            and "differ from registered" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "infra-crash")
        ok &= check("infra failure classified (backend crash)",
                    record["status"] == "infra_failure", notes)
        record, _, _, _ = run_case(ws, "garbage")
        ok &= check("infra failure classified (unparseable output)",
                    record["status"] == "infra_failure", notes)

        record, _, _, _ = run_case(ws, "timeout", timeout=2)
        ok &= check("workflow failure classified (timeout, not replaced)",
                    record["status"] == "workflow_failure", notes)

        record, _, _, _ = run_case(ws, "no-artifact", seed_research=True)
        ok &= check(
            "pre-existing artifacts ignored (seeded doc is not this run's output)",
            record["status"] == "workflow_failure"
            and record["interventions"] == runner.MAX_CONTINUATIONS,
            notes)

        record, _, _, _ = run_case(ws, "silent-stop")
        ok &= check(
            "driver continuation (ritual stop answered, counted)",
            record["status"] == "completed" and record["interventions"] == 1,
            notes)

        gt_only = ws / "task-gt-only.md"
        gt_only.write_text(
            f"---\ntask-id: bad\ntarget-sha: {sha}\n---\n\n## Ground truth\n\n{SECRET}\n",
            encoding="utf-8",
        )
        config, _ = build_config(ws, "normal")
        repo, _ = make_git_repo(ws, "gt-only")
        record = runner.run_task(config, "mock", gt_only, repo, ws / "out-gt-only")
        ok &= check(
            "ground-truth-only task refused (no prompt marker)",
            record["status"] == "infra_failure"
            and "refusing" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["backend_cmd"] = [sys.executable, str(HERE / "mock_claude.py"),
                                 "--mode", "no-artifact"]
        docs = []
        for i in range(2):
            doc = ws / f"anon-doc-{i}.md"
            doc.write_text(f"# Anonymized doc {i}\n", encoding="utf-8")
            docs.append(doc)
        judge = ws / "judge-prompt.md"
        judge.write_text("Score this document per the sealed rubric.\n",
                         encoding="utf-8")
        judge_out = ws / "judge-out"
        results = runner.score(config, docs, judge, judge_out)
        judge_files = sorted(judge_out.glob("judge-*.json"))
        ok &= check(
            "fresh pinned judge sessions (distinct session + profile per call)",
            len(results) == 2
            and len({r["session_id"] for r in results}) == 2
            and len({r["profile"] for r in results}) == 2,
            notes)
        ok &= check(
            "judge responses preserved on disk",
            len(judge_files) == 2
            and all("MOCK-VERDICT" in json.loads(
                f.read_text(encoding="utf-8"))["response"] for f in judge_files),
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
