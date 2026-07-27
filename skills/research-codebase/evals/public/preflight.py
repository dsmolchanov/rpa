#!/usr/bin/env python3
"""Synthetic preflight for the eval-runner (pilot plan, prerequisite 5).

Proves every runner capability against the deterministic mock backend on a
throwaway task — offline, CI-runnable, zero model spend. A real-backend
preflight on the throwaway task is still required once before baseline runs.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402

EXPECTED_TREE = {"input_tokens": 140, "output_tokens": 70, "tool_calls": 12}
EXPECTED_MAIN = {"input_tokens": 100, "output_tokens": 50, "tool_calls": 7}
EXPECTED_SUB = {"input_tokens": 40, "output_tokens": 20, "tool_calls": 5}
SECRET = "SECRET-GROUND-TRUTH-MARKER"
SEAL_SHA = None
SEAL_PATH = None


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
                "entrypoint": "/mock-research",
            }
        },
        "backend_cmd": [sys.executable, str(HERE / "mock_claude.py"),
                        "--mode", mode, "--plugin-dir", "{installation}",
                        "--effort", "{effort}"],
        "judge_backend_cmd": [sys.executable, str(HERE / "mock_claude.py"),
                              "--mode", "no-artifact", "--effort", "{effort}"],
        "judge_model": "opus",
        "judge_effort": "high",
        "workflow_abort_exit_codes": [21],
        "nonstandard_config": True,
        "sandbox_cmd": [sys.executable, str(HERE / "mock_sandbox.py"),
                        "{workdir}", "--"],
        "drift_fetch_cmd": [sys.executable, str(HERE / "mock_fetch.py"),
                            "{url}", "{dest}"],
        "seal_package_sha256": SEAL_SHA,
        "seal_manifest": SEAL_PATH,
        "backend_version": "mock-claude 1.0.0",
        "backend_version_cmd": [sys.executable, str(HERE / "mock_claude.py"),
                                "--version"],
        "timeout_seconds": timeout,
    }, install


def write_task(workspace, label, sha):
    task = Path(workspace) / f"task-{label}.md"
    task.write_text(
        f"---\ntask-id: preflight-{label}\ntarget-repo: mock-repo\n"
        f"target-sha: {sha}\nset: preflight\n---\n\n"
        f"## Task prompt\n\nThrowaway preflight task: research the mock subsystem.\n\n"
        f"## Ground truth\n\n{SECRET}\n",
        encoding="utf-8",
    )
    return task


def run_case(workspace, mode, label=None, timeout=20, tamper=False,
             sha_override=None, seed_research=False, use_retries=False,
             extra_env=None):
    label = label or mode
    config, install = build_config(workspace, mode, timeout)
    if tamper:
        (install / "plugin.txt").write_text("tampered\n", encoding="utf-8")
    repo, sha = make_git_repo(workspace, label, seed_research=seed_research)
    task = write_task(workspace, label, sha_override or sha)
    out = Path(workspace) / f"out-{label}"
    echo_dir = Path(workspace) / f"echo-{label}"
    os.environ["MOCK_ECHO_DIR"] = str(echo_dir)
    for key, value in (extra_env or {}).items():
        os.environ[key] = value
    try:
        if use_retries:
            record = runner.run_task_with_retries(config, "mock", task, repo, out)[-1]
        else:
            record = runner.run_task(config, "mock", task, repo, out)
    finally:
        os.environ.pop("MOCK_ECHO_DIR", None)
        for key in (extra_env or {}):
            os.environ.pop(key, None)
    return record, out, echo_dir, sha


def check(name, condition, notes, detail=""):
    notes.append((name, "PASS" if condition else "FAIL", detail))
    return bool(condition)


def run_preflight():
    global SEAL_SHA, SEAL_PATH
    notes = []
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)

        # Sealed judge materials, created up front so every config
        # registers the same seal package hash (part of the config digest).
        judge = ws / "judge-prompt.md"
        judge.write_text("Score this document per the sealed rubric.\n",
                         encoding="utf-8")
        ctx_file = ws / "sealed-context.md"
        ctx_file.write_text(
            "SEALED-CONTEXT: task prompt + ground truth for the sched task\n",
            encoding="utf-8")
        snap_dir = ws / "external-snapshots"
        (snap_dir / "a").mkdir(parents=True)
        (snap_dir / "b").mkdir(parents=True)
        (snap_dir / "a" / "index.html").write_text(
            "<html>SEALED-SNAPSHOT A</html>\n", encoding="utf-8")
        (snap_dir / "b" / "index.html").write_text(
            "<html>SEALED-SNAPSHOT B</html>\n", encoding="utf-8")
        dummy_tasks = []
        dummy_meta = {
            "a": ("1 — subsystem-explanation", "dsmolchanov/rpa"),
            "b": ("3 — narrow where-is", "dsmolchanov/rpa"),
            "c": ("2 — subsystem-explanation, largest repo",
                  "dsmolchanov/neomenu"),
            "d": ("4 — code + thoughts history", "dsmolchanov/neomenu"),
            "e": ("5 — external library context",
                  "dsmolchanov/livekit-voice-agent"),
            "f": ("6 — known-wrong premise",
                  "dsmolchanov/livekit-voice-agent"),
        }
        for c in "abcdef":
            arch, trepo = dummy_meta[c]
            dt = ws / f"t-{c}.md"
            dt.write_text(
                f"---\ntask-id: dummy-{c}\narchetype: \"{arch}\"\n"
                f"target-repo: {trepo}\n"
                f"target-sha: {'0' * 40}\n---\n\n## Task prompt\n\nDummy {c}.\n",
                encoding="utf-8")
            dummy_tasks.append(str(dt))
        d_a, d_b, d_c = dummy_tasks[:3]

        seal_file = ws / "seal-manifest.json"
        seal_files_map = {
            judge.name: hashlib.sha256(judge.read_bytes()).hexdigest(),
            ctx_file.name: hashlib.sha256(ctx_file.read_bytes()).hexdigest(),
            "external-snapshots/a/index.html": hashlib.sha256(
                (snap_dir / "a" / "index.html").read_bytes()).hexdigest(),
            "external-snapshots/b/index.html": hashlib.sha256(
                (snap_dir / "b" / "index.html").read_bytes()).hexdigest(),
        }
        for sealed_task in dummy_tasks:
            seal_files_map[Path(sealed_task).name] = hashlib.sha256(
                Path(sealed_task).read_bytes()).hexdigest()
        seal_file.write_text(json.dumps({"judge_prompts": {
            "scorer": "judge-prompt.md",
            "verifier": "judge-prompt.md",
        }, "task_contexts": {
            "task-sched.md": "sealed-context.md",
            "task-snap.md": "sealed-context.md",
        }, "judge_config": {
            "judge_backend_cmd": [sys.executable,
                                  str(HERE / "mock_claude.py"),
                                  "--mode", "no-artifact",
                                  "--effort", "{effort}"],
            "judge_model": "opus",
            "judge_effort": "high",
        }, "snapshot_sources": {
            "external-snapshots/a/index.html":
                "https://mock.invalid/live/a/index.html",
            "external-snapshots/b/index.html":
                "https://mock.invalid/live/b/index.html",
        }, "files": seal_files_map}), encoding="utf-8")
        SEAL_SHA = hashlib.sha256(seal_file.read_bytes()).hexdigest()
        SEAL_PATH = str(seal_file)

        record, out, echo_dir, sha = run_case(ws, "normal")
        ok &= check("clean run completes", record["status"] == "completed",
                    notes, f"status={record['status']}")
        acc = record.get("accounting", {})
        ok &= check(
            "tree-wide accounting (main/subagent/tree match declared)",
            acc.get("main") == EXPECTED_MAIN
            and acc.get("subagents") == EXPECTED_SUB
            and acc.get("tree") == EXPECTED_TREE
            and acc.get("subagents_spawned") == 1,
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
        ok &= check(
            "workflow entrypoint invoked (not a bare question)",
            prompt_echo.startswith("/mock-research "),
            notes)
        ok &= check(
            "per-node effort capture (pinned via {effort}, echoed by nodes)",
            all(n.get("effort") == "high" for n in record.get("nodes", [])),
            notes)
        plugin_echo = (echo_dir / "plugin-dir.txt").read_text(encoding="utf-8").strip()
        ok &= check(
            "installation mounted at an arm-neutral path, passed to backend",
            plugin_echo
            and Path(plugin_echo).name == "installation"
            and "mock" not in plugin_echo
            and "profiles" in plugin_echo
            and runner.hash_tree(plugin_echo) == record["installation_sha256"],
            notes, Path(plugin_echo).name if plugin_echo else "missing")
        sandbox_echo = (echo_dir / "sandbox.txt").read_text(
            encoding="utf-8").strip()
        ok &= check(
            "evaluated session wrapped by the registered sandbox (workdir)",
            sandbox_echo == record.get("worktree"),
            notes)
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

        modecfg, modeinstall = build_config(ws, "normal")
        orig_mode = (modeinstall / "plugin.txt").stat().st_mode
        os.chmod(modeinstall / "plugin.txt", 0o755)
        moderepo, modesha = make_git_repo(ws, "mode-tamper")
        modetask = write_task(ws, "mode-tamper", modesha)
        record = runner.run_task(modecfg, "mock", modetask, moderepo,
                                 ws / "out-mode-tamper")
        os.chmod(modeinstall / "plugin.txt", orig_mode)
        ok &= check(
            "mode drift (executable bit) blocked as infra (metadata hashed)",
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

        record, _, _, _ = run_case(ws, "wrong-effort")
        ok &= check(
            "effort parity (mismatched node effort invalidates run)",
            record["status"] == "infra_failure"
            and "effort" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "mixed-effort")
        ok &= check(
            "broken effort capture rejected (only some nodes report effort)",
            record["status"] == "infra_failure"
            and "broken effort capture" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "real-stream")
        ok &= check(
            "real Claude stream parsed (cached input categories counted)",
            record["status"] == "completed"
            and record.get("accounting", {}).get("tree") == EXPECTED_TREE
            and record.get("accounting", {}).get("subagents") == EXPECTED_SUB
            and record.get("effort_capture") == "command_pin",
            notes, f"effort_capture={record.get('effort_capture')}")
        ok &= check(
            "distinct subagents counted (two messages, one spawned subagent)",
            record.get("accounting", {}).get("subagents_spawned") == 1,
            notes)

        config, _ = build_config(ws, "normal")
        config["backend_cmd"] = [
            part for part in config["backend_cmd"]
            if part not in ("--effort", "{effort}")
        ]
        repo, pin_sha = make_git_repo(ws, "no-effort-pin")
        task = write_task(ws, "no-effort-pin", pin_sha)
        record = runner.run_task(config, "mock", task, repo, ws / "out-no-effort-pin")
        ok &= check(
            "backend command without {effort} pin refused",
            record["status"] == "infra_failure"
            and "{effort}" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "workflow-abort")
        ok &= check(
            "workflow abort exit counted as workflow failure (not rerun)",
            record["status"] == "workflow_failure"
            and "aborted" in record.get("failure", ""),
            notes)
        ok &= check(
            "workflow abort keeps partial-transcript accounting",
            record.get("accounting", {}).get("tree") == EXPECTED_TREE
            and len(record.get("nodes", [])) == 2
            and record.get("effort_capture") == "per_node",
            notes, json.dumps(record.get("accounting", {}).get("tree")))

        record, _, _, _ = run_case(ws, "abort-wrong-model")
        ok &= check(
            "runtime drift in partial transcript invalidates (not counted)",
            record["status"] == "infra_failure"
            and "differ from registered" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["second"] = dict(config["arms"]["mock"], effort="low")
        repo, par_sha = make_git_repo(ws, "arm-parity")
        task = write_task(ws, "arm-parity", par_sha)
        record = runner.run_task(config, "mock", task, repo, ws / "out-arm-parity")
        ok &= check(
            "arm runtime parity enforced (differing effort across arms refused)",
            record["status"] == "infra_failure"
            and "only installation content" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["second"] = dict(config["arms"]["mock"],
                                        entrypoint="/other-workflow")
        task = write_task(ws, "ep-parity", par_sha)
        record = runner.run_task(config, "mock", task, repo, ws / "out-ep-parity")
        ok &= check(
            "arm entrypoint parity enforced (divergent entrypoint refused)",
            record["status"] == "infra_failure"
            and "entrypoint" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["second"] = dict(config["arms"]["mock"], sha256="0" * 64)
        task = write_task(ws, "all-arms", par_sha)
        record = runner.run_task(config, "mock", task, repo, ws / "out-all-arms")
        ok &= check(
            "every arm installation verified before each run",
            record["status"] == "infra_failure"
            and "second" in record.get("failure", "")
            and "hash mismatch" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["mock"]["forbid_subagents"] = True
        task = write_task(ws, "no-subagent", par_sha)
        record = runner.run_task(config, "mock", task, repo,
                                 ws / "out-no-subagent")
        ok &= check(
            "ablation no-subagent policy enforced at the harness boundary",
            record["status"] == "workflow_failure"
            and "no-subagent policy" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "launch-no-child")
        config["arms"]["mock"]["forbid_subagents"] = True
        task_lnc = write_task(ws, "launch-no-child", par_sha)
        record = runner.run_task(config, "mock", task_lnc, repo,
                                 ws / "out-lnc")
        ok &= check(
            "subagent launch without child output still counts (Task evidence)",
            record["status"] == "workflow_failure"
            and "no-subagent policy" in record.get("failure", "")
            and record.get("accounting", {}).get("subagents_spawned") == 1,
            notes)

        # On a NORMAL arm the same evidence gap is a parity fault: a Task
        # launch whose child emitted no model-bearing node leaves part of
        # the agent tree unvalidated — never accepted as completed.
        config, _ = build_config(ws, "launch-no-child")
        record = runner.run_task(config, "mock", task_lnc, repo,
                                 ws / "out-lnc-parity")
        ok &= check(
            "launch without model-bearing child invalidates the run",
            record["status"] == "infra_failure"
            and "cannot be validated" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        try:
            runner.run_task(config, "no-such-arm", task, repo,
                            ws / "out-bad-arm")
            arm_ok = False
        except runner.InfraFailure as exc:
            arm_ok = "unknown arm" in str(exc)
        except KeyError:
            arm_ok = False
        ok &= check(
            "unknown arm rejected with classified error (no traceback)",
            arm_ok, notes)

        config, _ = build_config(ws, "normal")
        config.pop("nonstandard_config")
        task_topo = write_task(ws, "run-topology", par_sha)
        record = runner.run_task(config, "mock", task_topo, repo,
                                 ws / "out-run-topology")
        ok &= check(
            "run mode requires three-arm topology unless config is dev-marked",
            record["status"] == "infra_failure"
            and "three-arm topology" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        base_arm = config["arms"].pop("mock")
        config["arms"]["baseline"] = dict(base_arm)
        config["arms"]["candidate"] = dict(base_arm)
        config["arms"]["ablation"] = dict(base_arm, forbid_subagents=True)
        config.pop("nonstandard_config")
        config.pop("sandbox_cmd")
        task_sbx = write_task(ws, "sandbox-req", par_sha)
        record = runner.run_task(config, "baseline", task_sbx, repo,
                                 ws / "out-direct-run")
        ok &= check(
            "production config direct run refused (schedule-only execution)",
            record["status"] == "infra_failure"
            and "--run-schedule" in record.get("failure", ""),
            notes)
        record = runner.run_task(config, "baseline", task_sbx, repo,
                                 ws / "out-sandbox-req", scheduled=True)
        ok &= check(
            "production config requires a registered sandbox_cmd",
            record["status"] == "infra_failure"
            and "sandbox_cmd" in record.get("failure", ""),
            notes)
        config["sandbox_cmd"] = ["/usr/bin/env"]
        record = runner.run_task(config, "baseline", task_sbx, repo,
                                 ws / "out-sandbox-noconfine", scheduled=True)
        ok &= check(
            "sandbox command without confinement placeholders refused",
            record["status"] == "infra_failure"
            and "placeholder" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["backend_cmd"] = [
            part for part in config["backend_cmd"]
            if part not in ("--plugin-dir", "{installation}")
        ]
        task = write_task(ws, "no-mount", par_sha)
        record = runner.run_task(config, "mock", task, repo, ws / "out-no-mount")
        ok &= check(
            "backend command without {installation} mount refused",
            record["status"] == "infra_failure"
            and "{installation}" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["second"] = dict(config["arms"]["mock"],
                                        forbid_subagents=True,
                                        schedule_tasks=[d_a, d_b])
        s1 = runner.make_schedule(config, [d_a, d_b, d_c], 3,
                                  seed=42, allow_nonstandard=True)
        s2 = runner.make_schedule(config, [d_a, d_b, d_c], 3,
                                  seed=42, allow_nonstandard=True)
        cell_counts = {}
        for entry in s1["entries"]:
            key = (entry["arm"], entry["task"])
            cell_counts[key] = cell_counts.get(key, 0) + 1
        ok &= check(
            "pre-registered schedule balanced, scoped, seed-deterministic",
            s1 == s2
            and len(s1["entries"]) == 15
            and cell_counts == {("mock", d_a): 3, ("mock", d_b): 3,
                                ("mock", d_c): 3, ("second", d_a): 3,
                                ("second", d_b): 3},
            notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["second"] = dict(config["arms"]["mock"],
                                        schedule_tasks=[d_a])
        try:
            runner.make_schedule(config, [d_a, d_b], 3, seed=42,
                                 allow_nonstandard=True)
            scope_ok = False
        except runner.InfraFailure as exc:
            scope_ok = "reserved for" in str(exc)
        ok &= check(
            "schedule_tasks scoping rejected on non-ablation arms",
            scope_ok, notes)

        config, _ = build_config(ws, "normal")
        config.pop("nonstandard_config")
        try:
            runner.make_schedule(config, [d_a], 2, seed=1)
            rep_ok = False
        except runner.InfraFailure as exc:
            rep_ok = "replicates" in str(exc)
        ok &= check(
            "nonstandard replicate count refused without explicit override",
            rep_ok, notes)

        config, _ = build_config(ws, "normal")
        config.pop("nonstandard_config")
        try:
            runner.make_schedule(config, [d_a], 3, seed=1)
            topo_ok = False
        except runner.InfraFailure as exc:
            topo_ok = "three-arm topology" in str(exc)
        ok &= check(
            "standard schedule requires the registered three-arm topology",
            topo_ok, notes)

        config, _ = build_config(ws, "normal")
        config.pop("nonstandard_config")
        base_arm = config["arms"].pop("mock")
        config["arms"]["baseline"] = dict(base_arm)
        config["arms"]["candidate"] = dict(base_arm)
        config["arms"]["ablation"] = dict(base_arm, forbid_subagents=True)
        six_tasks = list(dummy_tasks)

        dev_cfg, _ = build_config(ws, "normal")
        dev_base = dev_cfg["arms"].pop("mock")
        dev_cfg["arms"]["baseline"] = dict(dev_base)
        dev_cfg["arms"]["candidate"] = dict(dev_base)
        dev_cfg["arms"]["ablation"] = dict(dev_base, forbid_subagents=True,
                                           schedule_tasks=[d_a, d_b])
        try:
            runner.make_schedule(dev_cfg, list(dummy_tasks), 3, seed=1)
            devsched_ok = False
        except runner.InfraFailure as exc:
            devsched_ok = "dev config" in str(exc)
        ok &= check(
            "standard schedule refused from a dev-marked config",
            devsched_ok, notes)
        try:
            runner.make_schedule(config, six_tasks, 3, seed=1)
            abl_ok = False
        except runner.InfraFailure as exc:
            abl_ok = "schedule_tasks" in str(exc)
        config["arms"]["ablation"]["schedule_tasks"] = [d_a, d_b]
        s_abl = runner.make_schedule(config, six_tasks, 3, seed=1)
        ok &= check(
            "ablation arm requires explicit two-task scoping (standard 3-arm ok)",
            abl_ok
            and s_abl["nonstandard"] is False
            and sum(1 for e in s_abl["entries"] if e["arm"] == "ablation") == 6,
            notes)

        config["arms"]["ablation"]["schedule_tasks"] = [d_a, d_c]
        try:
            runner.make_schedule(config, six_tasks, 3, seed=1)
            arch_ok = False
        except runner.InfraFailure as exc:
            arch_ok = "registered archetypes" in str(exc)
        config["arms"]["ablation"]["schedule_tasks"] = [d_a, d_b]
        ok &= check(
            "ablation scope bound to the registered archetypes",
            arch_ok, notes)

        try:
            runner.make_schedule(config, [d_a, d_b], 3, seed=1)
            six_ok = False
        except runner.InfraFailure as exc:
            six_ok = "distinct holdout tasks" in str(exc)
        try:
            runner.make_schedule(config, six_tasks[:5] + [d_a], 3, seed=1)
            six_ok = False
        except runner.InfraFailure as exc:
            six_ok = six_ok and "duplicate task paths" in str(exc)
        ok &= check(
            "standard schedule requires six unique holdout tasks",
            six_ok, notes)

        config, _ = build_config(ws, "normal")
        config.pop("nonstandard_config")
        base_arm = config["arms"].pop("mock")
        config["arms"]["baseline"] = dict(base_arm)
        config["arms"]["canddate"] = dict(base_arm)
        config["arms"]["ablation"] = dict(base_arm, forbid_subagents=True,
                                          schedule_tasks=[d_a, d_b])
        try:
            runner.make_schedule(config, six_tasks, 3, seed=1)
            roles_ok = False
        except runner.InfraFailure as exc:
            roles_ok = "baseline" in str(exc) and "candidate" in str(exc)
        ok &= check(
            "standard topology requires the named baseline/candidate roles",
            roles_ok, notes)

        cov_cfg, _ = build_config(ws, "normal")
        cov_cfg.pop("nonstandard_config")
        cov_base = cov_cfg["arms"].pop("mock")
        cov_cfg["arms"]["baseline"] = dict(cov_base)
        cov_cfg["arms"]["candidate"] = dict(cov_base)
        cov_cfg["arms"]["ablation"] = dict(cov_base, forbid_subagents=True,
                                           schedule_tasks=[d_a, d_b])
        dup_arch = ws / "t-dup-arch.md"
        dup_arch.write_text(
            (ws / "t-f.md").read_text(encoding="utf-8").replace(
                "6 — known-wrong premise", "1 — subsystem-explanation"),
            encoding="utf-8")
        try:
            runner.make_schedule(cov_cfg, six_tasks[:5] + [str(dup_arch)],
                                 3, seed=1)
            cov_ok = False
        except runner.InfraFailure as exc:
            cov_ok = "one task per archetype" in str(exc)
        same_repo_tasks = []
        for c in "abcdef":
            sr = ws / f"t-sr-{c}.md"
            sr.write_text(
                (ws / f"t-{c}.md").read_text(encoding="utf-8").replace(
                    "dsmolchanov/neomenu", "dsmolchanov/rpa").replace(
                    "dsmolchanov/livekit-voice-agent", "dsmolchanov/rpa"),
                encoding="utf-8")
            same_repo_tasks.append(str(sr))
        cov_cfg["arms"]["ablation"]["schedule_tasks"] = [
            same_repo_tasks[0], same_repo_tasks[1]]
        try:
            runner.make_schedule(cov_cfg, same_repo_tasks, 3, seed=1)
            cov_ok2 = False
        except runner.InfraFailure as exc:
            cov_ok2 = "registered repositories" in str(exc)
        fake_tasks = []
        for i, c in enumerate("abcdef"):
            fk = ws / f"t-fake-{c}.md"
            fk.write_text(
                (ws / f"t-{c}.md").read_text(encoding="utf-8").replace(
                    dummy_meta[c][0], f"fake-{i + 1}"),
                encoding="utf-8")
            fake_tasks.append(str(fk))
        cov_cfg["arms"]["ablation"]["schedule_tasks"] = [d_a, d_b]
        try:
            runner.make_schedule(cov_cfg, fake_tasks[:4] + [d_a, d_b],
                                 3, seed=1)
            cov_ok3 = False
        except runner.InfraFailure as exc:
            cov_ok3 = "canonical" in str(exc)
        ok &= check(
            "standard schedule validates the full coverage matrix",
            cov_ok and cov_ok2 and cov_ok3, notes)

        unsealed = ws / "t-unsealed.md"
        unsealed.write_text(
            (ws / "t-f.md").read_text(encoding="utf-8").replace(
                "Dummy f.", "Unsealed impostor task."),
            encoding="utf-8")
        try:
            runner.make_schedule(cov_cfg, six_tasks[:5] + [str(unsealed)],
                                 3, seed=1)
            unsealed_ok = False
        except runner.InfraFailure as exc:
            unsealed_ok = "not sealed" in str(exc)
        ok &= check(
            "unsealed holdout task refused (tasks bound to the atomic seal)",
            unsealed_ok, notes)
        badseal = ws / "seal-garbage.json"
        badseal.write_bytes(b"{not json")
        badseal_cfg = json.loads(json.dumps(cov_cfg))
        badseal_cfg["seal_manifest"] = str(badseal)
        badseal_cfg["seal_package_sha256"] = hashlib.sha256(
            b"{not json").hexdigest()
        try:
            runner.make_schedule(badseal_cfg, six_tasks, 3, seed=1)
            badseal_ok = False
        except runner.InfraFailure as exc:
            badseal_ok = "not valid UTF-8 JSON" in str(exc)
        nofiles_bytes = json.dumps({"files": "nope"}).encode("utf-8")
        nofiles = ws / "seal-nofiles.json"
        nofiles.write_bytes(nofiles_bytes)
        nofiles_cfg = json.loads(json.dumps(badseal_cfg))
        nofiles_cfg["seal_manifest"] = str(nofiles)
        nofiles_cfg["seal_package_sha256"] = hashlib.sha256(
            nofiles_bytes).hexdigest()
        try:
            runner.make_schedule(nofiles_cfg, six_tasks, 3, seed=1)
            nofiles_ok = False
        except runner.InfraFailure as exc:
            nofiles_ok = "must be an object" in str(exc)
        ok &= check(
            "malformed seal manifest classified before dereference",
            badseal_ok and nofiles_ok, notes)
        judged_cfg = json.loads(json.dumps(cov_cfg))
        judged_cfg["judge_model"] = "sonnet"
        try:
            runner.make_schedule(judged_cfg, six_tasks, 3, seed=1)
            sealjudge_ok = False
        except runner.InfraFailure as exc:
            sealjudge_ok = "sealed judge configuration" in str(exc)
        ok &= check(
            "judge settings drifted from the seal refused at scheduling",
            sealjudge_ok, notes)

        s_dev = runner.make_schedule(cov_cfg, six_tasks, 3, seed=2,
                                     allow_nonstandard=True)
        ok &= check(
            "explicit nonstandard override retained in the schedule marker",
            s_dev["nonstandard"] is True, notes)

        devrep_cfg, _ = build_config(ws, "normal")
        try:
            runner.make_schedule(devrep_cfg, [d_a], 0, seed=1,
                                 allow_nonstandard=True)
            rep0_ok = False
        except runner.InfraFailure as exc:
            rep0_ok = "positive integer" in str(exc)
        ok &= check(
            "nonpositive replicate count refused",
            rep0_ok, notes)

        try:
            runner.load_config(ws / "no-such-config.json")
            cfg_ok = False
        except runner.InfraFailure as exc:
            cfg_ok = "cannot read config" in str(exc)
        bad_cfg = ws / "bad-config.json"
        bad_cfg.write_text("{not json", encoding="utf-8")
        try:
            runner.load_config(bad_cfg)
            cfg_ok = False
        except runner.InfraFailure as exc:
            cfg_ok = cfg_ok and "not valid JSON" in str(exc)
        ok &= check(
            "config read errors classified as infrastructure failures",
            cfg_ok, notes)
        empty_cfg = ws / "empty-config.json"
        empty_cfg.write_text("{}", encoding="utf-8")
        try:
            runner.load_config(empty_cfg)
            shape_ok = False
        except runner.InfraFailure as exc:
            shape_ok = "arms" in str(exc)
        noarm_cfg = ws / "noarm-config.json"
        noarm_cfg.write_text(json.dumps(
            {"arms": {"baseline": {"installation_dir": "/x",
                                   "sha256": "y"}},
             "backend_cmd": ["x"]}), encoding="utf-8")
        try:
            runner.load_config(noarm_cfg)
            shape_ok = False
        except runner.InfraFailure as exc:
            shape_ok = shape_ok and "missing required" in str(exc)
        ok &= check(
            "structurally invalid config refused at load (no deep KeyError)",
            shape_ok, notes)
        strflag_cfg = ws / "strflag-config.json"
        base_cfg, _ = build_config(ws, "normal")
        base_cfg["nonstandard_config"] = "false"
        strflag_cfg.write_text(json.dumps(base_cfg), encoding="utf-8")
        try:
            runner.load_config(strflag_cfg)
            flag_ok = False
        except runner.InfraFailure as exc:
            flag_ok = "must be a boolean" in str(exc)
        ok &= check(
            "non-boolean nonstandard_config refused (truthy string trap)",
            flag_ok, notes)

        typed_cfg = ws / "config-badtypes.json"
        base_cfg, _ = build_config(ws, "normal")
        bad_typed = json.loads(json.dumps(base_cfg))
        bad_typed["arms"]["mock"]["model"] = ["opus"]
        typed_cfg.write_text(json.dumps(bad_typed), encoding="utf-8")
        try:
            runner.load_config(typed_cfg)
            typed_ok = False
        except runner.InfraFailure as exc:
            typed_ok = "non-empty string" in str(exc)
        bad_typed2 = json.loads(json.dumps(base_cfg))
        bad_typed2["sandbox_cmd"] = 7
        typed_cfg.write_text(json.dumps(bad_typed2), encoding="utf-8")
        try:
            runner.load_config(typed_cfg)
            typed2_ok = False
        except runner.InfraFailure as exc:
            typed2_ok = "list of" in str(exc)
        ok &= check(
            "wrong-typed config fields refused at load (full schema)",
            typed_ok and typed2_ok, notes)

        config, _ = build_config(ws, "normal")
        repo_s, sha_s = make_git_repo(ws, "sched")
        task_s = write_task(ws, "sched", sha_s)
        sched = runner.make_schedule(config, [str(task_s)], 2, seed=7,
                                     allow_nonstandard=True)
        sched_path = ws / "schedule.json"
        sched_path.write_text(json.dumps(sched), encoding="utf-8")
        repos_map = {"mock-repo": str(repo_s)}
        manifest = runner.run_schedule(config, sched_path, repos_map,
                                       ws / "out-sched", [str(task_s)])
        ok &= check(
            "schedule executor runs every entry in order, records completion",
            manifest["complete"] is True
            and len(manifest["results"]) == 2
            and all(r["status"] == "completed" for r in manifest["results"])
            and (ws / "out-sched" / "schedule-manifest.json").exists(),
            notes)

        manifest_path = ws / "out-sched" / "schedule-manifest.json"
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        dropped_run = m["results"][1]["run_id"]
        m["results"] = m["results"][:1]
        m["complete"] = False
        manifest_path.write_text(json.dumps(m), encoding="utf-8")
        runs_before = len(list((ws / "out-sched").glob("run-*.json")))
        manifest2 = runner.run_schedule(config, sched_path, repos_map,
                                        ws / "out-sched", [str(task_s)])
        runs_after = len(list((ws / "out-sched").glob("run-*.json")))
        # The truncated manifest simulates the crash window between the
        # atomic run-record write and the manifest update: the completed
        # orphan record must be ADOPTED, never executed again — a second
        # backend launch would add an unaccounted observed replicate.
        ok &= check(
            "schedule resume adopts the orphan run record (no extra replicate)",
            manifest2["complete"] is True
            and len(manifest2["results"]) == 2
            and manifest2["results"][1]["run_id"] == dropped_run
            and runs_after == runs_before,
            notes)
        m3 = json.loads(manifest_path.read_text(encoding="utf-8"))
        m3["results"] = m3["results"][:1]
        m3["complete"] = False
        manifest_path.write_text(json.dumps(m3), encoding="utf-8")
        fake_orphan = json.loads(
            (ws / "out-sched" / f"run-{dropped_run}.json")
            .read_text(encoding="utf-8"))
        fake_orphan["run_id"] = "feedfacefeed"
        (ws / "out-sched" / "run-feedfacefeed.json").write_text(
            json.dumps(fake_orphan), encoding="utf-8")
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched", [str(task_s)])
            ambig_ok = False
        except runner.InfraFailure as exc:
            ambig_ok = "ambiguous orphan" in str(exc)
        (ws / "out-sched" / "run-feedfacefeed.json").unlink()
        manifest3 = runner.run_schedule(config, sched_path, repos_map,
                                        ws / "out-sched", [str(task_s)])
        ok &= check(
            "ambiguous orphan run records refused (cannot attribute runs)",
            ambig_ok and manifest3["complete"] is True,
            notes)
        # A record produced under a different task revision or runtime
        # configuration is STALE, not an orphan: adoption requires the
        # record's own immutable bindings to match the current schedule.
        m4 = json.loads(manifest_path.read_text(encoding="utf-8"))
        m4["results"] = m4["results"][:1]
        m4["complete"] = False
        manifest_path.write_text(json.dumps(m4), encoding="utf-8")
        stale_path = ws / "out-sched" / f"run-{dropped_run}.json"
        stale_rec = json.loads(stale_path.read_text(encoding="utf-8"))
        stale_rec["task_sha256"] = "0" * 64
        stale_path.write_text(json.dumps(stale_rec), encoding="utf-8")
        runs_b4 = len(list((ws / "out-sched").glob("run-*.json")))
        manifest4 = runner.run_schedule(config, sched_path, repos_map,
                                        ws / "out-sched", [str(task_s)])
        runs_aft = len(list((ws / "out-sched").glob("run-*.json")))
        ok &= check(
            "stale orphan records not adopted (task/config digest bound)",
            manifest4["complete"] is True
            and manifest4["results"][1]["run_id"] != dropped_run
            and runs_aft == runs_b4 + 1,
            notes)
        # A run journal without a terminal outcome means the backend may
        # have executed: neither adoptable nor safely re-runnable.
        m5 = json.loads(manifest_path.read_text(encoding="utf-8"))
        kept_run = m5["results"][0]["run_id"]
        m5["results"] = m5["results"][:1]
        m5["complete"] = False
        manifest_path.write_text(json.dumps(m5), encoding="utf-8")
        cur_rec = json.loads(
            (ws / "out-sched" / f"run-{kept_run}.json")
            .read_text(encoding="utf-8"))
        inprog = dict(cur_rec)
        inprog["run_id"] = "beefbeefbeef"
        inprog["status"] = "in_progress"
        for key in ("accounting", "nodes", "artifact_sha256", "failure"):
            inprog.pop(key, None)
        inprog_path = ws / "out-sched" / "run-beefbeefbeef.json"
        inprog_path.write_text(json.dumps(inprog), encoding="utf-8")
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched", [str(task_s)])
            inprog_ok = False
        except runner.InfraFailure as exc:
            inprog_ok = "in-progress run journal" in str(exc)
        inprog_path.unlink()
        manifest5 = runner.run_schedule(config, sched_path, repos_map,
                                        ws / "out-sched", [str(task_s)])
        ok &= check(
            "in-progress run journal blocks the schedule (uncertain outcome)",
            inprog_ok and manifest5["complete"] is True,
            notes)

        bad = dict(sched)
        bad["entries"] = sched["entries"][:-1]
        bad_path = ws / "schedule-bad.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            runner.run_schedule(config, bad_path, repos_map,
                                ws / "out-sched-bad", [str(task_s)])
            sched_ok = False
        except runner.InfraFailure as exc:
            sched_ok = "reconstructed" in str(exc)
        ok &= check(
            "edited schedule refused (reconstructed from registered config)",
            sched_ok, notes)

        config, _ = build_config(ws, "normal")
        config["arms"]["mock"]["model"] = "uniformly-changed"
        config["arms"]["mock"]["effort"] = "low"
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched-drift", [str(task_s)])
            bind_ok = False
        except runner.InfraFailure as exc:
            bind_ok = "config digest mismatch" in str(exc)
        ok &= check(
            "schedule bound to registered config (uniform drift refused)",
            bind_ok, notes)

        config, _ = build_config(ws, "normal")
        m2 = json.loads(manifest_path.read_text(encoding="utf-8"))
        orig_sdig = m2["schedule_digest"]
        m2["schedule_digest"] = "0" * 64
        manifest_path.write_text(json.dumps(m2), encoding="utf-8")
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched", [str(task_s)])
            resume_ok = False
        except runner.InfraFailure as exc:
            resume_ok = "schedule digest mismatch" in str(exc)
        manifest_path.write_text(
            json.dumps(m2 | {"schedule_digest": orig_sdig}), encoding="utf-8")
        ok &= check(
            "resumed manifest bound to the full schedule digest",
            resume_ok, notes)

        try:
            runner.run_schedule(config, sched_path, {"other-repo": str(repo_s)},
                                ws / "out-sched-route", [str(task_s)])
            route_ok = False
        except runner.InfraFailure as exc:
            route_ok = "no registered clone" in str(exc)
        ok &= check(
            "schedule entries routed to their task's registered clone",
            route_ok, notes)
        qual_task = ws / "task-qualified.md"
        qual_task.write_text(
            f"---\ntask-id: q\ntarget-repo: dsmolchanov/mock-repo\n"
            f"target-sha: {'0' * 40}\n---\n\n## Task prompt\n\nQ.\n",
            encoding="utf-8")
        route_a = runner.resolve_repo(qual_task, {"mock-repo": "/clone-a"})
        route_b = runner.resolve_repo(
            qual_task, {"dsmolchanov/mock-repo": "/clone-b"})
        ok &= check(
            "qualified target-repo routed via canonical mapping keys",
            route_a == "/clone-a" and route_b == "/clone-b", notes)

        original_task_bytes = Path(task_s).read_bytes()
        Path(task_s).write_bytes(original_task_bytes + b"\n<!-- edited -->\n")
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched-taskdrift", [str(task_s)])
            tdrift_ok = False
        except runner.InfraFailure as exc:
            tdrift_ok = "reconstructed" in str(exc)
        Path(task_s).write_bytes(original_task_bytes)
        ok &= check(
            "schedule bound to task contents (edited task refused)",
            tdrift_ok, notes)

        garbage_sched = ws / "schedule-garbage.json"
        garbage_sched.write_text("{not json", encoding="utf-8")
        try:
            runner.run_schedule(config, garbage_sched, repos_map,
                                ws / "out-sched-garbage", [str(task_s)])
            gsched_ok = False
        except runner.InfraFailure as exc:
            gsched_ok = "not valid JSON" in str(exc)
        try:
            runner.run_schedule(config, ws / "no-such-schedule.json",
                                repos_map, ws / "out-sched-missing",
                                [str(task_s)])
            gsched_ok = False
        except runner.InfraFailure as exc:
            gsched_ok = gsched_ok and "cannot read" in str(exc)
        ok &= check(
            "malformed or missing schedule files classified as infra",
            gsched_ok, notes)

        config, _ = build_config(ws, "normal")
        task_ret = write_task(ws, "retries", par_sha)
        config["max_infra_retries"] = -1
        try:
            runner.run_task_with_retries(config, "mock", task_ret, repo,
                                         ws / "out-neg-retries")
            retries_ok = False
        except runner.InfraFailure as exc:
            retries_ok = "nonnegative integer" in str(exc)
        config["max_infra_retries"] = "many"
        try:
            runner.run_task_with_retries(config, "mock", task_ret, repo,
                                         ws / "out-bad-retries")
            retries_ok = False
        except runner.InfraFailure as exc:
            retries_ok = retries_ok and "nonnegative integer" in str(exc)
        config["max_infra_retries"] = 0.5
        try:
            runner.run_task_with_retries(config, "mock", task_ret, repo,
                                         ws / "out-float-retries")
            retries_ok = False
        except runner.InfraFailure as exc:
            retries_ok = retries_ok and "nonnegative integer" in str(exc)
        ok &= check(
            "invalid max_infra_retries rejected as classified infra failure",
            retries_ok, notes)

        config, _ = build_config(ws, "normal")
        config["timeout_seconds"] = 0
        record = runner.run_task(config, "mock", task_ret, repo,
                                 ws / "out-zero-timeout")
        ok &= check(
            "nonpositive timeout rejected as classified infra failure",
            record["status"] == "infra_failure"
            and "positive number" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["workflow_abort_exit_codes"] = ["21"]
        record = runner.run_task(config, "mock", task_ret, repo,
                                 ws / "out-str-aborts")
        abort_ok = (record["status"] == "infra_failure"
                    and "list of integers" in record.get("failure", ""))
        config["workflow_abort_exit_codes"] = 21
        record = runner.run_task(config, "mock", task_ret, repo,
                                 ws / "out-scalar-aborts")
        ok &= check(
            "invalid workflow_abort_exit_codes rejected (typed list required)",
            abort_ok and record["status"] == "infra_failure"
            and "list of integers" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config["backend_version"] = "other-version 9.9"
        task_v = write_task(ws, "ver-mismatch", par_sha)
        record = runner.run_task(config, "mock", task_v, repo, ws / "out-ver")
        ok &= check(
            "backend version drift blocked before the run",
            record["status"] == "infra_failure"
            and "version" in record.get("failure", "")
            and "differs from registered" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        config.pop("backend_version")
        record = runner.run_task(config, "mock", task_v, repo, ws / "out-ver2")
        ok &= check(
            "unregistered backend version refused",
            record["status"] == "infra_failure"
            and "backend_version" in record.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        repo_r, sha_r = make_git_repo(ws, "relout")
        task_r = write_task(ws, "relout", sha_r)
        old_cwd = os.getcwd()
        os.chdir(ws)
        try:
            record = runner.run_task(config, "mock", task_r, repo_r,
                                     "rel-out-dir")
        finally:
            os.chdir(old_cwd)
        ok &= check(
            "relative --output resolved (worktree verified and removed)",
            record["status"] == "completed"
            and Path(record["worktree"]).is_absolute()
            and not Path(record["worktree"]).exists(),
            notes)

        record, _, _, _ = run_case(ws, "infra-crash")
        ok &= check("infra failure classified (backend crash)",
                    record["status"] == "infra_failure", notes)

        state_file = ws / "flaky-state"
        record, _, _, _ = run_case(
            ws, "flaky-infra", use_retries=True,
            extra_env={"MOCK_STATE_FILE": str(state_file)})
        ok &= check(
            "infra failure auto re-executed (bounded retry completes the run)",
            record["status"] == "completed" and record.get("attempt") == 2,
            notes, f"attempt={record.get('attempt')}")
        record, _, _, _ = run_case(ws, "garbage")
        ok &= check("infra failure classified (unparseable output)",
                    record["status"] == "infra_failure", notes)

        record, _, _, _ = run_case(ws, "timeout", timeout=2)
        ok &= check("workflow failure classified (timeout, not replaced)",
                    record["status"] == "workflow_failure", notes)

        record, _, echo_tc, _ = run_case(ws, "timeout-with-child", timeout=2)
        child_pid = int((echo_tc / "child-pid.txt").read_text(
            encoding="utf-8").strip())
        def _child_gone(pid):
            # A zombie can linger when PID 1 does not reap orphans: it can
            # no longer run or touch the worktree, so Z counts as gone.
            try:
                with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                    state = fh.read().rsplit(")", 1)[1].split()[0]
                return state == "Z"
            except OSError:
                return True
        child_dead = False
        for _ in range(100):
            if _child_gone(child_pid):
                child_dead = True
                break
            time.sleep(0.1)
        ok &= check(
            "timeout kills the whole session process tree (child reaped)",
            record["status"] == "workflow_failure" and child_dead,
            notes)

        # A workflow-shaped failure (timeout/abort) with an empty transcript
        # can neither be counted (no parity evidence) nor auto-re-executed
        # (counted failures are never replaced): it must BLOCK — one
        # attempt, blocking flag set, classified infra.
        record, _, _, _ = run_case(ws, "bad-artifact")
        ok &= check(
            "nonconforming artifact is a counted workflow failure (gate)",
            record["status"] == "workflow_failure"
            and "artifact contract" in record.get("failure", "")
            and record.get("artifact_defects"),
            notes)

        fn_doc = ws / "notes.md"
        fn_doc.write_text(
            (HERE / "fixtures" / "artifact-valid.md").read_text(
                encoding="utf-8"), encoding="utf-8")
        fn_bad = runner.artifact_validator.validate(
            fn_doc, enforce_filename=True)
        fn_good_doc = ws / "2026-07-26-fixture-copy.md"
        fn_good_doc.write_text(fn_doc.read_text(encoding="utf-8"),
                               encoding="utf-8")
        fn_good = runner.artifact_validator.validate(
            fn_good_doc, enforce_filename=True)
        anon_marker_doc = ws / "2026-07-26-marker-raw.md"
        anon_marker_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "git_commit: '0000000000000000000000000000000000000000'",
                "git_commit: '[anonymized:evil]'"),
            encoding="utf-8")
        marker_strict = runner.artifact_validator.validate(
            anon_marker_doc, enforce_filename=True)
        marker_lenient = runner.artifact_validator.validate(
            anon_marker_doc, allow_anonymized=True)
        free_marker_doc = ws / "2026-07-26-marker-free.md"
        free_marker_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "researcher: Fixture Researcher",
                "researcher: '[anonymized:evil]'", 1),
            encoding="utf-8")
        free_strict = runner.artifact_validator.validate(
            free_marker_doc, enforce_filename=True)
        script_date_doc = ws / "2026-07-26-script-date.md"
        script_date_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "date: 2026-07-27T00:00:00Z",
                "date: '2026-07-27 00:00:00 UTC'", 1),
            encoding="utf-8")
        script_date_ok = not runner.artifact_validator.validate(
            script_date_doc)
        fab_doc = ws / "2026-07-26-fab-sha.md"
        fab_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "git_commit: '0000000000000000000000000000000000000000'",
                "git_commit: '" + "0" * 12 + "f" * 28 + "'", 1),
            encoding="utf-8")
        fab_bad = runner.artifact_validator.validate(
            fab_doc, expected_git_commit="0" * 40)
        bodymeta_doc = ws / "2026-07-26-bodymeta.md"
        bodymeta_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "**Git Commit**: 0000000000000000000000000000000000000000",
                "**Git Commit**: deadbeef", 1),
            encoding="utf-8")
        bodymeta_bad = runner.artifact_validator.validate(
            bodymeta_doc, expected_git_commit="0" * 40)
        impossible_doc = ws / "2026-07-26-impossible.md"
        impossible_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "date: 2026-07-27T00:00:00Z",
                "date: '2026-99-99T29:61:00Z'", 1).replace(
                "last_updated: 2026-07-27",
                "last_updated: '2026-13-40'", 1),
            encoding="utf-8")
        impossible_bad = runner.artifact_validator.validate(impossible_doc)
        offset_doc = ws / "2026-07-26-offset-date.md"
        offset_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "date: 2026-07-27T00:00:00Z",
                "date: '2026-07-27 03:00:00 +0300'", 1),
            encoding="utf-8")
        offset_ok = not runner.artifact_validator.validate(offset_doc)
        timeshift_doc = ws / "2026-07-26-timeshift.md"
        timeshift_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "**Date**: 2026-07-27T00:00:00Z",
                "**Date**: 2026-07-27T05:00:00Z", 1),
            encoding="utf-8")
        timeshift_bad = runner.artifact_validator.validate(timeshift_doc)
        prose_doc = ws / "2026-07-26-prose-block.md"
        prose_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "**Researcher**: Fixture Researcher",
                "Interleaved prose.\n**Researcher**: Fixture Researcher",
                1),
            encoding="utf-8")
        prose_bad = runner.artifact_validator.validate(prose_doc)
        hashhead_doc = ws / "2026-07-26-hashhead.md"
        hashhead_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "## Summary", "## Summary#", 1),
            encoding="utf-8")
        hashhead_bad = runner.artifact_validator.validate(hashhead_doc)
        import builtins as _bi
        import importlib.util as _ilu
        _real_import = _bi.__import__

        def _no_yaml(name, *a, **k):
            if name == "yaml":
                raise ImportError("blocked for fallback probe")
            return _real_import(name, *a, **k)

        _bi.__import__ = _no_yaml
        try:
            _spec = _ilu.spec_from_file_location(
                "va_noyaml", HERE / "validate_artifact.py")
            va_noyaml = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(va_noyaml)
        finally:
            _bi.__import__ = _real_import
        unq_doc = ws / "2026-07-26-unquoted.md"
        unq_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                'topic: "Fixture topic (synthetic)"',
                'topic: "unterminated', 1),
            encoding="utf-8")
        unq_bad = va_noyaml.validate(unq_doc)
        fallback_valid_ok = not va_noyaml.validate(fn_doc)
        boolid_doc = ws / "2026-07-26-boolid.md"
        boolid_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "researcher: Fixture Researcher",
                "researcher: false", 1).replace(
                "**Researcher**: Fixture Researcher",
                "**Researcher**: false", 1),
            encoding="utf-8")
        boolid_bad = runner.artifact_validator.validate(boolid_doc)
        boolid_fallback_bad = va_noyaml.validate(boolid_doc)
        flowmap_doc = ws / "2026-07-26-flowmap.md"
        flowmap_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "tags: [research, fixture]",
                "tags: [foo: bar]", 1),
            encoding="utf-8")
        flowmap_bad = runner.artifact_validator.validate(flowmap_doc)
        flowmap_fallback_bad = va_noyaml.validate(flowmap_doc)
        flowbool_doc = ws / "2026-07-26-flowbool.md"
        flowbool_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "tags: [research, fixture]",
                "tags: [true, fixture]", 1),
            encoding="utf-8")
        flowbool_bad = runner.artifact_validator.validate(flowbool_doc)
        flowbool_fallback_bad = va_noyaml.validate(flowbool_doc)
        try:
            runner.canonical_repo_name("..")
            dotdot_ok = False
        except runner.InfraFailure:
            dotdot_ok = True
        try:
            runner.canonical_repo_name("owner/..")
            dotpath_ok = False
        except runner.InfraFailure:
            dotpath_ok = True
        baddate_doc = ws / "2026-99-99-baddate.md"
        baddate_doc.write_text(fn_doc.read_text(encoding="utf-8"),
                               encoding="utf-8")
        baddate_bad = runner.artifact_validator.validate(
            baddate_doc, enforce_filename=True)
        ok &= check(
            "filename contract enforced; raw anonymization markers rejected",
            any("basename" in e for e in fn_bad)
            and not fn_good
            and any("git_commit" in e for e in marker_strict)
            and not marker_lenient
            and any("researcher" in e and "anonymization marker" in e
                    for e in free_strict)
            and script_date_ok
            and any("target-sha" in e for e in fab_bad)
            and any("**Git Commit**" in e for e in bodymeta_bad)
            and any("date" in e for e in impossible_bad)
            and any("last_updated" in e for e in impossible_bad)
            and offset_ok
            and any("different instants" in e for e in timeshift_bad)
            and any("only the five metadata lines" in e
                    for e in prose_bad)
            and any("## Summary" in e for e in hashhead_bad)
            and any("unmatched quote" in e for e in unq_bad)
            and fallback_valid_ok
            and any("researcher" in e and "must be a string" in e
                    for e in boolid_bad)
            and any("researcher" in e and "must be a string" in e
                    for e in boolid_fallback_bad)
            and any("tags" in e for e in flowmap_bad)
            and any("tags" in e for e in flowmap_fallback_bad)
            and any("tags" in e for e in flowbool_bad)
            and any("tags" in e for e in flowbool_fallback_bad)
            and dotdot_ok and dotpath_ok
            and any("calendar" in e for e in baddate_bad),
            notes)

        meta_script = (HERE.parents[3] / "scripts"
                       / "spec_metadata.sh")
        det_repo, det_sha = make_git_repo(ws, "detached-meta")
        det_wt = runner.make_worktree(det_repo, det_sha, ws / "detmeta",
                                      name="mock-repo")
        meta_out = subprocess.run(["bash", str(meta_script)],
                                  cwd=det_wt, capture_output=True,
                                  text=True)
        runner.remove_worktree(det_repo, det_wt)
        branch_lines = [l for l in meta_out.stdout.splitlines()
                        if l.startswith("Current Branch Name:")]
        ok &= check(
            "metadata script supplies branch identity in detached worktrees",
            meta_out.returncode == 0 and bool(branch_lines)
            and "detached@" in branch_lines[0],
            notes)

        record, _, _, _ = run_case(ws, "stale-artifact")
        ok &= check(
            "artifact metadata bound to the run's pinned checkout",
            record["status"] == "workflow_failure"
            and "target-sha" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "hang-silent", timeout=2,
                                   use_retries=True)
        ok &= check(
            "evidence-less workflow failure blocks (not counted, no auto-rerun)",
            record["status"] == "infra_failure"
            and record.get("blocking") is True
            and record.get("attempt") == 1
            and "parity evidence" in record.get("failure", ""),
            notes)

        record, _, _, _ = run_case(ws, "slow-no-artifact", timeout=2)
        ok &= check(
            "run-level deadline shared across continuations (no reset)",
            record["status"] == "infra_failure"
            and "parity evidence" in record.get("failure", "")
            and record.get("wall_seconds", 99) < 3
            and record["interventions"] == 1,
            notes, f"wall={record.get('wall_seconds')}")

        record, _, _, _ = run_case(ws, "no-artifact", seed_research=True)
        ok &= check(
            "pre-existing artifacts ignored (seeded doc is not this run's output)",
            record["status"] == "workflow_failure"
            and record["interventions"] == runner.MAX_CONTINUATIONS,
            notes)
        sessions = 1 + runner.MAX_CONTINUATIONS
        acc = record.get("accounting", {})
        ok &= check(
            "failed-run accounting preserved (workflow failure keeps full cost)",
            acc.get("tree", {}).get("input_tokens")
            == sessions * EXPECTED_TREE["input_tokens"]
            and len(record.get("nodes", [])) == sessions * 2
            and "wall_seconds" in record,
            notes, json.dumps(acc.get("tree")))
        stops = record.get("interventions_log", [])
        ok &= check(
            "final unanswered stop recorded on exhausted runs",
            len(stops) == sessions
            and all(s["answered"] for s in stops[:-1])
            and stops[-1]["answered"] is False,
            notes, f"{len(stops)} stops")

        record, _, _, _ = run_case(ws, "silent-stop")
        ok &= check(
            "driver continuation (ritual stop answered, counted)",
            record["status"] == "completed" and record["interventions"] == 1,
            notes)
        stops = record.get("interventions_log", [])
        ok &= check(
            "pre-artifact stop response preserved and classified",
            len(stops) == 1
            and "Shall I proceed" in stops[0].get("response", "")
            and stops[0].get("classification") == "question",
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

        no_marker = ws / "task-no-marker.md"
        no_marker.write_text(
            f"---\ntask-id: nm\ntarget-sha: {sha}\n---\n\nJust a bare question.\n",
            encoding="utf-8",
        )
        record = runner.run_task(config, "mock", no_marker, repo,
                                 ws / "out-no-marker")
        ok &= check(
            "marker-less task refused (prompt marker required unconditionally)",
            record["status"] == "infra_failure"
            and "refusing" in record.get("failure", ""),
            notes)

        missing_task = ws / "task-does-not-exist.md"
        record = runner.run_task(config, "mock", missing_task, repo,
                                 ws / "out-missing-task")
        binary_task = ws / "task-binary.md"
        binary_task.write_bytes(b"\xff\xfe\x00 not utf-8")
        record_bin = runner.run_task(config, "mock", binary_task, repo,
                                     ws / "out-binary-task")
        ok &= check(
            "missing or non-UTF-8 task file classified as infra (no traceback)",
            record["status"] == "infra_failure"
            and "cannot read task file" in record.get("failure", "")
            and record_bin["status"] == "infra_failure"
            and "cannot read task file" in record_bin.get("failure", ""),
            notes)

        config, _ = build_config(ws, "normal")
        docs = []
        for i in range(2):
            doc = ws / f"anon-doc-{i}.md"
            doc.write_text(f"# Anonymized doc {i}\n", encoding="utf-8")
            docs.append(doc)
        judge_out = ws / "judge-out"
        placeholder_cfg = dict(config)
        placeholder_cfg.pop("judge_backend_cmd")
        try:
            runner.score(placeholder_cfg, docs, judge, ws / "judge-bad",
                         scoring_seed=5, allow_unscheduled=True)
            guard_ok = False
        except runner.InfraFailure as exc:
            guard_ok = "mount-free" in str(exc)
        ok &= check(
            "judge command placeholder guard (mount-free required)",
            guard_ok, notes)
        wrongjudge_cfg = dict(config)
        wrongjudge_cfg["judge_backend_cmd"] = [
            sys.executable, str(HERE / "mock_claude.py"),
            "--mode", "wrong-model", "--effort", "{effort}"]
        try:
            runner.score(wrongjudge_cfg, docs, judge, ws / "judge-wrong",
                         scoring_seed=5, allow_unscheduled=True)
            judge_parity_ok = False
        except runner.InfraFailure as exc:
            judge_parity_ok = "differ from registered" in str(exc)
        ok &= check(
            "judge model parity (mismatched judge model rejected)",
            judge_parity_ok, notes)
        raw_doc = ws / "run-deadbeef-raw.md"
        raw_doc.write_text(
            "---\nresearcher: Mock Researcher\ngit_commit: deadbeef\n---\n\n"
            "**Researcher**: Mock Researcher\n", encoding="utf-8")
        leaky_doc = ws / "leaky-report.md"
        leaky_doc.write_text(
            "---\nresearcher: Mock Researcher\n---\n\n# Report\n",
            encoding="utf-8")
        blind_ok = True
        for bad_doc in (raw_doc, leaky_doc):
            try:
                runner.score(config, [bad_doc], judge, ws / "judge-blind",
                             scoring_seed=5, allow_unscheduled=True)
                blind_ok = False
            except runner.InfraFailure as exc:
                blind_ok &= "blind scoring" in str(exc) or "anonymized copy" in str(exc)
        ok &= check(
            "raw/fingerprint-bearing documents refused in score mode",
            blind_ok, notes)
        results = runner.score(config, docs, judge, judge_out, scoring_seed=5,
                               allow_unscheduled=True)
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
        iso_ok = True
        for r in results:
            cwd = Path(r["cwd"])
            settings = json.loads(
                (Path(r["profile"]) / "settings.json").read_text(encoding="utf-8"))
            iso_ok &= not str(cwd).startswith(str(ws))
            iso_ok &= list(cwd.iterdir()) == []
            iso_ok &= bool(settings.get("permissions", {}).get("deny"))
        ok &= check(
            "blind judge isolated (empty cwd outside run tree, fs tools denied)",
            iso_ok, notes)
        try:
            runner.score(config, docs, judge, judge_out, scoring_seed=5,
                         allow_unscheduled=True)
            second_ok = False
        except runner.InfraFailure as exc:
            second_ok = "already complete" in str(exc)
        ok &= check(
            "completed judge batch refuses a second pass (atomic batches)",
            second_ok
            and len(sorted(judge_out.glob("judge-*.json"))) == 2,
            notes)

        resume_out = ws / "judge-batch-resume"
        r1 = runner.score(config, docs, judge, resume_out, scoring_seed=5,
                          allow_unscheduled=True)
        sm_path = resume_out / "scoring-scorer-manifest.json"
        sm = json.loads(sm_path.read_text(encoding="utf-8"))
        sm["complete"] = False
        sm["results"] = sm["results"][:1]
        sm_path.write_text(json.dumps(sm), encoding="utf-8")
        r2 = runner.score(config, docs, judge, resume_out, scoring_seed=5,
                          allow_unscheduled=True)
        sm_after = json.loads(sm_path.read_text(encoding="utf-8"))
        ok &= check(
            "interrupted judge batch resumes under the same scoring id",
            len(r2) == 2
            and r2[0]["session_id"] == r1[0]["session_id"]
            and sm_after["complete"] is True
            and sm_after["scoring_id"] == sm["scoring_id"],
            notes)
        sm_after["complete"] = False
        sm_path.write_text(json.dumps(sm_after), encoding="utf-8")
        try:
            runner.score(config, docs, judge, resume_out, scoring_seed=6,
                         allow_unscheduled=True)
            ident_ok = False
        except runner.InfraFailure as exc:
            ident_ok = "different identity" in str(exc)
        ok &= check(
            "judge batch with a different identity refused (no mixing)",
            ident_ok, notes)
        try:
            runner.score(config, list(reversed(docs)), judge, resume_out,
                         scoring_seed=5, allow_unscheduled=True)
            reorder_ok = False
        except runner.InfraFailure as exc:
            reorder_ok = "different identity" in str(exc)
        ok &= check(
            "reordered documents on resume refused (ordered identity)",
            reorder_ok, notes)
        rec_out = ws / "judge-batch-reconcile"
        q1 = runner.score(config, docs, judge, rec_out, scoring_seed=5,
                          allow_unscheduled=True)
        smp = rec_out / "scoring-scorer-manifest.json"
        smj = json.loads(smp.read_text(encoding="utf-8"))
        smj["complete"] = False
        smj["results"] = []
        smp.write_text(json.dumps(smj), encoding="utf-8")
        q2 = runner.score(config, docs, judge, rec_out, scoring_seed=5,
                          allow_unscheduled=True)
        ok &= check(
            "orphaned judge records adopted on resume (no second session)",
            [r["session_id"] for r in q2] == [r["session_id"] for r in q1],
            notes)
        # A corrupted or hand-edited scoring manifest must never smuggle an
        # invented score past the resumed judge loop: each resumed slot is
        # revalidated against its atomic judge record.
        forged_out = ws / "judge-batch-forged"
        runner.score(config, docs, judge, forged_out, scoring_seed=5,
                     allow_unscheduled=True)
        fmp = forged_out / "scoring-scorer-manifest.json"
        fm = json.loads(fmp.read_text(encoding="utf-8"))
        fm["complete"] = False
        fm["results"][0]["response"] = "FORGED-VERDICT: coverage 10/10"
        fmp.write_text(json.dumps(fm), encoding="utf-8")
        try:
            runner.score(config, docs, judge, forged_out, scoring_seed=5,
                         allow_unscheduled=True)
            forged_ok = False
        except runner.InfraFailure as exc:
            forged_ok = "judge record" in str(exc)
        ok &= check(
            "edited manifest result refused on resume (judge-record binding)",
            forged_ok, notes)
        gone_out = ws / "judge-batch-gone-record"
        runner.score(config, docs, judge, gone_out, scoring_seed=5,
                     allow_unscheduled=True)
        gmp = gone_out / "scoring-scorer-manifest.json"
        gm = json.loads(gmp.read_text(encoding="utf-8"))
        gm["complete"] = False
        gmp.write_text(json.dumps(gm), encoding="utf-8")
        (gone_out / f"judge-{gm['scoring_id']}-0.json").unlink()
        try:
            runner.score(config, docs, judge, gone_out, scoring_seed=5,
                         allow_unscheduled=True)
            gone_ok = False
        except runner.InfraFailure as exc:
            gone_ok = "judge record" in str(exc)
        ok &= check(
            "missing judge record on resume refused (no unbacked scores)",
            gone_ok, notes)
        try:
            runner.score(config, [ws / "no-such-doc.md"], judge,
                         ws / "judge-missing-doc", scoring_seed=5,
                         allow_unscheduled=True)
            missdoc_ok = False
        except runner.InfraFailure as exc:
            missdoc_ok = "cannot read scoring document" in str(exc)
        bad_doc = ws / "binary-doc.md"
        bad_doc.write_bytes(b"\xff\xfe\x00 not utf-8")
        try:
            runner.score(config, [bad_doc], judge, ws / "judge-binary-doc",
                         scoring_seed=5, allow_unscheduled=True)
            bindoc_ok = False
        except runner.InfraFailure as exc:
            bindoc_ok = "cannot read scoring document" in str(exc)
        ok &= check(
            "missing or non-UTF-8 scoring document classified as infra",
            missdoc_ok and bindoc_ok, notes)
        malformed_out = ws / "judge-batch-malformed"
        malformed_out.mkdir()
        (malformed_out / "scoring-scorer-manifest.json").write_text(
            "{truncated", encoding="utf-8")
        try:
            runner.score(config, docs, judge, malformed_out, scoring_seed=5,
                         allow_unscheduled=True)
            malformed_ok = False
        except runner.InfraFailure as exc:
            malformed_ok = "scoring batch manifest" in str(exc)
        ok &= check(
            "malformed scoring batch manifest classified as infra",
            malformed_ok, notes)
        # The scoring id must survive a crash BEFORE the first judge record
        # lands: the batch state is persisted up front, so a restart resumes
        # under the same id instead of re-judging under a fresh one.
        flaky_out = ws / "judge-batch-preinit"
        flaky_cfg = json.loads(json.dumps(config))
        flaky_cfg["judge_backend_cmd"] = [
            "flaky-infra" if p == "no-artifact" else p
            for p in flaky_cfg["judge_backend_cmd"]]
        state_file = ws / "judge-flaky-state.txt"
        os.environ["MOCK_STATE_FILE"] = str(state_file)
        try:
            try:
                runner.score(flaky_cfg, docs, judge, flaky_out,
                             scoring_seed=5, allow_unscheduled=True)
                pre_ok = False
            except runner.InfraFailure:
                pre_ok = (flaky_out
                          / "scoring-scorer-manifest.json").exists()
            sid_crash = json.loads(
                (flaky_out / "scoring-scorer-manifest.json")
                .read_text(encoding="utf-8"))["scoring_id"]
            flaky_res = runner.score(flaky_cfg, docs, judge, flaky_out,
                                     scoring_seed=5, allow_unscheduled=True)
        finally:
            os.environ.pop("MOCK_STATE_FILE", None)
        sm_flaky = json.loads(
            (flaky_out / "scoring-scorer-manifest.json")
            .read_text(encoding="utf-8"))
        ok &= check(
            "scoring id persisted before the first judge (crash-safe resume)",
            pre_ok and len(flaky_res) == 2
            and sm_flaky["scoring_id"] == sid_crash
            and sm_flaky["complete"] is True,
            notes)
        bom_doc = ws / "bom-doc.md"
        bom_doc.write_text(
            "\ufeff---\nresearcher: Real Name\n---\n\nbody\n",
            encoding="utf-8")
        try:
            runner.assert_blind_scorable(bom_doc)
            bom_ok = False
        except runner.InfraFailure as exc:
            bom_ok = "not anonymized" in str(exc)
        off_doc = ws / "offset-doc.md"
        off_doc.write_text(
            "\n---\ngit_commit: deadbeef\n---\n\nbody\n",
            encoding="utf-8")
        try:
            runner.assert_blind_scorable(off_doc)
            off_ok = False
        except runner.InfraFailure as exc:
            off_ok = "not anonymized" in str(exc)
        anon_bom = runner.anonymize(
            "\ufeff---\nresearcher: Real Name\n---\n\nbody\n", "tid")
        ok &= check(
            "fingerprints behind BOM/offset frontmatter refused and masked",
            bom_ok and off_ok
            and "Real Name" not in anon_bom
            and "[anonymized:tid]" in anon_bom,
            notes)
        pend_out = ws / "judge-batch-pending"
        p1 = runner.score(config, docs, judge, pend_out, scoring_seed=5,
                          allow_unscheduled=True)
        pmp = pend_out / "scoring-scorer-manifest.json"
        pm = json.loads(pmp.read_text(encoding="utf-8"))
        pm["complete"] = False
        pm["results"] = []
        pmp.write_text(json.dumps(pm), encoding="utf-8")
        psid = pm["scoring_id"]
        (pend_out / f"judge-{psid}-0.json").unlink()
        (pend_out / f"judge-{psid}-0.pending").write_text(
            "{}", encoding="utf-8")
        try:
            runner.score(config, docs, judge, pend_out, scoring_seed=5,
                         allow_unscheduled=True)
            pend_ok = False
        except runner.InfraFailure as exc:
            pend_ok = "pending judge journal" in str(exc)
        (pend_out / f"judge-{psid}-0.pending").unlink()
        p2 = runner.score(config, docs, judge, pend_out, scoring_seed=5,
                          allow_unscheduled=True)
        ok &= check(
            "pending judge journal blocks resume (no silent second session)",
            pend_ok and len(p2) == 2
            and p2[1]["session_id"] == p1[1]["session_id"],
            notes)
        atomic_target = ws / "atomic-test.json"
        atomic_target.write_text("old", encoding="utf-8")
        runner.atomic_write_text(atomic_target, "new-content")
        ok &= check(
            "manifest writes are atomic (temp + fsync + os.replace, no leftovers)",
            atomic_target.read_text(encoding="utf-8") == "new-content"
            and not list(ws.glob("atomic-test.json.*")),
            notes)
        ok &= check(
            "scorer judge role recorded (blind, evidence-free)",
            all(r.get("role") == "scorer" for r in results),
            notes)
        ok &= check(
            "backend version re-probed and recorded per judge session",
            all(r.get("backend_version") == "mock-claude 1.0.0"
                for r in results),
            notes)
        import random as _random
        expected_order = list(range(len(docs)))
        _random.Random(5).shuffle(expected_order)
        results2 = runner.score(config, docs, judge, ws / "judge-order",
                                scoring_seed=5, allow_unscheduled=True)
        ok &= check(
            "scoring order randomized from recorded seed (reproducible)",
            [r["doc"] for r in results]
            == [str(docs[i]) for i in expected_order]
            and [r["doc"] for r in results2] == [r["doc"] for r in results]
            and all(r.get("scoring_seed") == 5
                    and r.get("presentation_index") == i
                    for i, r in enumerate(results)),
            notes)
        try:
            runner.score(config, docs, judge, ws / "judge-halfpair",
                         evidence_sha="deadbeef", scoring_seed=5,
                         allow_unscheduled=True)
            pair_ok = False
        except runner.InfraFailure as exc:
            pair_ok = "all-or-nothing" in str(exc)
        ok &= check(
            "evidence repo/sha accepted only as a pair",
            pair_ok, notes)
        try:
            runner.score(config, docs, judge, ws / "judge-unsched",
                         scoring_seed=5)
            unsched_ok = False
        except runner.InfraFailure as exc:
            unsched_ok = "unscheduled" in str(exc)
        ok &= check(
            "scoring without a manifest requires explicit unscheduled opt-out",
            unsched_ok, notes)
        sched_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sched_docs = [ws / "out-sched" / f"run-{r['run_id']}-anon.md"
                      for r in sched_manifest["results"]]
        sched_ctx = {Path(task_s).name: str(ctx_file)}
        echo_dir = ws / "echo-judge-ctx"
        os.environ["MOCK_ECHO_DIR"] = str(echo_dir)
        try:
            mres = runner.score(config, sched_docs, judge, ws / "judge-sched",
                                scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                                task_contexts=sched_ctx,
                                seal_manifest_path=seal_file)
        finally:
            os.environ.pop("MOCK_ECHO_DIR", None)
        judge_prompt_echo = (echo_dir / "prompt.txt").read_text(
            encoding="utf-8")
        ok &= check(
            "manifest-bound scoring covers every completed replicate once",
            len(mres) == 2 and all(r.get("scheduled") for r in mres),
            notes)
        m4 = json.loads(manifest_path.read_text(encoding="utf-8"))
        trimmed = dict(m4)
        trimmed["results"] = m4["results"][:1]
        manifest_path.write_text(json.dumps(trimmed), encoding="utf-8")
        try:
            runner.score(config, sched_docs[:1], judge, ws / "judge-trim",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            trim_ok = False
        except runner.InfraFailure as exc:
            trim_ok = "post-hoc subset" in str(exc)
        manifest_path.write_text(json.dumps(m4), encoding="utf-8")
        ok &= check(
            "trimmed scoring manifest refused (verified against its schedule)",
            trim_ok, notes)
        sched_full = json.loads(sched_path.read_text(encoding="utf-8"))
        sched_cut = dict(sched_full)
        sched_cut["entries"] = sched_full["entries"][:1]
        m5 = json.loads(manifest_path.read_text(encoding="utf-8"))
        cut = dict(m5)
        cut["results"] = m5["results"][:1]
        cut["schedule_digest"] = runner.schedule_digest(sched_cut)
        cut_sched_path = ws / "schedule-cut.json"
        cut_sched_path.write_text(json.dumps(sched_cut), encoding="utf-8")
        cut["schedule"] = str(cut_sched_path)
        manifest_path.write_text(json.dumps(cut), encoding="utf-8")
        try:
            runner.score(config, sched_docs[:1], judge, ws / "judge-cut",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            cut_ok = False
        except runner.InfraFailure as exc:
            cut_ok = ("reconstructed from the registered configuration and "
                      "task set" in str(exc))
        manifest_path.write_text(json.dumps(m5), encoding="utf-8")
        ok &= check(
            "schedule and manifest trimmed together refused (reconstruction)",
            cut_ok, notes)
        ok &= check(
            "per-task sealed context routed to each judge and recorded",
            "SEALED-CONTEXT" in judge_prompt_echo
            and all(r.get("task") == str(task_s)
                    and r.get("task_context") == str(ctx_file)
                    for r in mres),
            notes)
        try:
            runner.score(config, sched_docs, judge, ws / "judge-noctx",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)])
            noctx_ok = False
        except runner.InfraFailure as exc:
            noctx_ok = "sealed context" in str(exc)
        ok &= check(
            "manifest scoring without per-task sealed contexts refused",
            noctx_ok, notes)
        try:
            runner.score(config, sched_docs, judge, ws / "judge-swapctx",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts={Path(task_s).name: str(judge)},
                         seal_manifest_path=seal_file)
            swap_ok = False
        except runner.InfraFailure as exc:
            swap_ok = "not the sealed context" in str(exc)
        ok &= check(
            "context not sealed FOR this task refused (association bound)",
            swap_ok, notes)
        try:
            runner.score(config, sched_docs, ctx_file, ws / "judge-roleprompt",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            roleprompt_ok = False
        except runner.InfraFailure as exc:
            roleprompt_ok = "not the sealed" in str(exc)
        ok &= check(
            "judge prompt bound to its role in the seal (mixups refused)",
            roleprompt_ok, notes)
        to_cfg, _ = build_config(ws, "normal", timeout=2)
        to_cfg["judge_backend_cmd"] = [sys.executable,
                                       str(HERE / "mock_claude.py"),
                                       "--mode", "timeout",
                                       "--effort", "{effort}"]
        try:
            runner.score(to_cfg, docs, judge, ws / "judge-timeout",
                         scoring_seed=5, allow_unscheduled=True)
            jto_ok = False
        except runner.InfraFailure as exc:
            jto_ok = "judge session" in str(exc)
        ok &= check(
            "judge timeout classified as infrastructure (batch resumable)",
            jto_ok, notes)
        try:
            runner.score(config, sched_docs, judge, ws / "judge-noseal",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx)
            noseal_ok = False
        except runner.InfraFailure as exc:
            noseal_ok = "atomic-seal manifest" in str(exc)
        ok &= check(
            "manifest scoring without the atomic-seal manifest refused",
            noseal_ok, notes)
        ctx_original = ctx_file.read_bytes()
        ctx_file.write_bytes(ctx_original + b"\nEDITED AFTER SEALING\n")
        try:
            runner.score(config, sched_docs, judge, ws / "judge-sealdrift",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            sealdrift_ok = False
        except runner.InfraFailure as exc:
            sealdrift_ok = "atomic-seal" in str(exc)
        ctx_file.write_bytes(ctx_original)
        ok &= check(
            "judge inputs verified against the atomic seal (edit refused)",
            sealdrift_ok, notes)
        forged_seal = ws / "seal-forged.json"
        forged_ctx_hash = hashlib.sha256(
            b"forged context").hexdigest()
        forged_seal.write_text(json.dumps({"files": {
            Path(judge).name: hashlib.sha256(
                Path(judge).read_bytes()).hexdigest(),
            ctx_file.name: forged_ctx_hash,
        }}), encoding="utf-8")
        try:
            runner.score(config, sched_docs, judge, ws / "judge-forgedseal",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=forged_seal)
            forged_ok = False
        except runner.InfraFailure as exc:
            forged_ok = "seal_package_sha256" in str(exc)
        ok &= check(
            "recomputed seal manifest refused (bound to registered package hash)",
            forged_ok, notes)

        m3 = json.loads(manifest_path.read_text(encoding="utf-8"))
        fab = dict(m3)
        fab["complete"] = False
        fab["results"] = [dict(m3["results"][0], artifact_sha256="0" * 64)]
        manifest_path.write_text(json.dumps(fab), encoding="utf-8")
        try:
            runner.run_schedule(config, sched_path, repos_map,
                                ws / "out-sched", [str(task_s)])
            fab_ok = False
        except runner.InfraFailure as exc:
            fab_ok = "run record" in str(exc)
        manifest_path.write_text(json.dumps(m3), encoding="utf-8")
        ok &= check(
            "resumed manifest results verified against immutable run records",
            fab_ok, notes)

        repo_snap, sha_snap = make_git_repo(ws, "snap")
        task_snap = ws / "task-snap.md"
        task_snap.write_text(
            f"---\ntask-id: snap\ntarget-repo: mock-repo\n"
            f"target-sha: {sha_snap}\nexternal-snapshots: true\n---\n\n"
            f"## Task prompt\n\nSnapshot task.\n\n"
            f"## Ground truth\n\n{SECRET}\n",
            encoding="utf-8")
        snap_cfg, _ = build_config(ws, "normal")
        snap_sched = runner.make_schedule(snap_cfg, [str(task_snap)], 1,
                                          seed=11, allow_nonstandard=True)
        snap_sched_path = ws / "schedule-snap.json"
        snap_sched_path.write_text(json.dumps(snap_sched), encoding="utf-8")
        snap_manifest = runner.run_schedule(
            snap_cfg, snap_sched_path, {"mock-repo": str(repo_snap)},
            ws / "out-snap", [str(task_snap)])
        snap_docs = [ws / "out-snap" / f"run-{r['run_id']}-anon.md"
                     for r in snap_manifest["results"]]
        snap_ctx = {task_snap.name: str(ctx_file)}
        snap_manifest_path = ws / "out-snap" / "schedule-manifest.json"
        refetch_ok = ws / "refetch-ok"
        (refetch_ok / "a").mkdir(parents=True)
        (refetch_ok / "b").mkdir(parents=True)
        (refetch_ok / "a" / "index.html").write_text(
            "<html>SEALED-SNAPSHOT A</html>\n", encoding="utf-8")
        (refetch_ok / "b" / "index.html").write_text(
            "<html>SEALED-SNAPSHOT B</html>\n", encoding="utf-8")
        refetch_bad = ws / "refetch-bad"
        (refetch_bad / "a").mkdir(parents=True)
        (refetch_bad / "b").mkdir(parents=True)
        (refetch_bad / "a" / "index.html").write_text(
            "<html>SEALED-SNAPSHOT A</html>\n", encoding="utf-8")
        (refetch_bad / "b" / "index.html").write_text(
            "<html>THE LIVE SOURCE CHANGED</html>\n", encoding="utf-8")
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_ok)
        drift_ok_file = ws / "drift-unchanged.json"
        drift_ok_file.write_text(json.dumps(
            {task_snap.name: {}}), encoding="utf-8")
        drift_bad_file = ws / "drift-drifted.json"
        drift_bad_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "material": True,
                    "rationale": "ground-truth section replaced"}}}}),
            encoding="utf-8")
        drift_cosmetic_file = ws / "drift-cosmetic.json"
        drift_cosmetic_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "material": False,
                    "rationale": "footer timestamp only; ground-truth "
                                 "sections untouched"}}}}),
            encoding="utf-8")
        drift_noadj_file = ws / "drift-noadj.json"
        drift_noadj_file.write_text(json.dumps(
            {task_snap.name: {}}), encoding="utf-8")
        drift_claim_file = ws / "drift-claim.json"
        drift_claim_file.write_text(json.dumps(
            {task_snap.name: {"status": "unchanged"}}), encoding="utf-8")
        drift_local_file = ws / "drift-localcopy.json"
        drift_local_file.write_text(json.dumps(
            {task_snap.name: {"refetched": str(snap_dir)}}),
            encoding="utf-8")
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-nosnap",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx,
                         seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)})
            nosnap_ok = False
        except runner.InfraFailure as exc:
            nosnap_ok = "external" in str(exc) and "snapshots" in str(exc)
        ok &= check(
            "external-context task without sealed snapshots refused",
            nosnap_ok, notes)
        echo_dir = ws / "echo-snapverify"
        os.environ["MOCK_ECHO_DIR"] = str(echo_dir)
        try:
            snap_res = runner.score(
                snap_cfg, snap_docs, judge, ws / "judge-snap",
                scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                task_contexts=snap_ctx, seal_manifest_path=seal_file,
                evidence_repos={"mock-repo": str(repo_snap)},
                task_snapshots={task_snap.name: str(snap_dir)},
                drift_report_path=drift_ok_file)
        finally:
            os.environ.pop("MOCK_ECHO_DIR", None)
        snap_listing = (echo_dir / "cwd-listing.txt").read_text(
            encoding="utf-8")
        ok &= check(
            "sealed snapshots in verifier workdir (relative keys, layout kept)",
            "_sealed-snapshots" in snap_listing
            and snap_res[0].get("snapshots") == str(snap_dir),
            notes)
        partial_root = ws / "partial-set"
        partial_snap = partial_root / "external-snapshots"
        (partial_snap / "a").mkdir(parents=True)
        (partial_snap / "a" / "index.html").write_bytes(
            (snap_dir / "a" / "index.html").read_bytes())
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-partialsnap",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(partial_snap)},
                         drift_report_path=drift_ok_file)
            snapset_ok = False
        except runner.InfraFailure as exc:
            snapset_ok = "differs from the seal" in str(exc)
        ok &= check(
            "incomplete sealed snapshot set refused (enumerated from seal)",
            snapset_ok, notes)
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-nodrift",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(snap_dir)})
            nodrift_ok = False
        except runner.InfraFailure as exc:
            nodrift_ok = "drift report" in str(exc) or "--drift-report" in str(exc)
        ok &= check(
            "external-context scoring requires the pre-score drift report",
            nodrift_ok, notes)
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_bad)
        drift_res = runner.score(
            snap_cfg, snap_docs, judge, ws / "judge-drifted",
            scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
            task_contexts=snap_ctx, seal_manifest_path=seal_file,
            evidence_repos={"mock-repo": str(repo_snap)},
            task_snapshots={task_snap.name: str(snap_dir)},
            drift_report_path=drift_bad_file)
        ok &= check(
            "drifted external source makes the task inconclusive (not judged)",
            len(drift_res) == 1
            and drift_res[0].get("inconclusive") is True
            and "session_id" not in drift_res[0],
            notes)
        # The reported basis for exclusion (changed keys, verdicts,
        # rationales) must survive into the excluded record itself, not
        # collapse to a generic reason.
        ok &= check(
            "material drift adjudication preserved in the excluded record",
            drift_res[0].get("source_drift", {}).get("material") is True
            and drift_res[0]["source_drift"]["changed"]
            == ["external-snapshots/b/index.html"]
            and drift_res[0]["source_drift"]["adjudications"][
                "external-snapshots/b/index.html"]["rationale"]
            == "ground-truth section replaced",
            notes)
        # A corrected material-drift report between interruption and resume
        # is a different batch even when the same task stays inconclusive:
        # the adjudication details are part of the batch identity.
        drift_bad2_file = ws / "drift-drifted2.json"
        drift_bad2_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "material": True,
                    "rationale": "a different recorded basis"}}}}),
            encoding="utf-8")
        mdr_manifest = (ws / "judge-drifted"
                        / "scoring-verifier-manifest.json")
        mdm = json.loads(mdr_manifest.read_text(encoding="utf-8"))
        mdm["complete"] = False
        mdr_manifest.write_text(json.dumps(mdm), encoding="utf-8")
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-drifted",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_bad2_file)
            mdrift_ok = False
        except runner.InfraFailure as exc:
            mdrift_ok = "different identity" in str(exc)
        ok &= check(
            "changed material-drift basis refused on resume (same exclusions)",
            mdrift_ok, notes)
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-claim",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_claim_file)
            claim_ok = False
        except runner.InfraFailure as exc:
            claim_ok = "materiality adjudication" in str(exc)
        ok &= check(
            "bare drift status claim refused (harness computes drift)",
            claim_ok, notes)
        scorer_drift = runner.score(
            snap_cfg, snap_docs, judge, ws / "judge-scorer-drift",
            scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
            task_contexts=snap_ctx, seal_manifest_path=seal_file,
            task_snapshots={task_snap.name: str(snap_dir)},
            drift_report_path=drift_bad_file)
        ok &= check(
            "blind scorer excludes drifted external tasks too",
            len(scorer_drift) == 1
            and scorer_drift[0].get("inconclusive") is True,
            notes)
        sd_manifest = ws / "judge-scorer-drift" / "scoring-scorer-manifest.json"
        sdm = json.loads(sd_manifest.read_text(encoding="utf-8"))
        sdm["complete"] = False
        sdm["results"] = []
        sd_manifest.write_text(json.dumps(sdm), encoding="utf-8")
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_ok)
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-scorer-drift",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_ok_file)
            ddrift_ok = False
        except runner.InfraFailure as exc:
            ddrift_ok = "different identity" in str(exc)
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_bad)
        ok &= check(
            "changed drift decisions refused on resume (identity bound)",
            ddrift_ok, notes)
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-noadj",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_noadj_file)
            noadj_ok = False
        except runner.InfraFailure as exc:
            noadj_ok = "materiality adjudication" in str(exc)
        ok &= check(
            "changed source without materiality adjudication refused",
            noadj_ok, notes)
        cosmetic_res = runner.score(
            snap_cfg, snap_docs, judge, ws / "judge-cosmetic",
            scoring_seed=5, manifest_path=snap_manifest_path,
            score_task_paths=[str(task_snap)],
            task_contexts=snap_ctx, seal_manifest_path=seal_file,
            evidence_repos={"mock-repo": str(repo_snap)},
            task_snapshots={task_snap.name: str(snap_dir)},
            drift_report_path=drift_cosmetic_file)
        ok &= check(
            "adjudicated-cosmetic drift stays scoreable (recorded, not fatal)",
            len(cosmetic_res) == 1
            and not cosmetic_res[0].get("inconclusive")
            and cosmetic_res[0].get("source_drift", {}).get("material") is False,
            notes)
        # The gate must never trust operator-supplied bytes: a report that
        # points `refetched` at any local copy (here: the sealed snapshot
        # itself) is refused outright — the harness fetches the sealed
        # source URLs itself.
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-localcopy",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_local_file)
            localcopy_ok = False
        except runner.InfraFailure as exc:
            localcopy_ok = "not accepted" in str(exc)
        ok &= check(
            "local re-fetched copies refused (harness fetches live sources)",
            localcopy_ok, notes)
        empty_live = ws / "refetch-empty"
        empty_live.mkdir()
        os.environ["MOCK_LIVE_ROOT"] = str(empty_live)
        try:
            runner.score(snap_cfg, snap_docs, judge, ws / "judge-fetchfail",
                         scoring_seed=5, manifest_path=snap_manifest_path,
                         score_task_paths=[str(task_snap)],
                         task_contexts=snap_ctx, seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_snap)},
                         task_snapshots={task_snap.name: str(snap_dir)},
                         drift_report_path=drift_ok_file)
            fetchfail_ok = False
        except runner.InfraFailure as exc:
            fetchfail_ok = "live-source fetch failed" in str(exc)
        os.environ.pop("MOCK_LIVE_ROOT", None)
        ok &= check(
            "failed live-source fetch classified as infra (no silent skip)",
            fetchfail_ok, notes)
        # Drift is fetched once per task and the verdict applied to every
        # replicate: per-document fetching could split a nondeterministic
        # live source into judged and excluded replicates of one cell.
        sched2 = runner.make_schedule(snap_cfg, [str(task_snap)], 2,
                                      seed=12, allow_nonstandard=True)
        sched2_path = ws / "schedule-snap2.json"
        sched2_path.write_text(json.dumps(sched2), encoding="utf-8")
        man2 = runner.run_schedule(snap_cfg, sched2_path,
                                   {"mock-repo": str(repo_snap)},
                                   ws / "out-snap2", [str(task_snap)])
        docs2 = [ws / "out-snap2" / f"run-{r['run_id']}-anon.md"
                 for r in man2["results"]]
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_bad)
        fetch_log = ws / "fetch-log.txt"
        os.environ["MOCK_FETCH_LOG"] = str(fetch_log)
        try:
            two_res = runner.score(
                snap_cfg, docs2, judge, ws / "judge-snap2",
                scoring_seed=5,
                manifest_path=ws / "out-snap2" / "schedule-manifest.json",
                score_task_paths=[str(task_snap)],
                task_contexts=snap_ctx, seal_manifest_path=seal_file,
                evidence_repos={"mock-repo": str(repo_snap)},
                task_snapshots={task_snap.name: str(snap_dir)},
                drift_report_path=drift_bad_file)
        finally:
            os.environ.pop("MOCK_FETCH_LOG", None)
            os.environ.pop("MOCK_LIVE_ROOT", None)
        fetches = fetch_log.read_text(encoding="utf-8").splitlines()
        ok &= check(
            "drift fetched once per task, verdict uniform across replicates",
            len(two_res) == 2
            and all(r.get("inconclusive") is True for r in two_res)
            and len({json.dumps(r.get("source_drift"), sort_keys=True)
                     for r in two_res}) == 1
            and len(fetches) == 2,
            notes)
        cfgJ, _ = build_config(ws, "normal")
        cfgJ["judge_effort"] = "low"
        schedJ = runner.make_schedule(cfgJ, [str(task_s)], 1, seed=11,
                                      allow_nonstandard=True)
        schedJ_path = ws / "schedule-sealjudge.json"
        schedJ_path.write_text(json.dumps(schedJ), encoding="utf-8")
        manJ = runner.run_schedule(cfgJ, schedJ_path,
                                   {"mock-repo": str(repo_s)},
                                   ws / "out-sealjudge", [str(task_s)])
        docsJ = [ws / "out-sealjudge" / f"run-{r['run_id']}-anon.md"
                 for r in manJ["results"]]
        try:
            runner.score(cfgJ, docsJ, judge, ws / "judge-sealjudge",
                         scoring_seed=5,
                         manifest_path=(ws / "out-sealjudge"
                                        / "schedule-manifest.json"),
                         score_task_paths=[str(task_s)],
                         task_contexts={Path(str(task_s)).name:
                                        str(ctx_file)},
                         seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_s)})
            sealjudge2_ok = False
        except runner.InfraFailure as exc:
            sealjudge2_ok = "sealed judge configuration" in str(exc)
        ok &= check(
            "judge settings drifted from the seal refused at scoring",
            sealjudge2_ok, notes)
        vres3 = runner.score(config, sched_docs, judge, ws / "judge-sched",
                             scoring_seed=5, manifest_path=manifest_path,
                             score_task_paths=[str(task_s)],
                             evidence_repos={"mock-repo": str(repo_s)},
                             task_contexts=sched_ctx,
                             seal_manifest_path=seal_file)
        ok &= check(
            "scorer and verifier batches coexist in one output directory",
            len(vres3) == 2 and all(r.get("role") == "verifier" for r in vres3),
            notes)
        try:
            runner.score(config, sched_docs[:1], judge, ws / "judge-subset",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)])
            subset_ok = False
        except runner.InfraFailure as exc:
            subset_ok = "exactly once" in str(exc)
        ok &= check(
            "subset or duplicated scoring inputs refused against the manifest",
            subset_ok, notes)
        vres2 = runner.score(config, sched_docs, judge, ws / "judge-mverify",
                             scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                             evidence_repos={"mock-repo": str(repo_s)},
                             task_contexts=sched_ctx,
                             seal_manifest_path=seal_file)
        ok &= check(
            "manifest verification maps each doc to its task's repo@sha",
            all(r.get("role") == "verifier"
                and r.get("evidence_sha") == sha_s for r in vres2),
            notes)
        try:
            runner.score(config, sched_docs, judge, ws / "judge-mpair",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         evidence_repo=str(repo_s), evidence_sha=sha_s,
                         task_contexts=sched_ctx)
            mpair_ok = False
        except runner.InfraFailure as exc:
            mpair_ok = "NAME=PATH" in str(exc)
        ok &= check(
            "single shared evidence checkout refused for manifest batches",
            mpair_ok, notes)
        tampered_doc = Path(sched_docs[0])
        original_bytes = tampered_doc.read_bytes()
        tampered_doc.write_text("# swapped contents\n", encoding="utf-8")
        try:
            runner.score(config, sched_docs, judge, ws / "judge-tamperdoc",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)])
            digest_ok = False
        except runner.InfraFailure as exc:
            digest_ok = "artifact digest" in str(exc)
        tampered_doc.write_bytes(original_bytes)
        ok &= check(
            "scored artifacts bound to the content digest recorded at run time",
            digest_ok, notes)
        drift_cfg, _ = build_config(ws, "normal")
        drift_cfg["timeout_seconds"] = 999
        try:
            runner.score(drift_cfg, sched_docs, judge, ws / "judge-cfgdrift",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)])
            cdrift_ok = False
        except runner.InfraFailure as exc:
            cdrift_ok = "config digest mismatch" in str(exc)
        ok &= check(
            "runtime-config drift refused before scoring",
            cdrift_ok, notes)
        Path(task_s).write_bytes(original_task_bytes + b"\nX\n")
        try:
            runner.score(config, sched_docs, judge, ws / "judge-taskdrift",
                         scoring_seed=5, manifest_path=manifest_path,
                         score_task_paths=[str(task_s)],
                         evidence_repos={"mock-repo": str(repo_s)},
                         task_contexts=sched_ctx)
            sdrift_ok = False
        except runner.InfraFailure as exc:
            sdrift_ok = "task file changed" in str(exc)
        Path(task_s).write_bytes(original_task_bytes)
        ok &= check(
            "task drift refused at scoring time (binding to scheduled task)",
            sdrift_ok, notes)
        ev_repo, ev_sha = make_git_repo(ws, "evidence")
        echo_dir = ws / "echo-verifier"
        os.environ["MOCK_ECHO_DIR"] = str(echo_dir)
        try:
            vres = runner.score(config, [docs[0]], judge, ws / "judge-verify",
                                evidence_repo=ev_repo, evidence_sha=ev_sha,
                                scoring_seed=5, allow_unscheduled=True)
        finally:
            os.environ.pop("MOCK_ECHO_DIR", None)
        listing = (echo_dir / "cwd-listing.txt").read_text(encoding="utf-8")
        vdeny = json.loads(
            (Path(vres[0]["profile"]) / "settings.json").read_text(
                encoding="utf-8")).get("permissions", {}).get("deny", [])
        sandbox_echo = (echo_dir / "sandbox.txt").read_text(
            encoding="utf-8").strip()
        ok &= check(
            "verifier judge gets read-only evidence worktree at pinned sha",
            vres[0].get("role") == "verifier"
            and vres[0].get("evidence_sha") == ev_sha
            and "README.md" in listing
            and not Path(vres[0]["cwd"]).exists()
            and "Read" not in vdeny and "Bash" in vdeny and "Write" in vdeny,
            notes)
        ok &= check(
            "judge session sandbox confined to its evidence worktree",
            sandbox_echo == vres[0].get("cwd"),
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
