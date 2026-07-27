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
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402

EXPECTED_TREE = {"input_tokens": 140, "output_tokens": 70, "tool_calls": 12}
EXPECTED_MAIN = {"input_tokens": 100, "output_tokens": 50, "tool_calls": 7}
EXPECTED_SUB = {"input_tokens": 40, "output_tokens": 20, "tool_calls": 5}
SECRET = "SECRET-GROUND-TRUTH-MARKER"
SEAL_SHA = None


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
        "seal_package_sha256": SEAL_SHA,
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
    global SEAL_SHA
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
        seal_file = ws / "seal-manifest.json"
        seal_file.write_text(json.dumps({"files": {
            judge.name: hashlib.sha256(judge.read_bytes()).hexdigest(),
            ctx_file.name: hashlib.sha256(ctx_file.read_bytes()).hexdigest(),
            "external-snapshots/a/index.html": hashlib.sha256(
                (snap_dir / "a" / "index.html").read_bytes()).hexdigest(),
            "external-snapshots/b/index.html": hashlib.sha256(
                (snap_dir / "b" / "index.html").read_bytes()).hexdigest(),
        }}), encoding="utf-8")
        SEAL_SHA = hashlib.sha256(seal_file.read_bytes()).hexdigest()

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
                                 ws / "out-sandbox-req")
        ok &= check(
            "production config requires a registered sandbox_cmd",
            record["status"] == "infra_failure"
            and "sandbox_cmd" in record.get("failure", ""),
            notes)
        config["sandbox_cmd"] = ["/usr/bin/env"]
        record = runner.run_task(config, "baseline", task_sbx, repo,
                                 ws / "out-sandbox-noconfine")
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

        dummy_tasks = []
        archetypes = {"a": "1 — subsystem-explanation",
                      "b": "3 — narrow where-is"}
        for c in "abcdef":
            arch = archetypes.get(c, f"9 — other-{c}")
            dt = ws / f"t-{c}.md"
            dt.write_text(
                f"---\ntask-id: dummy-{c}\narchetype: \"{arch}\"\n"
                f"target-repo: mock-repo\n"
                f"target-sha: {'0' * 40}\n---\n\n## Task prompt\n\nDummy {c}.\n",
                encoding="utf-8")
            dummy_tasks.append(str(dt))
        d_a, d_b, d_c = dummy_tasks[:3]

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
        m["results"] = m["results"][:1]
        m["complete"] = False
        manifest_path.write_text(json.dumps(m), encoding="utf-8")
        runs_before = len(list((ws / "out-sched").glob("run-*.json")))
        manifest2 = runner.run_schedule(config, sched_path, repos_map,
                                        ws / "out-sched", [str(task_s)])
        runs_after = len(list((ws / "out-sched").glob("run-*.json")))
        ok &= check(
            "schedule progress persisted and resumed (no duplicate reruns)",
            manifest2["complete"] is True
            and len(manifest2["results"]) == 2
            and runs_after == runs_before + 1,
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

        record, _, _, _ = run_case(ws, "hang-silent", timeout=2)
        ok &= check(
            "failure without any parity evidence invalidated (empty transcript)",
            record["status"] == "infra_failure"
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
        drift_ok_file = ws / "drift-unchanged.json"
        drift_ok_file.write_text(json.dumps(
            {task_snap.name: {"refetched": str(refetch_ok)}}),
            encoding="utf-8")
        drift_bad_file = ws / "drift-drifted.json"
        drift_bad_file.write_text(json.dumps(
            {task_snap.name: {"refetched": str(refetch_bad), "changed": {
                "external-snapshots/b/index.html": {
                    "material": True,
                    "rationale": "ground-truth section replaced"}}}}),
            encoding="utf-8")
        drift_cosmetic_file = ws / "drift-cosmetic.json"
        drift_cosmetic_file.write_text(json.dumps(
            {task_snap.name: {"refetched": str(refetch_bad), "changed": {
                "external-snapshots/b/index.html": {
                    "material": False,
                    "rationale": "footer timestamp only; ground-truth "
                                 "sections untouched"}}}}),
            encoding="utf-8")
        drift_noadj_file = ws / "drift-noadj.json"
        drift_noadj_file.write_text(json.dumps(
            {task_snap.name: {"refetched": str(refetch_bad)}}),
            encoding="utf-8")
        drift_claim_file = ws / "drift-claim.json"
        drift_claim_file.write_text(json.dumps(
            {task_snap.name: {"status": "unchanged"}}), encoding="utf-8")
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
            claim_ok = "not evidence" in str(exc)
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
