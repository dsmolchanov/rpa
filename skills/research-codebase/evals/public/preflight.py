#!/usr/bin/env python3
"""Synthetic preflight for the eval-runner (pilot plan, prerequisite 5).

Proves every runner capability against the deterministic mock backend on a
throwaway task — offline, CI-runnable, zero model spend. A real-backend
preflight on the throwaway task is still required once before baseline runs.
"""

import hashlib
import contextlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402
import judge_contract  # noqa: E402
import mock_claude  # noqa: E402
import aggregate_results  # noqa: E402
import seal_package  # noqa: E402
import judge_live_probe  # noqa: E402
import pilot_registration  # noqa: E402

EXPECTED_TREE = {"input_tokens": 140, "output_tokens": 70, "tool_calls": 12}
EXPECTED_MAIN = {"input_tokens": 100, "output_tokens": 50, "tool_calls": 7}
EXPECTED_SUB = {"input_tokens": 40, "output_tokens": 20, "tool_calls": 5}
SECRET = "SECRET-GROUND-TRUTH-MARKER"
SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256 = "1" * 64
SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256 = "2" * 64
SYNTHETIC_NONPENDING_SEAL_SHA256 = "7" * 64
SEAL_SHA = None
SEAL_PATH = None


def _registration_state():
    operator_contract = judge_live_probe.operator_contract
    return {
        "shared": (
            pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256,
            pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
        ),
        # judge_live_probe imports step5_operator before run_preflight enters
        # its fixture context, so its compatibility aliases must be isolated
        # and restored alongside the shared authority.
        "probe_operator": (
            operator_contract.REGISTERED_SEAL_PACKAGE_SHA256,
            operator_contract.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            operator_contract.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
        ),
    }


def _restore_registration_state(state):
    operator_contract = judge_live_probe.operator_contract
    (pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256,
     pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
     pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256) = state[
         "shared"]
    (operator_contract.REGISTERED_SEAL_PACKAGE_SHA256,
     operator_contract.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
     operator_contract.REGISTERED_LIVE_PROBE_EXECUTION_SHA256) = state[
         "probe_operator"]


@contextlib.contextmanager
def isolated_synthetic_registration():
    """Temporarily replace production registrations for public fixtures."""
    saved = _registration_state()
    operator_contract = judge_live_probe.operator_contract
    pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256 = (
        pilot_registration.PENDING_SEAL_PACKAGE_SHA256)
    pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
        SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256)
    pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
        SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256)
    operator_contract.REGISTERED_SEAL_PACKAGE_SHA256 = (
        pilot_registration.PENDING_SEAL_PACKAGE_SHA256)
    operator_contract.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
        SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256)
    operator_contract.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
        SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256)
    try:
        yield saved
    finally:
        _restore_registration_state(saved)


def _registration_isolation_self_test():
    """Prove non-pending isolation even when the real authority is pending."""
    actual = _registration_state()
    injected = {
        "shared": (SYNTHETIC_NONPENDING_SEAL_SHA256,
                   *actual["shared"][1:]),
        "probe_operator": (SYNTHETIC_NONPENDING_SEAL_SHA256,
                           *actual["probe_operator"][1:]),
    }
    try:
        _restore_registration_state(injected)
        with isolated_synthetic_registration():
            isolated = _registration_state()
            entered_cleanly = (
                isolated["shared"] == (
                    pilot_registration.PENDING_SEAL_PACKAGE_SHA256,
                    SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
                    SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256)
                and isolated["probe_operator"] == isolated["shared"])
        return entered_cleanly and _registration_state() == injected
    finally:
        _restore_registration_state(actual)


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
                            "{dest}"],
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
             extra_env=None, protocol_v2=False):
    label = label or mode
    config, install = build_config(workspace, mode, timeout)
    if protocol_v2:
        config.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "max_infra_retries": runner.DEFAULT_MAX_INFRA_RETRIES,
        })
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


def make_v2_fixture(workspace, label, repo, target_sha,
                    run_mode="normal", judge_mode="judge-auto",
                    execute_run=True, timeout=20, task_numbers=(1,)):
    """Create one private-shaped, nonstandard v2 schedule in a temp tree.

    Task, context, and prompt contents remain synthetic.  The fixture still
    exercises the real seal/config/schedule/run-record bindings used by a
    production batch; only the topology and replicate count are dev-marked.
    """
    root = Path(workspace) / f"v2-{label}"
    sealed = root / "sealed"
    sealed.mkdir(parents=True)
    archetypes = {
        1: "1 — subsystem-explanation",
        2: "2 — subsystem-explanation, largest repo",
        3: "3 — narrow where-is",
        4: "4 — code + thoughts history",
        5: "5 — external library context",
        6: "6 — known-wrong premise",
    }
    tasks = {}
    contexts = {}
    for number in range(1, 7):
        task_path = sealed / f"holdout-v2-{number}.md"
        external_marker = (
            "external-snapshots: true\n" if number == 5 else "")
        task_path.write_text(
            f"---\ntask-id: v2-{label}-{number}\n"
            f"archetype: \"{archetypes[number]}\"\n"
            f"target-repo: mock-repo\ntarget-sha: {target_sha}\n"
            f"set: preflight-v2\n{external_marker}---\n\n"
            f"## Task prompt\n\n"
            f"Synthetic protocol-v2 task {label}-{number}.\n\n"
            f"## Ground truth\n\n{SECRET}\n",
            encoding="utf-8",
        )
        context_path = (
            sealed / seal_package.CANONICAL_TASK_CONTEXTS[task_path.name])
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(
            f"SEALED-V2-CONTEXT {label}-{number}: synthetic prompt and "
            f"ground truth.\n",
            encoding="utf-8",
        )
        tasks[number] = task_path
        contexts[number] = context_path
    selected_numbers = list(task_numbers)
    if (not selected_numbers or len(set(selected_numbers))
            != len(selected_numbers)
            or any(number not in tasks for number in selected_numbers)):
        raise ValueError("task_numbers must name distinct fixture tasks")
    selected_tasks = [tasks[number] for number in selected_numbers]
    task = selected_tasks[0]
    context = contexts[selected_numbers[0]]
    prompts = {
        role: sealed / relative
        for role, relative in seal_package.CANONICAL_JUDGE_PROMPTS.items()
    }
    for path in prompts.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    prompts["scorer"].write_text(
        "SCORER-CONTRACT\nReturn exactly the sealed scorer JSON object.\n",
        encoding="utf-8",
    )
    prompts["verifier"].write_text(
        "VERIFIER-CONTRACT\nReturn exactly the sealed verifier JSON object.\n",
        encoding="utf-8",
    )
    schemas = {
        role: sealed / relative
        for role, relative in seal_package.CANONICAL_JUDGE_SCHEMAS.items()
    }
    for path in schemas.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    for role, path in schemas.items():
        path.write_text(
            json.dumps(judge_contract.contract_schema(role),
                       indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    rubric = sealed / seal_package.CANONICAL_QUALITY_RUBRIC
    rubric.write_text(
        "# Synthetic quality rubric\n\nScore only against sealed evidence.\n",
        encoding="utf-8",
    )
    coverage = sealed / seal_package.CANONICAL_COVERAGE_MATRIX
    coverage.write_text(
        json.dumps({
            tasks[number].name: {"archetype": archetypes[number]}
            for number in range(1, 7)
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    snapshot = sealed / "snapshots" / "reference.txt"
    snapshot.parent.mkdir()
    snapshot.write_text(
        "Synthetic frozen external reference.\n", encoding="utf-8")

    config, _ = build_config(workspace, run_mode, timeout=timeout)
    judge_backend_cmd = [
        sys.executable, str(HERE / "mock_claude.py"),
        "--mode", judge_mode, "--effort", "{effort}",
        "--prompt-receipt-file", str(root / "judge-prompt-receipt.txt"),
        "--transport-receipt-file",
        str(root / "judge-transport-receipt.ndjson"),
    ]
    if judge_mode == "judge-invalid-then-valid":
        judge_backend_cmd.extend([
            "--judge-state-file", str(root / "judge-state.txt")])
    if judge_mode == "judge-background-child":
        judge_backend_cmd.extend([
            "--child-write-file", str(root / "judge-child-survived")])
    config.update({
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "nonstandard_config": True,
        "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
        "judge_live_probe_receipt_sha256":
            SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
        "judge_live_probe_execution_sha256":
            SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256,
        "judge_backend_cmd": judge_backend_cmd,
    })
    if run_mode == "flaky-infra":
        config["backend_cmd"].extend([
            "--run-state-file", str(root / "run-state.txt")])
    materials = [
        *tasks.values(), *contexts.values(), *prompts.values(),
        *schemas.values(), rubric, coverage, snapshot,
    ]
    file_digests = {
        path.relative_to(sealed).as_posix(): hashlib.sha256(
            path.read_bytes()).hexdigest()
        for path in materials
    }
    seal = sealed / "seal-manifest.json"
    seal.write_text(json.dumps({
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "nonstandard_config": True,
        "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
        "judge_retry_policy": runner.PILOT_V2_JUDGE_RETRY_POLICY,
        "judge_output_policy": runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
        "judge_live_probe": runner.protocol_v2_live_probe_binding(config),
        "pilot_runtime_registration_sha256": (
            pilot_registration.standard_v2_runtime_registration_sha256()),
        "aggregation_policy": runner.PILOT_V2_AGGREGATION_POLICY,
        "judge_prompts": {
            role: path.relative_to(sealed).as_posix()
            for role, path in prompts.items()
        },
        "judge_response_schemas": {
            role: path.relative_to(sealed).as_posix()
            for role, path in schemas.items()
        },
        "quality_rubric": rubric.relative_to(sealed).as_posix(),
        "coverage_matrix": coverage.relative_to(sealed).as_posix(),
        "task_contexts": {
            tasks[number].name: contexts[number].relative_to(
                sealed).as_posix()
            for number in range(1, 7)
        },
        "ablation_tasks": ["holdout-v2-1.md", "holdout-v2-3.md"],
            "snapshot_sources": {
                "snapshots/reference.txt":
                "https://example.invalid/live/reference.txt",
        },
        "judge_config": {
            "judge_backend_cmd": config["judge_backend_cmd"],
            "judge_model": config["judge_model"],
            "judge_effort": config["judge_effort"],
        },
        "files": file_digests,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    config["seal_manifest"] = str(seal)
    config["seal_package_sha256"] = hashlib.sha256(
        seal.read_bytes()).hexdigest()

    schedule = runner.make_schedule(
        config, [str(path) for path in selected_tasks], 1,
        seed=runner.PILOT_V2_SCHEDULE_SEED,
        allow_nonstandard=True)
    schedule_path = root / "schedule.json"
    schedule_path.write_text(
        json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
    run_output = root / "runs"
    manifest = None
    manifest_path = run_output / "schedule-manifest.json"
    docs = []
    if execute_run:
        manifest = runner.run_schedule(
            config, schedule_path, {"mock-repo": str(repo)}, run_output,
            [str(path) for path in selected_tasks],
        )
        for result in manifest["results"]:
            gate = result.get("artifact_gate")
            if gate == "passed":
                suffix = "anon"
            elif gate == "failed":
                suffix = "diag"
            else:
                continue
            docs.append(run_output / f"run-{result['run_id']}-{suffix}.md")
    return {
        "root": root,
        "config": config,
        "task": task,
        "tasks": selected_tasks,
        "context": context,
        "contexts": {
            tasks[number].name: contexts[number]
            for number in selected_numbers
        },
        "prompts": prompts,
        "schemas": schemas,
        "rubric": rubric,
        "seal": seal,
        "schedule": schedule_path,
        "run_output": run_output,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "docs": docs,
        "repo": Path(repo),
        "prompt_receipt": root / "judge-prompt-receipt.txt",
        "transport_receipt": root / "judge-transport-receipt.ndjson",
    }


def score_v2_fixture(fixture, role, output_dir):
    kwargs = {
        "scoring_seed": (runner.PILOT_V2_VERIFIER_SEED
                         if role == "verifier"
                         else runner.PILOT_V2_SCORER_SEED),
        "manifest_path": fixture["manifest_path"],
        "score_task_paths": [str(task) for task in fixture["tasks"]],
        "task_contexts": {
            name: str(path) for name, path in fixture["contexts"].items()
        },
        "seal_manifest_path": fixture["seal"],
    }
    if role == "verifier":
        kwargs["evidence_repos"] = {"mock-repo": str(fixture["repo"])}
    return runner.score(
        fixture["config"], fixture["docs"], fixture["prompts"][role],
        output_dir, **kwargs,
    )


def make_v2_aggregation_fixture(workspace, target_sha, label="golden"):
    """Build the complete standard 42-run/84-judge aggregation population.

    No backend is launched: deterministic immutable records stand in for the
    already-completed private round.  The topology, seal, schedule, all-docs
    judge manifests, and every aggregation binding are production-shaped.
    """
    root = Path(workspace) / f"v2-aggregate-{label}"
    sealed = root / "sealed"
    output = root / "output"
    sealed.mkdir(parents=True)
    output.mkdir()
    (output / ".run-schedule.lock").write_text("", encoding="utf-8")
    for role in ("scorer", "verifier"):
        (output / f".scoring-{role}-all-docs.lock").write_text(
            "", encoding="utf-8")

    task_meta = (
        (1, "1 — subsystem-explanation", "dsmolchanov/rpa"),
        (2, "2 — subsystem-explanation, largest repo", "dsmolchanov/neomenu"),
        (3, "3 — narrow where-is", "dsmolchanov/rpa"),
        (4, "4 — code + thoughts history", "dsmolchanov/neomenu"),
        (5, "5 — external library context",
         "dsmolchanov/livekit-voice-agent"),
        (6, "6 — known-wrong premise",
         "dsmolchanov/livekit-voice-agent"),
    )
    tasks = []
    contexts = {}
    for number, archetype, repository in task_meta:
        task = sealed / f"holdout-v2-{number}.md"
        external_marker = (
            "external-snapshots: true\n" if number == 5 else "")
        task.write_text(
            f"---\ntask-id: aggregate-v2-{number}\n"
            f"archetype: \"{archetype}\"\n"
            f"target-repo: {repository}\ntarget-sha: {target_sha}\n"
            f"set: aggregate-preflight\n{external_marker}---\n\n"
            f"## Task prompt\n\n"
            f"Synthetic aggregation task {number}.\n",
            encoding="utf-8",
        )
        context = sealed / seal_package.CANONICAL_TASK_CONTEXTS[task.name]
        context.parent.mkdir(parents=True, exist_ok=True)
        context.write_text(
            f"Synthetic sealed context {number}; {SECRET}\n",
            encoding="utf-8",
        )
        tasks.append(task)
        contexts[task.name] = context

    prompts = {}
    schemas = {}
    for role in ("scorer", "verifier"):
        prompt = sealed / seal_package.CANONICAL_JUDGE_PROMPTS[role]
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text(
            f"{role.upper()}-CONTRACT: return strict JSON.\n",
            encoding="utf-8",
        )
        prompts[role] = prompt
        schema = sealed / seal_package.CANONICAL_JUDGE_SCHEMAS[role]
        schema.parent.mkdir(parents=True, exist_ok=True)
        schema.write_text(
            json.dumps(judge_contract.contract_schema(role),
                       indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        schemas[role] = schema
    rubric = sealed / seal_package.CANONICAL_QUALITY_RUBRIC
    rubric.write_text(
        "# Synthetic quality rubric\n\nScore only against sealed evidence.\n",
        encoding="utf-8",
    )
    coverage = sealed / seal_package.CANONICAL_COVERAGE_MATRIX
    coverage.write_text(
        json.dumps({
            task.name: {"archetype": task_meta[index][1]}
            for index, task in enumerate(tasks)
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    snapshot = sealed / "snapshots" / "reference.txt"
    snapshot.parent.mkdir()
    snapshot.write_text(
        "Synthetic frozen external reference.\n", encoding="utf-8")

    installs = {}
    for arm in ("baseline", "candidate", "ablation"):
        install = root / f"install-{arm}"
        install.mkdir()
        (install / "plugin.txt").write_text(
            "identical synthetic installation\n", encoding="utf-8")
        installs[arm] = install

    judge_cmd = list(pilot_registration.JUDGE_BACKEND_CMD)
    config = {
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
        "arms": {},
        "backend_cmd": list(pilot_registration.BACKEND_CMD),
        "judge_backend_cmd": judge_cmd,
        "judge_model": pilot_registration.JUDGE_MODEL,
        "judge_effort": pilot_registration.JUDGE_EFFORT,
        "workflow_abort_exit_codes": list(
            pilot_registration.WORKFLOW_ABORT_EXIT_CODES),
        "max_infra_retries": pilot_registration.MAX_INFRA_RETRIES,
        "timeout_seconds": pilot_registration.TIMEOUT_SECONDS,
        "nonstandard_config": False,
        "operator_image_sha256": pilot_registration.OPERATOR_IMAGE_SHA256,
        "artifact_parser": pilot_registration.ARTIFACT_PARSER,
        "artifact_parser_version": pilot_registration.ARTIFACT_PARSER_VERSION,
        "judge_live_probe_receipt_sha256":
            SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
        "judge_live_probe_execution_sha256":
            SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256,
        "sandbox_cmd": [
            sys.executable,
            str(HERE / pilot_registration.PLATFORM_WRAPPER.get(
                sys.platform, pilot_registration.DEFAULT_WRAPPER)),
            *pilot_registration.SANDBOX_TAIL,
        ],
        "drift_fetch_cmd": list(pilot_registration.DRIFT_FETCH_CMD),
        "backend_version": pilot_registration.BACKEND_VERSION,
        "backend_version_cmd": list(pilot_registration.BACKEND_VERSION_CMD),
    }
    for arm, install in installs.items():
        config["arms"][arm] = {
            "installation_dir": str(install),
            "sha256": pilot_registration.INSTALL_SHA256[arm],
            "model": pilot_registration.MODEL,
            "effort": pilot_registration.EFFORT,
            "entrypoint": pilot_registration.ENTRYPOINT,
        }
    config["arms"]["ablation"].update({
        "forbid_subagents": True,
        "schedule_tasks": [tasks[0].name, tasks[2].name],
    })

    materials = [*tasks, *contexts.values(), *prompts.values(),
                 *schemas.values(), rubric, coverage, snapshot]
    seal = sealed / "seal-manifest.json"
    seal.write_text(json.dumps({
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "nonstandard_config": False,
        "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
        "judge_retry_policy": runner.PILOT_V2_JUDGE_RETRY_POLICY,
        "judge_output_policy": runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
        "judge_live_probe": runner.protocol_v2_live_probe_binding(config),
        "pilot_runtime_registration_sha256": (
            pilot_registration.standard_v2_runtime_registration_sha256()),
        "aggregation_policy": runner.PILOT_V2_AGGREGATION_POLICY,
        "judge_prompts": {
            role: path.relative_to(sealed).as_posix()
            for role, path in prompts.items()
        },
        "judge_response_schemas": {
            role: path.relative_to(sealed).as_posix()
            for role, path in schemas.items()
        },
        "quality_rubric": rubric.relative_to(sealed).as_posix(),
        "coverage_matrix": coverage.relative_to(sealed).as_posix(),
        "task_contexts": {
            task: path.relative_to(sealed).as_posix()
            for task, path in contexts.items()
        },
        "ablation_tasks": [tasks[0].name, tasks[2].name],
        "snapshot_sources": {
            "snapshots/reference.txt":
                "https://example.invalid/live/reference.txt",
        },
        "judge_config": {
            "judge_backend_cmd": judge_cmd,
            "judge_model": config["judge_model"],
            "judge_effort": config["judge_effort"],
        },
        "files": {
            path.relative_to(sealed).as_posix(): hashlib.sha256(
                path.read_bytes()).hexdigest()
            for path in materials
        },
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    config["seal_manifest"] = str(seal)
    config["seal_package_sha256"] = hashlib.sha256(
        seal.read_bytes()).hexdigest()
    # This fixture is the one process-local synthetic standard round.  Its
    # seal bytes are identical for the golden and zero-document variants;
    # registering that digest exercises the same fail-closed direct-runner
    # boundary without adding a runtime bypass flag.
    registered_fixture_seal = config["seal_package_sha256"]
    if (pilot_registration.seal_registration_pending()
            or pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256
            == registered_fixture_seal):
        pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256 = (
            registered_fixture_seal)
    else:
        raise AssertionError(
            "synthetic standard fixtures produced different seal digests")
    config_path = root / "runner-config.json"
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    task_paths = [str(task) for task in tasks]
    schedule = runner.make_schedule(
        config, task_paths, 3, seed=runner.PILOT_V2_SCHEDULE_SEED)
    schedule_path = root / "schedule.json"
    schedule_path.write_text(
        json.dumps(schedule, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summaries = []
    doc_task = {}
    for position, entry in enumerate(schedule["entries"]):
        run_id = f"{position + 1:012x}"
        doc_name = f"run-{run_id}-anon.md"
        doc_bytes = f"# Synthetic aggregate document {position + 1}\n".encode()
        (output / doc_name).write_bytes(doc_bytes)
        (output / f"run-{run_id}-raw.md").write_bytes(doc_bytes)
        tokens = {"baseline": 100, "candidate": 75, "ablation": 40}[
            entry["arm"]]
        wall = {"baseline": 10, "candidate": 8, "ablation": 5}[
            entry["arm"]]
        nodes = [{
            "model": config["arms"][entry["arm"]]["model"],
            "effort": "high",
            "input_tokens": tokens - 10,
            "output_tokens": 10,
            "tool_calls": 1,
            "subagent": False,
            "subagent_id": None,
            "subagent_launches": 0,
        }]
        record = {
            "run_id": run_id,
            "arm": entry["arm"],
            "task": entry["task"],
            "registered_model": config["arms"][entry["arm"]]["model"],
            "effort": config["arms"][entry["arm"]]["effort"],
            "installation_sha256": config["arms"][entry["arm"]]["sha256"],
            "backend_version": config["backend_version"],
            "entrypoint": config["arms"][entry["arm"]]["entrypoint"],
            "standard_topology": True,
            "target_sha": target_sha,
            "attempt": 1,
            "status": "completed",
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": (
                runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
            "runtime_pins": runner.protocol_v2_runtime_pins(config),
            "schedule_digest": runner.schedule_digest(schedule),
            "schedule_index": entry["index"],
            "failure_kind": None,
            "artifact_gate": "passed",
            "raw_sha256": hashlib.sha256(doc_bytes).hexdigest(),
            "artifact_sha256": hashlib.sha256(doc_bytes).hexdigest(),
            "config_digest": runner.config_digest(config),
            "task_sha256": schedule["task_digests"][entry["task"]],
            "telemetry_policy_id": (
                runner.PILOT_V2_AGGREGATION_POLICY["telemetry"]),
            "telemetry_eligible": True,
            "telemetry_exclusion_reason": None,
            "wall_seconds": wall,
            "accounting": runner.account(nodes),
            "nodes": nodes,
            "effort_capture": runner.validate_efforts(nodes, "high"),
            "interventions": 0,
            "interventions_log": [],
        }
        record_path = output / f"run-{run_id}.json"
        record_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summaries.append({
            "index": entry["index"],
            "arm": entry["arm"],
            "task": entry["task"],
            "run_id": run_id,
            "status": "completed",
            "attempts": 1,
            "artifact_sha256": record["artifact_sha256"],
            "diagnostic_sha256": None,
            "raw_sha256": record["raw_sha256"],
            "task_sha256": record["task_sha256"],
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": (
                runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
            "runtime_pins": runner.protocol_v2_runtime_pins(config),
            "schedule_digest": record["schedule_digest"],
            "failure_kind": None,
            "artifact_gate": "passed",
            "telemetry_policy_id": record["telemetry_policy_id"],
            "telemetry_eligible": True,
            "telemetry_exclusion_reason": None,
        })
        doc_task[doc_name] = entry["task"]

    manifest = {
        "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
        "environment_policy_id": runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "schedule": str(schedule_path),
        "seed": schedule["seed"],
        "schedule_digest": runner.schedule_digest(schedule),
        "config_digest": runner.config_digest(config),
        "replicates": 3,
        "nonstandard": False,
        "results": summaries,
        "complete": True,
    }
    manifest_path = output / "schedule-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    docs = [f"run-{summary['run_id']}-anon.md" for summary in summaries]
    unchanged_drift = {
        "changed": [],
        "material": False,
        "adjudications": {},
    }
    drift_by_doc = {
        doc_name: unchanged_drift
        for doc_name in docs
        if Path(doc_task[doc_name]).name == "holdout-v2-5.md"
    }
    judge_manifests = {}
    parsed_by_role = {
        "scorer": judge_contract.validate_response(
            json.dumps(mock_claude.SCORER_RESPONSE), "scorer"),
        "verifier": judge_contract.validate_response(
            json.dumps(mock_claude.VERIFIER_RESPONSE), "verifier"),
    }
    for role in ("scorer", "verifier"):
        scoring_id = "5c0ae001" if role == "scorer" else "5c0ae002"
        scoring_seed = (runner.PILOT_V2_SCORER_SEED
                        if role == "scorer"
                        else runner.PILOT_V2_VERIFIER_SEED)
        schema_sha = hashlib.sha256(schemas[role].read_bytes()).hexdigest()
        response = json.dumps(parsed_by_role[role], sort_keys=True)
        results = []
        presentation_order = list(range(len(docs)))
        random.Random(scoring_seed).shuffle(presentation_order)
        for presentation_index, doc_index in enumerate(presentation_order):
            doc_name = docs[doc_index]
            session_id = f"aggregate-{role}-{presentation_index:02d}"
            raw_stream = "\n".join((
                json.dumps({
                    "type": "node",
                    "model": config["judge_model"],
                    "effort": config["judge_effort"],
                    "tool_calls": 0,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }, sort_keys=True),
                json.dumps({
                    "type": "result",
                    "subtype": "success",
                    "session_id": session_id,
                    "result": response,
                    "structured_output": parsed_by_role[role],
                }, sort_keys=True),
            ))
            (parsed_session, judge_nodes, parsed_response,
             parsed_structured, stream_defects) = (
                runner._parse_judge_stream_tolerant(
                    raw_stream, require_structured_output=True)
            )
            if (parsed_session != session_id or parsed_response != response
                    or parsed_structured != parsed_by_role[role]
                    or stream_defects):
                raise AssertionError("invalid synthetic v2 judge stream")
            result = {
                "doc": str(output / doc_name),
                "presentation_index": presentation_index,
                "scoring_id": scoring_id,
                "role": role,
                "axis": "all-docs",
                "attempt": 1,
                "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
                "environment_policy_id": (
                    runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
                "response_schema_version": (
                    judge_contract.RESPONSE_SCHEMA_VERSION),
                "schema_sha256": schema_sha,
                "judge_output_policy": (
                    runner.PILOT_V2_JUDGE_OUTPUT_POLICY),
                "structured_output_schema_sha256": (
                    judge_contract.structured_output_schema_sha256(role)),
                "final_response_contract_sha256": (
                    judge_contract.final_response_contract_sha256(role)),
                "judge_prompt_sha256": hashlib.sha256(
                    prompts[role].read_bytes()).hexdigest(),
                "quality_rubric_sha256": hashlib.sha256(
                    rubric.read_bytes()).hexdigest(),
                "config_digest": runner.config_digest(config),
                "session_id": session_id,
                "profile": str(
                    root / f"isolated-{role}-{presentation_index}-profile"),
                "cwd": str(
                    root / f"isolated-{role}-{presentation_index}-workdir"),
                "backend_version": config["backend_version"],
                "scoring_seed": scoring_seed,
                "scheduled": True,
                "judge_model": config["judge_model"],
                "judge_effort": config["judge_effort"],
                "profile_settings": (
                    runner.VERIFIER_SETTINGS
                    if role == "verifier" else runner.JUDGE_SETTINGS
                ),
                "task": doc_task[doc_name],
                "task_context": str(
                    contexts[Path(doc_task[doc_name]).name]),
                "seal_manifest": str(seal),
                "snapshots": (
                    str(snapshot.parent)
                    if Path(doc_task[doc_name]).name
                    == "holdout-v2-5.md" else None),
                "source_drift": drift_by_doc.get(doc_name),
                "raw_stream_limit_bytes": (
                    runner.PILOT_V2_MAX_RAW_STREAM_BYTES),
                "raw_stream_sidecar": str(
                    output / (
                        f"judge-{scoring_id}-{presentation_index}-attempt-1-"
                        "raw-stream.txt"
                    )
                ),
                "raw_stream": raw_stream,
                "raw_stream_external": False,
                "raw_stream_external_reason": None,
                "raw_stream_bytes": len(raw_stream.encode("utf-8")),
                "raw_stream_sha256": hashlib.sha256(
                    raw_stream.encode("utf-8")).hexdigest(),
                "nodes": judge_nodes,
                "launch_defects": [],
                "response": response,
                "structured_output": parsed_by_role[role],
                "response_sha256": hashlib.sha256(
                    response.encode("utf-8")).hexdigest(),
                "schema_valid": True,
                "transport_invalid": False,
                "effort_capture": runner.validate_efforts(
                    judge_nodes, config["judge_effort"]),
                "parsed_response": parsed_by_role[role],
                "validation": {"valid": True, "defects": []},
                "accounting": runner.account(judge_nodes),
            }
            if role == "verifier":
                numerator = parsed_by_role[role]["supported_claims"]
                denominator = parsed_by_role[role]["verifiable_claims"]
                result.update({
                    "evidence_sha": target_sha,
                    "evidence_accuracy_numerator": numerator,
                    "evidence_accuracy_denominator": denominator,
                    "evidence_accuracy": (
                        numerator / denominator if denominator else 0.0),
                })
            canonical_path = output / (
                f"judge-{scoring_id}-{presentation_index}.json")
            canonical_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (output / (
                f"judge-{scoring_id}-{presentation_index}-attempt-1.json"
            )).write_bytes(canonical_path.read_bytes())
            results.append(result)
        identity = {
            "scoring_seed": scoring_seed,
            "manifest": str(manifest_path),
            "config_digest": runner.config_digest(config),
            "role": role,
            "axis": "all-docs",
            "docs": docs,
            "drift_decisions": {
                "inconclusive": [],
                "notes_digest": hashlib.sha256(json.dumps(
                    drift_by_doc, sort_keys=True).encode("utf-8")).hexdigest(),
                "tasks": {
                    "holdout-v2-5.md": {
                        "observed_sha256": {
                            "snapshots/reference.txt": hashlib.sha256(
                                snapshot.read_bytes()).hexdigest(),
                        },
                        "changed": [],
                        "material": False,
                        "adjudications": {},
                    },
                },
            },
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": (
                runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
            "response_schema_version": judge_contract.RESPONSE_SCHEMA_VERSION,
            "schema_sha256": schema_sha,
            "judge_output_policy": runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
            "structured_output_schema_sha256": (
                judge_contract.structured_output_schema_sha256(role)),
            "final_response_contract_sha256": (
                judge_contract.final_response_contract_sha256(role)),
            "judge_prompt_sha256": hashlib.sha256(
                prompts[role].read_bytes()).hexdigest(),
            "quality_rubric_sha256": hashlib.sha256(
                rubric.read_bytes()).hexdigest(),
        }
        judge_manifest = output / (
            f"scoring-{role}-all-docs-manifest.json")
        judge_manifest.write_text(json.dumps({
            "scoring_id": scoring_id,
            "identity": identity,
            "results": results,
            "complete": True,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        judge_manifests[role] = judge_manifest

    return {
        "root": root,
        "config": config,
        "config_path": config_path,
        "seal": seal,
        "schedule": schedule_path,
        "manifest": manifest_path,
        "judge_manifests": judge_manifests,
        "first_run_record": output / f"run-{summaries[0]['run_id']}.json",
        "run_count": len(summaries),
        "judge_count": len(docs) * 2,
    }


def _run_preflight(registration_isolation_ok):
    global SEAL_SHA, SEAL_PATH
    notes = []
    ok = True
    current_registration = _registration_state()
    ok &= check(
        "synthetic fixtures isolate and restore injected non-pending seal",
        registration_isolation_ok
        and pilot_registration.seal_registration_pending()
        and current_registration["shared"][1:] == (
            SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
            SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256)
        and current_registration["probe_operator"] == (
            pilot_registration.PENDING_SEAL_PACKAGE_SHA256,
            SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
            SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256),
        notes)
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)

        # Transport flags belong to the backend argv, not the sandbox
        # prefix: a wrapper's own --verbose must not suppress the flag that
        # Claude 2.1.220 requires with stream-json output.
        collision_config = {
            "nonstandard_config": True,
            "sandbox_cmd": ["sandbox", "--verbose", "{workdir}",
                            "{profile}", "--"],
        }
        collision_cmd = runner.apply_sandbox(
            collision_config,
            runner.with_stream_json_transport(["claude"]), ws, ws)
        ok &= check(
            "backend stream transport ignores wrapper --verbose collision",
            collision_cmd.count("--verbose") == 2
            and collision_cmd[-2:] == ["claude", "--verbose"], notes)
        existing_verbose = runner.with_stream_json_transport(
            ["claude", "--verbose"])
        ok &= check(
            "backend stream transport adds verbose idempotently",
            existing_verbose == ["claude", "--verbose"], notes)

        # All evaluated and judge input is private transport data. Claude
        # 2.1.220's `-p` switch reads stdin when there is no positional
        # prompt; prove initial, resumed/continuation, wrapper, and capped
        # judge launches all use that form and preserve bytes exactly.
        transport_receipt = ws / "stdin-transport.ndjson"
        transport_cmd = runner.with_stream_json_transport([
            sys.executable, str(HERE / "mock_claude.py"),
            "--mode", "no-artifact", "--transport-receipt-file",
            str(transport_receipt),
        ])
        initial_canary = "PRIVATE-INITIAL-PROMPT-CANARY\nточные байты 🧪"
        continuation_canary = "PRIVATE-CONTINUATION-PROMPT-CANARY — 継続"
        runner.spawn_session(
            transport_cmd, initial_canary, ws, os.environ.copy(), 10)
        runner.spawn_session(
            transport_cmd, continuation_canary, ws, os.environ.copy(), 10,
            resume="session-resume-token")
        transport_rows = [
            json.loads(line)
            for line in transport_receipt.read_text(
                encoding="utf-8").splitlines()
        ]
        ok &= check(
            "initial and continuation prompts travel only through stdin",
            len(transport_rows) == 2
            and [row["prompt"] for row in transport_rows]
            == [initial_canary, continuation_canary]
            and all(row["prompt_source"] == "stdin"
                    for row in transport_rows)
            and all(
                canary not in argv_part
                for row in transport_rows
                for argv_part in row["argv"]
                for canary in (initial_canary, continuation_canary)
            )
            and "--resume" not in transport_rows[0]["argv"]
            and transport_rows[1]["argv"][
                transport_rows[1]["argv"].index("--resume") + 1]
            == "session-resume-token"
            and all(
                row["argv"][-3:]
                == ["-p", "--output-format", "stream-json"]
                for row in transport_rows
            ), notes)

        passthrough = ws / "sandbox-passthrough.py"
        passthrough.write_text(
            "import os,sys\n"
            "cut=sys.argv.index('--')\n"
            "os.execv(sys.argv[cut+1], sys.argv[cut+1:])\n",
            encoding="utf-8",
        )
        wrapper_receipt = ws / "wrapper-stdin-transport.ndjson"
        wrapped_backend = runner.with_stream_json_transport([
            sys.executable, str(HERE / "mock_claude.py"),
            "--mode", "no-artifact", "--transport-receipt-file",
            str(wrapper_receipt),
        ])
        wrapped_cmd = runner.apply_sandbox({
            "nonstandard_config": True,
            "sandbox_cmd": [
                sys.executable, str(passthrough), "--verbose",
                "{workdir}", "{profile}", "--",
            ],
        }, wrapped_backend, ws, ws)
        wrapper_canary = "PRIVATE-WRAPPER-PROMPT-CANARY"
        runner.spawn_session(
            wrapped_cmd, wrapper_canary, ws, os.environ.copy(), 10)
        wrapper_row = json.loads(
            wrapper_receipt.read_text(encoding="utf-8").strip())
        ok &= check(
            "wrapper verbose collision keeps prompt off argv and on stdin",
            wrapped_cmd.count("--verbose") == 2
            and all(wrapper_canary not in part for part in wrapped_cmd)
            and wrapper_row["prompt_source"] == "stdin"
            and wrapper_row["prompt"] == wrapper_canary
            and all(wrapper_canary not in part
                    for part in wrapper_row["argv"]), notes)

        judge_receipt = ws / "judge-stdin-transport.ndjson"
        judge_cmd = runner.with_stream_json_transport([
            sys.executable, str(HERE / "mock_claude.py"),
            "--mode", "judge-auto", "--transport-receipt-file",
            str(judge_receipt),
        ])
        judge_canary = "SCORER-CONTRACT\nPRIVATE-JUDGE-PROMPT-CANARY"
        (judge_stream, _judge_bytes, _judge_digest, judge_defects,
         judge_external) = runner.spawn_judge_session_capped(
            judge_cmd, judge_canary, ws, os.environ.copy(), 10,
            ws / "judge-stdin-stream.jsonl",
            runner.PILOT_V2_MAX_RAW_STREAM_BYTES,
            structured_output_schema=(
                judge_contract.structured_output_schema_text("scorer")))
        judge_row = json.loads(
            judge_receipt.read_text(encoding="utf-8").strip())
        (_sid, _nodes, judge_response, judge_structured,
         stream_defects) = runner._parse_judge_stream_tolerant(
            judge_stream, require_structured_output=True)
        ok &= check(
            "capped scorer/verifier transport sends sealed input via stdin",
            not judge_defects and not stream_defects and not judge_external
            and judge_row["prompt_source"] == "stdin"
            and judge_row["prompt"] == judge_canary
            and all(judge_canary not in part for part in judge_row["argv"])
            and judge_row["argv"].count("--json-schema") == 1
            and judge_row["argv"][
                judge_row["argv"].index("--json-schema") + 1]
            == judge_contract.structured_output_schema_text("scorer")
            and judge_structured == mock_claude.SCORER_RESPONSE
            and json.loads(judge_response)["total"] == 8.0, notes)

        probe_config, _probe_install = build_config(ws, "normal")
        probe_operator = judge_live_probe.operator_contract
        probe_config.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "judge_live_probe_receipt_sha256":
                pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            "judge_live_probe_execution_sha256":
                pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
            "judge_backend_cmd": [
                sys.executable, str(HERE / "mock_claude.py"),
                "--mode", "judge-auto", "--effort", "{effort}",
            ],
            "sandbox_cmd": [
                sys.executable,
                str(HERE / probe_operator.PLATFORM_WRAPPER.get(
                    sys.platform, probe_operator.DEFAULT_WRAPPER)),
                *probe_operator.REGISTERED_SANDBOX_TAIL,
            ],
        })
        probe_round = ws / judge_live_probe.ROUND_NAMESPACE
        (probe_round / judge_live_probe.PACKAGE_NAMESPACE).mkdir(
            parents=True)
        probe_config["seal_manifest"] = str(
            probe_round / judge_live_probe.PACKAGE_NAMESPACE
            / seal_package.MANIFEST_NAME)
        probe_config["seal_package_sha256"] = (
            probe_operator.REGISTERED_SEAL_PACKAGE_SHA256)
        probe_output = probe_round / judge_live_probe.OUTPUT_NAMESPACE
        original_probe_apply_sandbox = runner.apply_sandbox
        original_probe_pin_gate = probe_operator.live_probe_config_problems

        def apply_mock_probe_sandbox(_config, command, workdir, _profile):
            return [
                sys.executable, str(HERE / "mock_sandbox.py"),
                str(workdir), "--", *command,
            ]

        runner.apply_sandbox = apply_mock_probe_sandbox
        probe_operator.live_probe_config_problems = lambda _config: []
        try:
            probe_receipt = judge_live_probe.run_probe(probe_config)
        finally:
            runner.apply_sandbox = original_probe_apply_sandbox
        probe_reverified = judge_live_probe.verify_receipt(
            probe_config, probe_backend=False)
        original_probe_spawn = runner.spawn_judge_session_capped
        replay_launches = []

        def forbidden_probe_relaunch(*args, **kwargs):
            replay_launches.append((args, kwargs))
            raise AssertionError("existing probe namespace relaunched a model")

        runner.spawn_judge_session_capped = forbidden_probe_relaunch
        try:
            replay_receipt = judge_live_probe.run_probe(probe_config)
            incomplete_config = json.loads(json.dumps(probe_config))
            incomplete_round = ws / "incomplete" / judge_live_probe.ROUND_NAMESPACE
            (incomplete_round / judge_live_probe.PACKAGE_NAMESPACE).mkdir(
                parents=True)
            incomplete_config["seal_manifest"] = str(
                incomplete_round / judge_live_probe.PACKAGE_NAMESPACE
                / seal_package.MANIFEST_NAME)
            (incomplete_round / judge_live_probe.OUTPUT_NAMESPACE).mkdir()
            try:
                judge_live_probe.run_probe(incomplete_config)
                incomplete_namespace_rejected = False
            except judge_live_probe.ProbeError:
                incomplete_namespace_rejected = True
        finally:
            runner.spawn_judge_session_capped = original_probe_spawn
        probe_help = subprocess.run(
            [sys.executable, str(HERE / "judge_live_probe.py"), "--help"],
            capture_output=True, text=True)
        probe_out_arg = subprocess.run([
            sys.executable, str(HERE / "judge_live_probe.py"),
            "--config", str(ws / "unused.json"), "--out", str(ws / "x"),
            "--verify",
        ], capture_output=True, text=True)
        probe_raw = (
            probe_output / judge_live_probe.RAW_NAMES["scorer"])
        probe_raw_bytes = probe_raw.read_bytes()
        alternate_probe_events = [
            json.loads(line) for line in probe_raw_bytes.decode("utf-8")
            .splitlines() if line.strip()
        ]
        for event in alternate_probe_events:
            if event.get("type") == "result":
                alternate = dict(event["structured_output"])
                alternate["summary"] = "Schema-valid but not the probe value."
                event["structured_output"] = alternate
                event["result"] = json.dumps(alternate)
        try:
            judge_live_probe._validated_observation(
                "scorer", "\n".join(json.dumps(event)
                                    for event in alternate_probe_events),
                probe_config)
            alternate_probe_rejected = False
        except judge_live_probe.ProbeError:
            alternate_probe_rejected = True
        probe_raw.write_bytes(probe_raw_bytes + b"\n")
        try:
            judge_live_probe.verify_receipt(
                probe_config, probe_backend=False)
            probe_tamper_rejected = False
        except judge_live_probe.ProbeError:
            probe_tamper_rejected = True
        finally:
            probe_raw.write_bytes(probe_raw_bytes)
        probe_receipt_path = probe_output / judge_live_probe.RECEIPT_NAME
        probe_receipt_bytes = probe_receipt_path.read_bytes()
        actual_probe_receipt_sha = hashlib.sha256(
            probe_receipt_bytes).hexdigest()
        actual_probe_execution_sha = probe_receipt[
            "identity"]["execution_sha256"]
        saved_probe_registration = (
            pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
        )
        pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_RECEIPT_SHA256)
        pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_EXECUTION_SHA256)
        pending_probe_registration_rejected = bool(
            probe_operator.live_probe_receipt_problem(
                probe_config, probe_backend=False))
        pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
            actual_probe_receipt_sha)
        pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
            actual_probe_execution_sha)
        registered_probe_config = json.loads(json.dumps(probe_config))
        registered_probe_config["judge_live_probe_receipt_sha256"] = (
            actual_probe_receipt_sha)
        registered_probe_config["judge_live_probe_execution_sha256"] = (
            actual_probe_execution_sha)
        registered_probe_valid = (
            probe_operator.live_probe_receipt_problem(
                registered_probe_config, probe_backend=False) is None)
        probe_receipt_path.write_bytes(probe_receipt_bytes + b"\n")
        try:
            registered_probe_tamper_rejected = bool(
                probe_operator.live_probe_receipt_problem(
                    registered_probe_config, probe_backend=False))
        finally:
            probe_receipt_path.write_bytes(probe_receipt_bytes)
            (pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
             pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256) = (
                saved_probe_registration)
        original_probe_file_sha256 = judge_live_probe._file_sha256

        def drift_probe_code_digest(path):
            if Path(path).resolve() == Path(judge_live_probe.__file__).resolve():
                return "0" * 64
            return original_probe_file_sha256(path)

        judge_live_probe._file_sha256 = drift_probe_code_digest
        try:
            judge_live_probe.verify_receipt(
                probe_config, probe_backend=False)
            probe_code_drift_rejected = False
        except judge_live_probe.ProbeError:
            probe_code_drift_rejected = True
        finally:
            judge_live_probe._file_sha256 = original_probe_file_sha256
            probe_operator.live_probe_config_problems = original_probe_pin_gate
        ok &= check(
            "pre-seal live probe covers both structured judge roles once",
            probe_receipt == probe_reverified
            and set(probe_receipt["observations"])
            == {"scorer", "verifier"}
            and probe_receipt["identity"]["judge_output_policy"]
            == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
            and all(
                probe_receipt["observations"][role][
                    "structured_output_schema_sha256"]
                == judge_contract.structured_output_schema_sha256(role)
                for role in ("scorer", "verifier"))
            and probe_receipt["identity"].get(
                "final_response_contract_sha256")
            == pilot_registration.FINAL_RESPONSE_CONTRACT_SHA256
            and all(
                probe_receipt["observations"][role].get(
                    "final_response_contract_sha256")
                == judge_contract.final_response_contract_sha256(role)
                for role in ("scorer", "verifier"))
            and all(
                observation["backend_version_observed"]
                == probe_config["backend_version"]
                for observation in probe_receipt["observations"].values())
            and probe_receipt["identity"]["runtime_pins"]
            == runner.protocol_v2_runtime_pins(probe_config)
            and probe_receipt["identity"]["probe_sha256"]
            == original_probe_file_sha256(judge_live_probe.__file__)
            and probe_receipt["identity"]["sandbox_wrapper_sha256"]
            == original_probe_file_sha256(probe_config["sandbox_cmd"][1])
            and replay_receipt == probe_receipt and not replay_launches
            and incomplete_namespace_rejected
            and probe_help.returncode == 0 and "--out" not in probe_help.stdout
            and judge_live_probe.ROUND_NAMESPACE == "holdout-v2-round7"
            and "holdout-v2-round7" in probe_help.stdout
            and probe_out_arg.returncode == 2
            and "unrecognized arguments: --out" in probe_out_arg.stderr
            and pending_probe_registration_rejected
            and registered_probe_valid
            and registered_probe_tamper_rejected
            and alternate_probe_rejected and probe_tamper_rejected
            and probe_code_drift_rejected,
            notes)

        fetch_root = ws / "stdin-fetch-root"
        (fetch_root / "source").mkdir(parents=True)
        (fetch_root / "source" / "reference.txt").write_bytes(
            b"private live source bytes\n")
        fetch_transport_receipt = ws / "fetch-transport-receipt.ndjson"
        fetch_url = (
            "https://private-source-canary.mock.invalid/live/"
            "source/reference.txt")
        os.environ["MOCK_LIVE_ROOT"] = str(fetch_root)
        os.environ["MOCK_FETCH_TRANSPORT_LOG"] = str(
            fetch_transport_receipt)
        fetch_cmd = [
            sys.executable, str(HERE / "mock_fetch.py"), "{dest}",
        ]
        try:
            fetched = runner._fetch_live_source(fetch_cmd, fetch_url, 10)
            fetch_row = json.loads(fetch_transport_receipt.read_text(
                encoding="utf-8").strip())
            before_bad_transport = fetch_transport_receipt.read_bytes()
            try:
                runner._fetch_live_source(
                    [sys.executable, str(HERE / "mock_fetch.py"),
                     "{url}", "{dest}"],
                    fetch_url, 10)
                argv_url_rejected = False
            except runner.InfraFailure as exc:
                argv_url_rejected = (
                    "only through stdin" in str(exc)
                    and fetch_url not in str(exc))
            after_bad_transport = fetch_transport_receipt.read_bytes()
            missing_url = (
                "https://private-error-canary.mock.invalid/live/"
                "source/missing.txt")
            try:
                runner._fetch_live_source(fetch_cmd, missing_url, 10)
                fetch_error_private = False
            except runner.InfraFailure as exc:
                fetch_error_private = (
                    "live-source fetch failed" in str(exc)
                    and missing_url not in str(exc)
                    and "private-error-canary" not in str(exc))
        finally:
            os.environ.pop("MOCK_FETCH_TRANSPORT_LOG", None)
            os.environ.pop("MOCK_LIVE_ROOT", None)
        ok &= check(
            "live-source URL travels only through stdin and stays out of errors",
            fetched == b"private live source bytes\n"
            and fetch_url not in fetch_row["argv"]
            and all(fetch_url not in part for part in fetch_row["argv"])
            and fetch_row["stdin"] == f'url = "{fetch_url}"\n'
            and argv_url_rejected
            and before_bad_transport == after_bad_transport
            and fetch_error_private,
            notes)

        mock_base = [sys.executable, str(HERE / "mock_claude.py"),
                     "--mode", "no-artifact", "-p", "probe"]
        implicit_text = subprocess.run(
            mock_base, cwd=ws, capture_output=True, text=True)
        missing_verbose = subprocess.run(
            mock_base + ["--output-format", "stream-json"],
            cwd=ws, capture_output=True, text=True)
        explicit_verbose = subprocess.run(
            mock_base + ["--verbose", "--output-format", "stream-json"],
            cwd=ws, capture_output=True, text=True)
        ok &= check(
            "mock accepts text default and enforces stream-json verbose",
            implicit_text.returncode == 0
            and missing_verbose.returncode == 2
            and "requires --verbose" in missing_verbose.stderr
            and explicit_verbose.returncode == 0, notes)

        # Protocol-v2 judge outputs are data, not prose to be recovered.
        # Prove the public, seal-bound role contracts directly before the
        # session/batch tests exercise their crash-safe retry integration.
        scorer_json = json.dumps(mock_claude.SCORER_RESPONSE)
        verifier_json = json.dumps(mock_claude.VERIFIER_RESPONSE)
        scorer_parsed = judge_contract.validate_response(
            scorer_json, "scorer")
        verifier_parsed = judge_contract.validate_response(
            verifier_json, "verifier")
        scorer_rationale_note = json.loads(scorer_json)
        scorer_rationale_note["coverage"]["rationale_note"] = "forbidden"
        scorer_code_context = json.loads(scorer_json)
        scorer_code_context["coverage"]["code_context"] = "forbidden"
        verifier_wrong_sum = json.loads(verifier_json)
        verifier_wrong_sum["verifiable_claims"] = 3
        verifier_wrong_ledger_length = json.loads(verifier_json)
        verifier_wrong_ledger_length["claim_ledger"].pop()
        verifier_wrong_status_count = json.loads(verifier_json)
        verifier_wrong_status_count["claim_ledger"][0]["status"] = (
            "unsupported")
        verifier_wrong_critical_count = json.loads(verifier_json)
        verifier_wrong_critical_count["critical_error_count"] = 1
        verifier_empty_citations = json.loads(verifier_json)
        verifier_empty_citations["claim_ledger"][0][
            "candidate_citations"] = []
        verifier_empty_evidence = json.loads(verifier_json)
        verifier_empty_evidence["claim_ledger"][0]["evidence"] = []
        verifier_blank_text = json.loads(verifier_json)
        verifier_blank_text["summary"] = " \t "
        verifier_blank_array_item = json.loads(verifier_json)
        verifier_blank_array_item["claim_ledger"][0][
            "candidate_citations"] = [" \t "]
        verifier_duplicate_critical = json.loads(verifier_json)
        verifier_duplicate_critical["critical_errors"] = [
            {
                "proposition": "ＦＯＯ.",
                "category": "architecture",
                "rationale": "first form",
                "evidence": ["mock/file.py:1"],
            },
            {
                "proposition": "foo",
                "category": "architecture",
                "rationale": "normalized duplicate",
                "evidence": ["mock/file.py:1"],
            },
        ]
        verifier_duplicate_critical["critical_error_count"] = 2
        verifier_semantic_cases = [
            (verifier_wrong_sum,
             "verifiable_claims must equal supported + unsupported + "
             "unverifiable"),
            (verifier_wrong_ledger_length,
             "claim_ledger length must equal verifiable_claims"),
            (verifier_wrong_status_count,
             "claim_ledger supported count must equal supported_claims"),
            (verifier_wrong_critical_count,
             "critical_error_count must equal critical_errors length"),
            (verifier_empty_citations,
             "claim_ledger[0]: supported claims require citations and "
             "evidence"),
            (verifier_empty_evidence,
             "claim_ledger[0]: supported claims require citations and "
             "evidence"),
            (verifier_blank_text, "summary must be nonempty"),
            (verifier_blank_array_item,
             "claim_ledger[0].candidate_citations[0] must be nonempty"),
            (verifier_duplicate_critical,
             "critical error propositions must be unique after "
             "normalization"),
        ]
        invalid_judge_responses = [
            ("scorer", f"```json\n{scorer_json}\n```"),
            ("scorer", "analysis before the JSON object"),
            ("scorer", '{"summary":"a","summary":"b"}'),
            ("scorer", scorer_json.replace('3.5', 'NaN', 1)),
            ("scorer", scorer_json[:-1] + ',"extra":1}'),
            ("scorer", json.dumps(scorer_rationale_note)),
            ("scorer", json.dumps(scorer_code_context)),
            ("scorer", scorer_json.replace('"total": 8.0',
                                             '"total": 8.25')),
            ("scorer", scorer_json.replace('"score": 3.5',
                                             '"score": true', 1)),
            ("verifier", verifier_json[:-1]
             + ',"evidence_accuracy":0.5}'),
            ("verifier", json.dumps(verifier_wrong_sum)),
            ("verifier", json.dumps(verifier_wrong_ledger_length)),
            ("verifier", json.dumps(verifier_wrong_status_count)),
            ("verifier", json.dumps(verifier_wrong_critical_count)),
        ]
        contract_rejects = True
        for role, response in invalid_judge_responses:
            try:
                judge_contract.validate_response(response, role)
                contract_rejects = False
            except judge_contract.JudgeResponseError:
                pass
        semantic_defects_exact = True
        for value, expected_error in verifier_semantic_cases:
            try:
                judge_contract.validate_response(
                    json.dumps(value), "verifier")
                semantic_defects_exact = False
            except judge_contract.JudgeResponseError as exc:
                if str(exc) != expected_error:
                    semantic_defects_exact = False

        structured_schemas = {
            role: judge_contract.structured_output_schema(role)
            for role in ("scorer", "verifier")
        }
        unsupported_structural_keywords = {
            "minimum", "maximum", "multipleOf", "minLength", "minItems",
        }

        def structural_nodes(value):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from structural_nodes(child)
            elif isinstance(value, list):
                for child in value:
                    yield from structural_nodes(child)

        structural_nodes_by_role = {
            role: list(structural_nodes(schema))
            for role, schema in structured_schemas.items()
        }
        structural_shape_ok = (
            set(structured_schemas["scorer"]["properties"])
            == set(judge_contract.SCORER_KEYS)
            and set(structured_schemas["scorer"]["properties"][
                "coverage"]["properties"])
            == set(judge_contract.SCORER_COMPONENT_KEYS)
            and set(structured_schemas["verifier"]["properties"])
            == set(judge_contract.VERIFIER_KEYS)
            and set(structured_schemas["verifier"]["properties"][
                "claim_ledger"]["items"]["properties"])
            == set(judge_contract.CLAIM_KEYS)
            and all(
                node.get("additionalProperties") is False
                for nodes in structural_nodes_by_role.values()
                for node in nodes if node.get("type") == "object")
            and all(
                not unsupported_structural_keywords.intersection(node)
                for nodes in structural_nodes_by_role.values()
                for node in nodes)
        )
        structural_digests = {
            role: judge_contract.structured_output_schema_sha256(role)
            for role in ("scorer", "verifier")
        }
        final_contract_digests = {
            role: judge_contract.final_response_contract_sha256(role)
            for role in ("scorer", "verifier")
        }
        independently_hashed_final_contracts = {
            role: hashlib.sha256(
                judge_contract.output_contract_reminder(role).encode(
                    "utf-8")
            ).hexdigest()
            for role in ("scorer", "verifier")
        }
        structural_binding_ok = (
            structural_digests["scorer"] != structural_digests["verifier"]
            and all(
                hashlib.sha256(
                    judge_contract.structured_output_schema_text(role)
                    .encode("utf-8")
                ).hexdigest() == digest
                and judge_contract.contract_schema(role)[
                    "output_contract"][
                        "structured_output_schema_sha256"] == digest
                and judge_contract.contract_schema(role)[
                    "output_contract"][
                        "structured_output_policy_id"]
                == judge_contract.STRUCTURED_OUTPUT_POLICY_ID
                for role, digest in structural_digests.items())
            and final_contract_digests
            == pilot_registration.FINAL_RESPONSE_CONTRACT_SHA256
            == independently_hashed_final_contracts
            and runner.PILOT_V2_JUDGE_OUTPUT_POLICY.get(
                "final_response_contract_sha256")
            == final_contract_digests
        )
        invalid_structural_role_rejected = False
        try:
            judge_contract.structured_output_schema("reviewer")
        except judge_contract.JudgeResponseError:
            invalid_structural_role_rejected = True
        structured_override_rejected = True
        for override in (
            ["claude", "--json-schema", "{}"],
            ["claude", "--json-schema={}"],
        ):
            try:
                runner.refuse_v2_structured_output_override(override)
                structured_override_rejected = False
            except runner.InfraFailure:
                pass

        stream_node = json.dumps({
            "type": "node", "model": "opus", "effort": "high",
            "tool_calls": 0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

        def structured_stream(*result_events):
            return "\n".join((stream_node, *(
                json.dumps(event) for event in result_events)))

        valid_structured_event = {
            "type": "result", "subtype": "success",
            "session_id": "contract-pair", "result": scorer_json,
            "structured_output": json.loads(scorer_json),
        }
        malformed_streams = [
            structured_stream({
                key: value for key, value in valid_structured_event.items()
                if key != "structured_output"
            }),
            structured_stream({
                **valid_structured_event, "structured_output": []}),
            structured_stream({
                **valid_structured_event, "subtype": "error"}),
            structured_stream(valid_structured_event,
                              valid_structured_event),
        ]
        malformed_streams_rejected = all(
            runner._parse_judge_stream_tolerant(
                stream, require_structured_output=True)[4]
            for stream in malformed_streams
        )
        mismatched_structured = json.loads(scorer_json)
        mismatched_structured["summary"] = "different but individually valid"
        _parsed_pair, mismatch_defects = (
            runner._validate_v2_judge_response_pair(
                scorer_json, mismatched_structured, "scorer"))
        _parsed_missing, missing_pair_defects = (
            runner._validate_v2_judge_response_pair(
                scorer_json, None, "scorer"))
        ok &= check(
            "protocol-v2 judge schemas fail closed on malformed semantics",
            scorer_parsed["total"] == 8
            and verifier_parsed["supported_claims"] == 1
            and contract_rejects and semantic_defects_exact
            and judge_contract.contract_schema("scorer")[
                "output_contract"]["exact_object_keys"]["$.coverage"]
            == ["score", "rationale"]
            and judge_contract.contract_schema("verifier")[
                "output_contract"]["exact_object_keys"][
                    "$.claim_ledger[]"]
            == list(judge_contract.CLAIM_KEYS)
            and judge_contract.contract_schema("scorer")[
                "response_schema_version"]
            == judge_contract.RESPONSE_SCHEMA_VERSION,
            notes)
        ok &= check(
            "public structured schemas deterministically constrain exact keys",
            structural_shape_ok and structural_binding_ok
            and invalid_structural_role_rejected
            and structured_override_rejected,
            notes)
        ok &= check(
            "protocol-v2 dual judge outputs fail closed on envelope mismatch",
            malformed_streams_rejected
            and any("differs" in defect for defect in mismatch_defects)
            and any("missing" in defect for defect in missing_pair_defects),
            notes)

        environment_canary_name = "RPA_UNRELATED_SECRET_CANARY"
        environment_canary_before = os.environ.get(environment_canary_name)
        auth_canary_name = "CLAUDE_SESSION_INGRESS_TOKEN"
        auth_canary_before = os.environ.get(auth_canary_name)
        try:
            os.environ[environment_canary_name] = SECRET
            os.environ[auth_canary_name] = "synthetic-auth-canary"
            v2_environment = runner.backend_env(
                ws, runner.PILOT_V2_PROTOCOL_VERSION)
        finally:
            if environment_canary_before is None:
                os.environ.pop(environment_canary_name, None)
            else:
                os.environ[environment_canary_name] = environment_canary_before
            if auth_canary_before is None:
                os.environ.pop(auth_canary_name, None)
            else:
                os.environ[auth_canary_name] = auth_canary_before
        ok &= check(
            "protocol-v2 child environment excludes unrelated secret canaries",
            environment_canary_name not in v2_environment
            and SECRET not in v2_environment.values()
            and v2_environment.get(auth_canary_name)
            == "synthetic-auth-canary"
            and v2_environment.get("RPA_ENVIRONMENT_POLICY")
            == runner.PILOT_V2_ENVIRONMENT_POLICY_ID
            and v2_environment.get("CLAUDE_CONFIG_DIR") == str(ws)
            and v2_environment.get("TMPDIR") == "/tmp",
            notes)

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

        class MonotonicOnlyClock:
            monotonic = staticmethod(time.monotonic)
            sleep = staticmethod(time.sleep)

            @staticmethod
            def time():
                raise AssertionError("run timing consulted the wall clock")

        runner_time = runner.time
        runner.time = MonotonicOnlyClock
        try:
            monotonic_record, _, _, _ = run_case(
                ws, "normal", label="monotonic-clock")
            monotonic_ok = (
                monotonic_record.get("status") == "completed"
                and monotonic_record.get("wall_seconds", -1) >= 0)
        except AssertionError:
            monotonic_ok = False
        finally:
            runner.time = runner_time
        ok &= check(
            "run deadline and latency telemetry use only monotonic time",
            monotonic_ok, notes)

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

        strict_accounting = True
        for accounting_mode in (
                "bad-accounting-negative", "bad-accounting-fractional",
                "bad-accounting-typed", "bad-accounting-missing",
                "bad-accounting-zero"):
            bad_accounting, _, _, _ = run_case(ws, accounting_mode)
            accounting_failure = bad_accounting.get("failure", "")
            strict_accounting &= (
                bad_accounting.get("status") == "infra_failure"
                and ("nonnegative integer" in accounting_failure
                     or "usage must be an object" in accounting_failure
                     or "missing mandatory" in accounting_failure
                     or "positive model-token total" in accounting_failure))
        ok &= check(
            "backend accounting requires typed nonnegative integers",
            strict_accounting, notes)

        bad_assistant, _, _, _ = run_case(ws, "bad-assistant-message")
        ok &= check(
            "malformed assistant envelopes cannot hide before valid nodes",
            bad_assistant.get("status") == "infra_failure"
            and "assistant event message" in bad_assistant.get(
                "failure", ""),
            notes)

        abort_bad_accounting, _, _, _ = run_case(
            ws, "abort-bad-accounting", use_retries=True,
            protocol_v2=True)
        ok &= check(
            "invalid accounting on observed abort blocks without retry",
            abort_bad_accounting.get("status") == "infra_failure"
            and abort_bad_accounting.get("blocking") is True
            and abort_bad_accounting.get("attempt") == 1
            and "invalid accounting" in abort_bad_accounting.get(
                "failure", ""),
            notes)

        abort_bad_assistant, _, _, _ = run_case(
            ws, "abort-bad-assistant-message", use_retries=True,
            protocol_v2=True)
        abort_malformed_stream, _, _, _ = run_case(
            ws, "abort-malformed-stream", use_retries=True,
            protocol_v2=True)
        ok &= check(
            "partial abort accounting rejects malformed stream evidence",
            all(
                record.get("status") == "infra_failure"
                and record.get("blocking") is True
                and record.get("attempt") == 1
                and "invalid accounting" in record.get("failure", "")
                for record in (
                    abort_bad_assistant, abort_malformed_stream)),
            notes)

        judge_bad_accounting_stream = "\n".join((
            json.dumps({"type": "system", "session_id": "bad-acct"}),
            json.dumps({
                "type": "node", "model": "opus", "effort": "high",
                "tool_calls": True,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }),
            json.dumps({
                "type": "result", "session_id": "bad-acct",
                "result": "{}",
            }),
        ))
        (_sid, _nodes, _response, _structured,
         judge_accounting_defects) = runner._parse_judge_stream_tolerant(
             judge_bad_accounting_stream)
        judge_bad_assistant_stream = "\n".join((
            json.dumps({"type": "system", "session_id": "bad-msg"}),
            json.dumps({
                "type": "assistant", "session_id": "bad-msg",
                "message": None,
            }),
            json.dumps({
                "type": "node", "model": "opus", "effort": "high",
                "tool_calls": 0,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }),
            json.dumps({
                "type": "result", "session_id": "bad-msg",
                "result": "{}",
            }),
        ))
        (_sid, _nodes, _response, _structured,
         judge_assistant_defects) = runner._parse_judge_stream_tolerant(
             judge_bad_assistant_stream)
        ok &= check(
            "judge accounting/envelope defects consume an invalid attempt",
            any("invalid accounting" in defect
                for defect in judge_accounting_defects)
            and any("assistant event message" in defect
                    for defect in judge_assistant_defects),
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

        record, _, _, _ = run_case(
            ws, "abort-wrong-model", use_retries=True, protocol_v2=True)
        ok &= check(
            "partial runtime drift blocks the observed abort without retry",
            record["status"] == "infra_failure"
            and record.get("blocking") is True
            and record.get("attempt") == 1
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

        config, _ = build_config(ws, "launch-no-child")
        config.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "max_infra_retries": runner.DEFAULT_MAX_INFRA_RETRIES,
        })
        config["arms"]["mock"]["forbid_subagents"] = True
        v2_lnc = runner.run_task_with_retries(
            config, "mock", task_lnc, repo, ws / "out-v2-lnc")[-1]
        ok &= check(
            "v2 ablation launch without child blocks at first observation",
            v2_lnc.get("status") == "infra_failure"
            and v2_lnc.get("blocking") is True
            and v2_lnc.get("attempt") == 1
            and v2_lnc.get("failure_kind") == "subagent_policy"
            and v2_lnc.get("telemetry_eligible") is False,
            notes)

        config, _ = build_config(ws, "abort-after-artifact")
        config.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "max_infra_retries": runner.DEFAULT_MAX_INFRA_RETRIES,
        })
        config["arms"]["mock"]["forbid_subagents"] = True
        combo = runner.run_task_with_retries(
            config, "mock", task_lnc, repo, ws / "out-v2-policy-abort")[-1]
        ok &= check(
            "v2 combined policy+abort uses registered policy precedence",
            combo.get("status") == "workflow_failure"
            and combo.get("failure_kind") == "subagent_policy"
            and combo.get("secondary_failure_kind") == "abort"
            and combo.get("artifact_gate") == "passed"
            and combo.get("telemetry_eligible") is True,
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

        runtime_cfg_path = ws / "config-runtime-pins.json"
        runtime_cfg, _ = build_config(ws, "normal")
        runtime_cfg.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "max_infra_retries": runner.DEFAULT_MAX_INFRA_RETRIES,
            "nonstandard_config": False,
            "operator_image_sha256": "sha256:" + "a" * 64,
            "artifact_parser": "pyyaml",
            "artifact_parser_version": "6.0.2",
            "judge_live_probe_receipt_sha256":
                SYNTHETIC_LIVE_PROBE_RECEIPT_SHA256,
            "judge_live_probe_execution_sha256":
                SYNTHETIC_LIVE_PROBE_EXECUTION_SHA256,
        })
        runtime_cfg_path.write_text(
            json.dumps(runtime_cfg), encoding="utf-8")
        runtime_shape_ok = bool(runner.load_config(runtime_cfg_path))
        for field, bad_value in (
                ("operator_image_sha256", "a" * 64),
                ("artifact_parser", "PyYAML"),
                ("artifact_parser_version", "6.0")):
            malformed = json.loads(json.dumps(runtime_cfg))
            malformed[field] = bad_value
            runtime_cfg_path.write_text(
                json.dumps(malformed), encoding="utf-8")
            try:
                runner.load_config(runtime_cfg_path)
            except runner.InfraFailure as exc:
                runtime_shape_ok &= field in str(exc)
            else:
                runtime_shape_ok = False
        missing = json.loads(json.dumps(runtime_cfg))
        missing.pop("operator_image_sha256")
        runtime_cfg_path.write_text(json.dumps(missing), encoding="utf-8")
        try:
            runner.load_config(runtime_cfg_path)
        except runner.InfraFailure as exc:
            runtime_shape_ok &= "operator_image_sha256" in str(exc)
        else:
            runtime_shape_ok = False
        ok &= check(
            "standard v2 config requires strict operator runtime pin shapes",
            runtime_shape_ok, notes)

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

        bg_cfg, _ = build_config(ws, "background-child-success")
        bg_marker = ws / "background-child-survived"
        bg_cfg["backend_cmd"].extend([
            "--child-write-file", str(bg_marker)])
        bg_repo, bg_sha = make_git_repo(ws, "background-child")
        bg_task = write_task(ws, "background-child", bg_sha)
        bg_record = runner.run_task(
            bg_cfg, "mock", bg_task, bg_repo, ws / "out-background-child")
        time.sleep(1.2)
        ok &= check(
            "successful run parent cannot leave a background tool child",
            bg_record.get("status") == "completed"
            and not bg_marker.exists(),
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

        abort_doc, abort_doc_out, _, _ = run_case(
            ws, "abort-after-artifact", label="abort-after-artifact-v2",
            protocol_v2=True)
        ok &= check(
            "protocol-v2 abort preserves and gates an already-written document",
            abort_doc.get("status") == "workflow_failure"
            and abort_doc.get("failure_kind") == "abort"
            and abort_doc.get("artifact_gate") == "passed"
            and isinstance(abort_doc.get("artifact_sha256"), str)
            and len(list(abort_doc_out.glob("run-*-anon.md"))) == 1
            and len(list(abort_doc_out.glob("run-*-raw.md"))) == 1,
            notes)

        timeout_doc, timeout_doc_out, _, _ = run_case(
            ws, "timeout-after-artifact",
            label="timeout-after-artifact-v2", timeout=2,
            protocol_v2=True)
        ok &= check(
            "protocol-v2 timeout preserves and gates an already-written document",
            timeout_doc.get("status") == "workflow_failure"
            and timeout_doc.get("failure_kind") == "timeout"
            and timeout_doc.get("artifact_gate") == "passed"
            and isinstance(timeout_doc.get("artifact_sha256"), str)
            and len(list(timeout_doc_out.glob("run-*-anon.md"))) == 1,
            notes)

        artifact_repo, artifact_sha = make_git_repo(
            ws, "artifact-outcome-judging")
        produced_doc_judging = True
        for label, mode, mode_timeout in (
                ("abort-doc-judged", "abort-after-artifact", 20),
                ("timeout-doc-judged", "timeout-after-artifact", 2)):
            fixture = make_v2_fixture(
                ws, label, artifact_repo, artifact_sha,
                run_mode=mode, timeout=mode_timeout)
            judge_out = fixture["root"] / "judges"
            scorer_rows = score_v2_fixture(fixture, "scorer", judge_out)
            verifier_rows = score_v2_fixture(fixture, "verifier", judge_out)
            summary = fixture["manifest"]["results"][0]
            produced_doc_judging &= (
                summary.get("status") == "workflow_failure"
                and summary.get("failure_kind")
                == ("abort" if "abort" in mode else "timeout")
                and summary.get("artifact_gate") == "passed"
                and len(fixture["docs"]) == 1
                and fixture["docs"][0].name.endswith("-anon.md")
                and len(scorer_rows) == len(verifier_rows) == 1
                and scorer_rows[0].get("doc") == verifier_rows[0].get("doc")
            )
        ok &= check(
            "timeout/abort documents reach both protocol-v2 judge roles",
            produced_doc_judging, notes)

        non_utf8, non_utf8_out, _, _ = run_case(
            ws, "bad-utf8-artifact", label="bad-utf8-artifact-v2",
            protocol_v2=True)
        non_utf8_raw = next(non_utf8_out.glob("run-*-raw.md"), None)
        non_utf8_diag = next(non_utf8_out.glob("run-*-diag.md"), None)
        ok &= check(
            "non-UTF-8 produced document is a gate failure with raw evidence",
            non_utf8.get("status") == "workflow_failure"
            and non_utf8.get("failure_kind") == "artifact_contract"
            and non_utf8.get("artifact_gate") == "failed"
            and any("cannot read document" in defect
                    for defect in non_utf8.get("artifact_defects", []))
            and non_utf8_raw is not None
            and b"\xff" in non_utf8_raw.read_bytes()
            and non_utf8_diag is not None
            and "\ufffd" in non_utf8_diag.read_text(encoding="utf-8"),
            notes)

        validator_cfg, _ = build_config(ws, "normal")
        validator_cfg.update({
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "max_judge_attempts": runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "max_infra_retries": runner.DEFAULT_MAX_INFRA_RETRIES,
        })
        validator_repo, validator_sha = make_git_repo(ws, "validator-crash")
        validator_task = write_task(ws, "validator-crash", validator_sha)
        original_validator = runner.artifact_validator.validate
        try:
            def crash_validator(*_args, **_kwargs):
                raise RuntimeError("synthetic validator crash")

            runner.artifact_validator.validate = crash_validator
            validator_crash = runner.run_task(
                validator_cfg, "mock", validator_task, validator_repo,
                ws / "out-validator-crash")
            runner.artifact_validator.validate = lambda *_args, **_kwargs: None
            validator_indeterminate = runner.run_task(
                validator_cfg, "mock", validator_task, validator_repo,
                ws / "out-validator-indeterminate")
        finally:
            runner.artifact_validator.validate = original_validator
        ok &= check(
            "validator crash or indeterminate output is infrastructure failure",
            validator_crash.get("status") == "infra_failure"
            and "validator crashed" in validator_crash.get("failure", "")
            and validator_indeterminate.get("status") == "infra_failure"
            and "indeterminate" in validator_indeterminate.get("failure", ""),
            notes)

        aborted_stop, _, _, _ = run_case(
            ws, "abort-after-stop", label="abort-after-stop-v2",
            protocol_v2=True)
        aborted_stops = aborted_stop.get("interventions_log", [])
        ok &= check(
            "partial result before abort is preserved as unanswered stop",
            aborted_stop.get("status") == "workflow_failure"
            and aborted_stop.get("failure_kind") == "abort"
            and len(aborted_stops) == 1
            and aborted_stops[0].get("answered") is False
            and "provide the research query" in aborted_stops[0].get(
                "response", "")
            and aborted_stops[0].get("classification") == "statement",
            notes)

        empty_doc, empty_doc_out, _, _ = run_case(
            ws, "empty-artifact", label="empty-artifact-v2",
            protocol_v2=True)
        ok &= check(
            "whitespace-only fresh Markdown is a no-document outcome",
            empty_doc.get("status") == "workflow_failure"
            and empty_doc.get("failure_kind") == "missing_document"
            and empty_doc.get("artifact_gate") == "not_evaluated"
            and empty_doc.get("empty_artifacts")
            and not list(empty_doc_out.glob("run-*-anon.md"))
            and not list(empty_doc_out.glob("run-*-diag.md")),
            notes)

        multiple_fixture = make_v2_fixture(
            ws, "multiple-artifacts", artifact_repo, artifact_sha,
            run_mode="multiple-artifacts", execute_run=False)
        try:
            runner.run_schedule(
                multiple_fixture["config"], multiple_fixture["schedule"],
                {"mock-repo": str(artifact_repo)},
                multiple_fixture["run_output"],
                [str(multiple_fixture["task"])],
            )
            multiple_blocked = False
        except runner.InfraFailure as exc:
            multiple_blocked = "terminally invalid" in str(exc)
        multiple_records = list(
            multiple_fixture["run_output"].glob("run-*.json"))
        multiple_record = (json.loads(multiple_records[0].read_text(
            encoding="utf-8")) if len(multiple_records) == 1 else {})
        ok &= check(
            "multiple nonempty documents terminally invalidate the round",
            multiple_blocked
            and multiple_record.get("status") == "infra_failure"
            and multiple_record.get("blocking") is True
            and len(multiple_record.get("produced_artifacts", [])) == 2
            and len(list(multiple_fixture["run_output"].glob(
                "run-*-extra-*.md"))) == 2
            and (multiple_fixture["run_output"]
                 / "schedule-entry-0-terminal-invalid.json").exists(),
            notes)

        wrong_run_material_ok = True
        for material_kind in ("directory-record", "dangling-raw"):
            fixture = make_v2_fixture(
                ws, f"wrong-run-{material_kind}", artifact_repo,
                artifact_sha, execute_run=False)
            fixture["run_output"].mkdir(parents=True, exist_ok=True)
            (fixture["run_output"] / ".run-schedule.lock").write_text(
                "", encoding="utf-8")
            if material_kind == "directory-record":
                wrong_path = fixture["run_output"] / "run-deadbeefcafe.json"
                wrong_path.mkdir()
            else:
                wrong_path = (
                    fixture["run_output"] / "run-deadbeefcafe-raw.md")
                wrong_path.symlink_to(
                    fixture["root"] / "missing-run-material")
            try:
                runner.run_schedule(
                    fixture["config"], fixture["schedule"],
                    {"mock-repo": str(artifact_repo)},
                    fixture["run_output"], [str(fixture["task"])])
                first_block = False
            except runner.InfraFailure as exc:
                first_block = "terminally invalid" in str(exc)
            marker = (fixture["run_output"]
                      / "schedule-entry-0-terminal-invalid.json")
            if wrong_path.is_dir() and not wrong_path.is_symlink():
                wrong_path.rmdir()
            else:
                wrong_path.unlink()
            try:
                runner.run_schedule(
                    fixture["config"], fixture["schedule"],
                    {"mock-repo": str(artifact_repo)},
                    fixture["run_output"], [str(fixture["task"])])
                resume_block = False
            except runner.InfraFailure as exc:
                resume_block = "terminally invalid" in str(exc)
            wrong_run_material_ok &= (
                first_block and resume_block and marker.is_file()
                and not list(fixture["run_output"].glob("run-*-anon.md")))
        ok &= check(
            "wrong-type run records/artifacts durably block before launch",
            wrong_run_material_ok, notes)

        fn_doc = ws / "notes.md"
        fn_doc.write_text(
            (HERE / "fixtures" / "artifact-valid.md").read_text(
                encoding="utf-8"), encoding="utf-8")
        fn_bad = runner.artifact_validator.validate(
            fn_doc, enforce_filename=True)
        fn_good_doc = ws / "2026-07-27-fixture-copy.md"
        fn_good_doc.write_text(fn_doc.read_text(encoding="utf-8"),
                               encoding="utf-8")
        fn_good = runner.artifact_validator.validate(
            fn_good_doc, enforce_filename=True)
        alias_doc = ws / "2026-07-27-alias-frontmatter.md"
        alias_text = fn_doc.read_text(encoding="utf-8").replace(
            "researcher: Fixture Researcher",
            "identity: &who Fixture Researcher\nresearcher: *who",
            1,
        ).replace("---\n", "--- \t\n", 2)
        alias_doc.write_text(alias_text, encoding="utf-8")
        alias_gate_defects = runner.artifact_validator.validate(
            alias_doc, enforce_filename=True)
        # With PyYAML, the legal anchor/alias must pass.  The documented
        # dependency-free fallback intentionally accepts only flat scalar
        # mappings and may reject this richer YAML; preflight must remain
        # host-agnostic while blinding remains mandatory in either mode.
        alias_gate_ok = (
            not alias_gate_defects
            if runner.artifact_validator.yaml is not None
            else any("indicator-bearing" in defect
                     for defect in alias_gate_defects))
        alias_anon = runner.anonymize(alias_text, "alias")
        alias_anon_doc = ws / "alias-frontmatter-anon.md"
        alias_anon_doc.write_text(alias_anon, encoding="utf-8")
        try:
            runner.assert_blind_scorable(alias_anon_doc)
            alias_blind_ok = True
        except runner.InfraFailure:
            alias_blind_ok = False
        ok &= check(
            "YAML aliases blind safely under full/strict-fallback parsing",
            alias_gate_ok and alias_blind_ok
            and "Fixture Researcher" not in alias_anon,
            notes)
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
        alias_literal_doc = ws / "2026-07-27-alias-literal.md"
        alias_literal_doc.write_text(
            alias_text.replace(
                "**Researcher**: Fixture Researcher",
                "**Researcher**: *who",
                1,
            ),
            encoding="utf-8",
        )
        alias_fallback_bad = va_noyaml.validate(alias_literal_doc)
        alias_full_bad = runner.artifact_validator.validate(
            alias_literal_doc)
        spaced_date_doc = ws / "2026-07-27-spaced-date.md"
        spaced_date_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "date: 2026-07-27T00:00:00Z",
                "date: 2026-07-27 00:00:00 +0200", 1).replace(
                "**Date**: 2026-07-27T00:00:00Z",
                "**Date**: 2026-07-27 00:00:00 +0200", 1),
            encoding="utf-8",
        )
        spaced_date_full_ok = not runner.artifact_validator.validate(
            spaced_date_doc)
        spaced_date_fallback_ok = not va_noyaml.validate(spaced_date_doc)
        scalar_cross_parser_ok = True
        for index, scalar in enumerate((
                "Fixture Researcher # comment",
                "Fixture Researcher: admin",
                "Fixture Researcher {x: y}",
                "Fixture\tResearcher",
                "2026-01-01")):
            scalar_doc = ws / f"2026-07-27-scalar-{index}.md"
            scalar_doc.write_text(
                fn_doc.read_text(encoding="utf-8").replace(
                    "researcher: Fixture Researcher",
                    f"researcher: {scalar}", 1).replace(
                    "**Researcher**: Fixture Researcher",
                    f"**Researcher**: {scalar}", 1),
                encoding="utf-8",
            )
            fallback_defects = va_noyaml.validate(scalar_doc)
            full_defects = runner.artifact_validator.validate(scalar_doc)
            scalar_cross_parser_ok &= (
                any(("non-plain value" in defect
                     or "start alphabetically" in defect
                     or "contains a tab" in defect)
                    for defect in fallback_defects)
                and (runner.artifact_validator.yaml is None
                     or bool(full_defects)))
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
        flowempty_doc = ws / "2026-07-26-flowempty.md"
        flowempty_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "tags: [research, fixture]",
                "tags: [research,,fixture]", 1),
            encoding="utf-8")
        flowempty_bad = runner.artifact_validator.validate(flowempty_doc)
        flowempty_fallback_bad = va_noyaml.validate(flowempty_doc)
        flowdate_doc = ws / "2026-07-26-flowdate.md"
        flowdate_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "tags: [research, fixture]",
                "tags: [2026-01-01]", 1),
            encoding="utf-8")
        flowdate_bad = runner.artifact_validator.validate(flowdate_doc)
        flowdate_fallback_bad = va_noyaml.validate(flowdate_doc)
        oldname_doc = ws / "2025-01-01-old-topic.md"
        oldname_doc.write_text(fn_doc.read_text(encoding="utf-8"),
                               encoding="utf-8")
        oldname_bad = runner.artifact_validator.validate(
            oldname_doc, enforce_filename=True)
        quotejunk_doc = ws / "2026-07-27-quotejunk.md"
        quotejunk_doc.write_text(
            fn_doc.read_text(encoding="utf-8").replace(
                "researcher: Fixture Researcher",
                'researcher: "Fixture" Researcher"', 1),
            encoding="utf-8")
        quotejunk_bad = runner.artifact_validator.validate(quotejunk_doc)
        quotejunk_fallback_bad = va_noyaml.validate(quotejunk_doc)
        fix_text = fn_doc.read_text(encoding="utf-8")
        fm_close = fix_text.index("---\n", fix_text.index("---\n") + 4)
        commented_doc = ws / "2026-07-27-commented.md"
        commented_doc.write_text(
            fix_text[:fm_close + 4] + "<!--\n"
            + fix_text[fm_close + 4:] + "\n-->\n",
            encoding="utf-8")
        commented_bad = runner.artifact_validator.validate(commented_doc)
        htmlfill_doc = ws / "2026-07-27-htmlfill.md"
        htmlfill_doc.write_text(
            fix_text.replace(
                "Minimal valid document proving the validator accepts "
                "the contract shape.",
                "<!-- filler -->", 1),
            encoding="utf-8")
        htmlfill_bad = runner.artifact_validator.validate(htmlfill_doc)
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
            and any("indicator-bearing" in e
                    for e in alias_fallback_bad)
            and (runner.artifact_validator.yaml is None or alias_full_bad)
            and spaced_date_full_ok and spaced_date_fallback_ok
            and scalar_cross_parser_ok
            and any("researcher" in e and "must be a string" in e
                    for e in boolid_bad)
            and any("researcher" in e and "must be a string" in e
                    for e in boolid_fallback_bad)
            and any("tags" in e for e in flowmap_bad)
            and any("tags" in e for e in flowmap_fallback_bad)
            and any("tags" in e for e in flowbool_bad)
            and any("tags" in e for e in flowbool_fallback_bad)
            and flowempty_bad
            and any("empty item" in e for e in flowempty_fallback_bad)
            and flowdate_bad
            and any("start alphabetically" in e
                    for e in flowdate_fallback_bad)
            and any("does not match the metadata timestamp" in e
                    for e in oldname_bad)
            and quotejunk_bad
            and any("internal quote" in e
                    for e in quotejunk_fallback_bad)
            and any("missing required heading" in e
                    for e in commented_bad)
            and any("no substantive content" in e
                    for e in htmlfill_bad)
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
        branch_lines = [line for line in meta_out.stdout.splitlines()
                        if line.startswith("Current Branch Name:")]
        dt_lines = [line for line in meta_out.stdout.splitlines()
                    if line.startswith("Current Date/Time (TZ):")]
        fn_lines = [line for line in meta_out.stdout.splitlines()
                    if line.startswith("Timestamp For Filename:")]
        # Both formatted values must come from ONE clock reading — two
        # `date` calls can straddle midnight and split the metadata
        # timestamp and filename date across days.
        single_clock = (
            meta_script.read_text(encoding="utf-8").count("$(date") == 1
            and bool(dt_lines) and bool(fn_lines)
            and dt_lines[0].split(": ", 1)[1][:19]
            .replace(" ", "_").replace(":", "-")
            == fn_lines[0].split(": ", 1)[1])
        ok &= check(
            "metadata script supplies branch identity in detached worktrees",
            meta_out.returncode == 0 and bool(branch_lines)
            and "detached@" in branch_lines[0]
            and single_clock,
            notes)

        # The wrapper's parse-time @-imports must cover BOTH install
        # layouts: plugin (${CLAUDE_PLUGIN_ROOT} set) and Quick Install
        # (files copied under ~/.claude, variable unset) — with only the
        # plugin form, non-plugin invocations lose the embedded kernel
        # and artifact contract entirely.
        wrapper_text = (HERE.parents[3] / "commands"
                        / "research_codebase.md").read_text(encoding="utf-8")
        ok &= check(
            "command wrapper embeds kernel + contract in both install layouts",
            all(ref in wrapper_text for ref in (
                "@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/SKILL.md",
                "@~/.claude/skills/research-codebase/SKILL.md",
                "@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references"
                "/artifact-contract.md",
                "@~/.claude/skills/research-codebase/references"
                "/artifact-contract.md")),
            notes)

        # Each v2 adapter must IMPORT its contract at parse time
        # (@${CLAUDE_PLUGIN_ROOT}/...): the adapters have no Bash tool,
        # so a plugin-root path left as prose is unreadable to them in a
        # plugin-only install and all six would dead-end at the honest
        # failure branch instead of researching.
        adapter_dir = HERE.parents[3] / "agents"
        adapter_files = sorted(adapter_dir.glob("research-v2-*.md"))
        adapters_import = bool(adapter_files) and len(adapter_files) == 6
        for adapter in adapter_files:
            a_text = adapter.read_text(encoding="utf-8")
            contract = adapter.name.replace(
                "research-v2-", "research-", 1)
            adapters_import &= (
                "@${CLAUDE_PLUGIN_ROOT}/skills/research-codebase/references"
                f"/agent-contracts/{contract}" in a_text)
        ok &= check(
            "v2 adapters import their agent contracts at parse time",
            adapters_import,
            notes)

        # macOS amendment: the wrapper must carry the registered
        # interface and deny-default profile, and the operator check
        # must refuse to run anywhere but a Mac — the actual sandbox
        # behavior is validated on the operator host (sandbox-exec does
        # not exist here).
        mac_wrap = HERE / "macos_sandbox.py"
        mac_check_path = HERE / "macos_sandbox_check.py"
        mac_help = subprocess.run(
            [sys.executable, str(mac_wrap), "--help"],
            capture_output=True, text=True)
        wrap_text = mac_wrap.read_text(encoding="utf-8")
        notmac = subprocess.run(
            [sys.executable, str(mac_check_path), "--repo", "x",
             "--newer", "x"],
            capture_output=True, text=True)
        # The shared pinned-store builder must be idempotent across
        # continuations that re-enter the same worktree (both wrappers
        # re-invoke it per session).
        import importlib.util as _ilu_ns
        _spec_ns = _ilu_ns.spec_from_file_location(
            "ns_sb_probe", HERE / "ns_sandbox.py")
        ns_sb = _ilu_ns.module_from_spec(_spec_ns)
        _spec_ns.loader.exec_module(ns_sb)
        reuse_repo, reuse_sha = make_git_repo(ws, "pinned-reuse")
        reuse_wt = runner.make_worktree(reuse_repo, reuse_sha,
                                        ws / "pinned-reuse-out",
                                        name="mock-repo")
        reuse_common = ns_sb.git_common_dir(str(reuse_wt))
        p1, h1 = ns_sb.build_pinned_gitdir(str(reuse_wt), reuse_common)
        p2, h2 = ns_sb.build_pinned_gitdir(str(reuse_wt), reuse_common)
        rebuild_ok = (p1 == p2 and h1 == h2 == reuse_sha)
        runner.remove_worktree(reuse_repo, reuse_wt)
        # The step-5 operator driver mechanically restates the plan's
        # freeze record: its constants must match the plan text, and a
        # drifted operator config must be refused before any run.
        _spec_s5 = _ilu.spec_from_file_location(
            "step5_probe", HERE / "step5_operator.py")
        step5 = _ilu.module_from_spec(_spec_s5)
        _spec_s5.loader.exec_module(step5)
        plan_text = (HERE.parents[3] / "thoughts" / "shared" / "plans"
                     / "2026-07-26-thinking-model-modernization-pilot.md"
                     ).read_text(encoding="utf-8")
        seal_registration_recorded = (
            step5.REGISTERED_SEAL_PACKAGE_SHA256
            == step5.PENDING_SEAL_PACKAGE_SHA256
            or step5.REGISTERED_SEAL_PACKAGE_SHA256 in plan_text)
        constants_in_plan = (
            step5.FROZEN_CANDIDATE_SHA in plan_text
            and seal_registration_recorded
            and all(h in plan_text
                    for h in step5.REGISTERED_INSTALL_SHA256.values())
            and step5.REGISTERED_BACKEND_VERSION in plan_text
            and step5.REGISTERED_JUDGE_OUTPUT_POLICY["id"] in plan_text
            and all(
                digest in plan_text
                for digest in (
                    step5.REGISTERED_STRUCTURED_OUTPUT_SCHEMA_SHA256
                ).values())
            and all(
                digest in plan_text
                for digest in (
                    step5.REGISTERED_FINAL_RESPONSE_CONTRACT_SHA256
                ).values()))
        good_cfg = {
            "protocol_version": step5.REGISTERED_PROTOCOL_VERSION,
            "nonstandard_config": False,
            "operator_image_sha256":
                step5.REGISTERED_OPERATOR_IMAGE_SHA256,
            "artifact_parser": step5.REGISTERED_ARTIFACT_PARSER,
            "artifact_parser_version":
                step5.REGISTERED_ARTIFACT_PARSER_VERSION,
            "arms": {
                arm: {
                    "installation_dir": f"/x/{arm}",
                    "sha256": sha,
                    "model": step5.REGISTERED_MODEL,
                    "effort": step5.REGISTERED_EFFORT,
                    "entrypoint": step5.REGISTERED_ENTRYPOINT,
                    **({"forbid_subagents": True,
                        "schedule_tasks": list(
                            step5.REGISTERED_ABLATION_TASKS)}
                       if arm == "ablation" else {}),
                }
                for arm, sha in step5.REGISTERED_INSTALL_SHA256.items()
            },
            "sandbox_cmd": ["python3",
                            str(HERE / step5.PLATFORM_WRAPPER.get(
                                sys.platform, step5.DEFAULT_WRAPPER)),
                            "--confine-to", "{workdir}", "--profile",
                            "{profile}", "--"],
            "backend_cmd": list(step5.REGISTERED_BACKEND_CMD),
            "backend_version_cmd": list(
                step5.REGISTERED_BACKEND_VERSION_CMD),
            "judge_backend_cmd": list(
                step5.REGISTERED_JUDGE_BACKEND_CMD),
            "workflow_abort_exit_codes": list(
                step5.REGISTERED_ABORT_EXIT_CODES),
            "seal_package_sha256": step5.REGISTERED_SEAL_PACKAGE_SHA256,
            "judge_live_probe_receipt_sha256":
                pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            "judge_live_probe_execution_sha256":
                pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
            "backend_version": step5.REGISTERED_BACKEND_VERSION,
            "timeout_seconds": step5.REGISTERED_TIMEOUT_SECONDS,
            "max_infra_retries": step5.REGISTERED_MAX_INFRA_RETRIES,
            "max_judge_attempts": step5.REGISTERED_MAX_JUDGE_ATTEMPTS,
            "judge_model": step5.REGISTERED_JUDGE_MODEL,
            "judge_effort": step5.REGISTERED_JUDGE_EFFORT,
            "drift_fetch_cmd": list(step5.REGISTERED_DRIFT_FETCH_CMD),
        }
        pin_probe_round = (
            ws / "registered-pin-probe" / judge_live_probe.ROUND_NAMESPACE)
        (pin_probe_round / judge_live_probe.PACKAGE_NAMESPACE).mkdir(
            parents=True)
        good_cfg["seal_manifest"] = str(
            pin_probe_round / judge_live_probe.PACKAGE_NAMESPACE
            / seal_package.MANIFEST_NAME)
        saved_registration_for_probe_gate = (
            pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
        )
        pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_RECEIPT_SHA256)
        pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_EXECUTION_SHA256)
        pending_probe_cfg = json.loads(json.dumps(good_cfg))
        pending_probe_cfg["judge_live_probe_receipt_sha256"] = (
            pilot_registration.PENDING_LIVE_PROBE_RECEIPT_SHA256)
        pending_probe_cfg["judge_live_probe_execution_sha256"] = (
            pilot_registration.PENDING_LIVE_PROBE_EXECUTION_SHA256)
        try:
            pending_registration_authorizes_probe = not (
                step5.live_probe_config_problems(pending_probe_cfg))
        finally:
            (pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
             pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256) = (
                saved_registration_for_probe_gate)
        exact_runtime_observation = {
            "operator_image_sha256":
                step5.REGISTERED_OPERATOR_IMAGE_SHA256,
            "artifact_parser": step5.REGISTERED_ARTIFACT_PARSER,
            "artifact_parser_version":
                step5.REGISTERED_ARTIFACT_PARSER_VERSION,
            "artifact_parser_distribution_version":
                step5.REGISTERED_ARTIFACT_PARSER_VERSION,
        }
        original_runtime_observation = step5.operator_runtime_observation
        step5.operator_runtime_observation = (
            lambda: dict(exact_runtime_observation))
        clean_problems, clean_warnings = step5.validate_config(good_cfg)
        pending_registration = (
            step5.REGISTERED_SEAL_PACKAGE_SHA256
            == step5.PENDING_SEAL_PACKAGE_SHA256)

        def pending_registration_problem(problem):
            return ("all-zero placeholder" in problem
                    or "registration is pending" in problem)

        def non_pending_problems(config):
            return [
                problem for problem in step5.validate_config(config)[0]
                if not pending_registration_problem(problem)
            ]

        registration_state_ok = (
            not non_pending_problems(good_cfg)
            and bool(clean_problems) == pending_registration
            and (not clean_problems
                 or all(pending_registration_problem(problem)
                        for problem in clean_problems)))
        shared_registration_consistent = (
            runner.PILOT_V2_PROTOCOL_VERSION
            == seal_package.PROTOCOL_VERSION
            == step5.REGISTERED_PROTOCOL_VERSION
            == pilot_registration.PROTOCOL_VERSION
            and runner.DEFAULT_MAX_INFRA_RETRIES
            == step5.REGISTERED_MAX_INFRA_RETRIES
            == pilot_registration.MAX_INFRA_RETRIES
            and runner.PILOT_V2_MAX_JUDGE_ATTEMPTS
            == seal_package.MAX_JUDGE_ATTEMPTS
            == step5.REGISTERED_MAX_JUDGE_ATTEMPTS
            == pilot_registration.MAX_JUDGE_ATTEMPTS
            and runner.PILOT_V2_JUDGE_OUTPUT_POLICY
            is seal_package.JUDGE_OUTPUT_POLICY
            is step5.REGISTERED_JUDGE_OUTPUT_POLICY
            is pilot_registration.JUDGE_OUTPUT_POLICY
            and step5.REGISTERED_FINAL_RESPONSE_CONTRACT_SHA256
            is pilot_registration.FINAL_RESPONSE_CONTRACT_SHA256
            and step5.REGISTERED_INSTALL_SHA256
            is pilot_registration.INSTALL_SHA256)
        fake_python_dir = ws / "fake-python-interpreter"
        fake_python_dir.mkdir()
        fake_python = fake_python_dir / "python3"
        fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_python.chmod(0o755)
        fake_sandbox_cmd = list(good_cfg["sandbox_cmd"])
        fake_sandbox_cmd[0] = str(fake_python)
        fake_python_rejected = bool(
            pilot_registration.sandbox_registration_problem(
                fake_sandbox_cmd))

        saved_shared_seal = (
            pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256)
        direct_registered_seal = "5" * 64
        pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256 = (
            direct_registered_seal)
        direct_drift_cfg = json.loads(json.dumps(good_cfg))
        direct_drift_cfg["seal_package_sha256"] = direct_registered_seal
        direct_drift_cfg["arms"]["candidate"]["sha256"] = "6" * 64
        direct_drift_out = ws / "direct-registration-drift-output"
        direct_failures = []
        try:
            for operation in (
                    lambda: runner.make_schedule(
                        direct_drift_cfg, [str(ws / "must-not-read.md")],
                        3, runner.PILOT_V2_SCHEDULE_SEED),
                    lambda: runner.run_schedule(
                        direct_drift_cfg, ws / "must-not-read-schedule.json",
                        {}, direct_drift_out, [str(ws / "must-not-read.md")]),
                    lambda: runner.score(
                        direct_drift_cfg, [], ws / "must-not-read-prompt.md",
                        direct_drift_out,
                        scoring_seed=runner.PILOT_V2_SCORER_SEED),
            ):
                try:
                    operation()
                    direct_failures.append(False)
                except runner.InfraFailure as exc:
                    direct_failures.append(
                        "standard protocol-v2 runtime" in str(exc))
        finally:
            pilot_registration.REGISTERED_SEAL_PACKAGE_SHA256 = (
                saved_shared_seal)
        direct_drift_prelaunch = (
            all(direct_failures) and not direct_drift_out.exists())
        drifted_probe_config = json.loads(json.dumps(good_cfg))
        drifted_probe_config["judge_model"] = "unregistered-judge"
        original_live_probe_spawn = runner.spawn_judge_session_capped
        pin_drift_launches = []

        def forbidden_pin_drift_launch(*args, **kwargs):
            pin_drift_launches.append((args, kwargs))
            raise AssertionError("drifted live probe config launched a model")

        runner.spawn_judge_session_capped = forbidden_pin_drift_launch
        try:
            try:
                judge_live_probe.run_probe(drifted_probe_config)
                pin_drift_rejected = False
            except judge_live_probe.ProbeError:
                pin_drift_rejected = True
        finally:
            runner.spawn_judge_session_capped = original_live_probe_spawn
        ok &= check(
            "live judge probe rejects registered-pin drift before model spawn",
            pending_registration_authorizes_probe
            and pin_drift_rejected and not pin_drift_launches
            and not os.path.lexists(
                pin_probe_round / judge_live_probe.OUTPUT_NAMESPACE),
            notes)
        drifts = []
        for mutate in (
            lambda c: c.update(protocol_version=1),
            lambda c: c.update(operator_image_sha256="sha256:" + "0" * 64),
            lambda c: c.update(artifact_parser="other-parser"),
            lambda c: c.update(artifact_parser_version="6.0.3"),
            lambda c: c["arms"]["candidate"].update(model="opus"),
            lambda c: c["arms"]["baseline"].update(effort="medium"),
            lambda c: c["arms"]["candidate"].update(sha256="0" * 64),
            lambda c: c["arms"]["ablation"].pop("forbid_subagents"),
            lambda c: c["arms"]["ablation"].update(
                schedule_tasks=list(reversed(
                    step5.REGISTERED_ABLATION_TASKS))),
            lambda c: c.update(seal_package_sha256="f" * 64),
            lambda c: c.update(judge_live_probe_receipt_sha256="f" * 64),
            lambda c: c.update(judge_live_probe_execution_sha256="f" * 64),
            lambda c: c.update(backend_version="9.9.9"),
            lambda c: c.update(nonstandard_config=True),
            lambda c: c.pop("sandbox_cmd"),
            lambda c: c.update(sandbox_cmd=["/usr/bin/env"]),
            # A lookalike that mentions the wrapper's filename but
            # never runs it — the substring test this replaced.
            lambda c: c.update(sandbox_cmd=[
                "env", "TAG=ns_sandbox.py", "W={workdir}",
                "P={profile}", "--"]),
            # A `python`-prefixed shim that is not python3 at all.
            lambda c: c.update(sandbox_cmd=[
                "python-evil", c["sandbox_cmd"][1], "--confine-to",
                "{workdir}", "--profile", "{profile}", "--"]),
            lambda c: c.update(backend_cmd=[
                "claude", "--model", "claude-opus-5", "--effort",
                "{effort}", "--plugin-dir", "{installation}"]),
            lambda c: c.update(backend_version_cmd=["claude", "-v"]),
            lambda c: c.update(workflow_abort_exit_codes=[2]),
            lambda c: c.update(max_judge_attempts=2),
            lambda c: c.update(judge_backend_cmd=[
                "claude", "--model", "opus", "--effort", "{effort}"]),
            lambda c: c.update(judge_model="claude-opus-4"),
            lambda c: c.update(judge_effort="medium"),
            lambda c: c.update(drift_fetch_cmd=["cp", "{url}", "{dest}"]),
        ):
            cfg = json.loads(json.dumps(good_cfg))
            mutate(cfg)
            drifts.append(bool(non_pending_problems(cfg)))
        base_runtime_digest = runner.config_digest(good_cfg)
        runtime_digest_ok = all(
            runner.config_digest({**good_cfg, field: value})
            != base_runtime_digest
            for field, value in (
                ("operator_image_sha256", "sha256:" + "0" * 64),
                ("artifact_parser", "other-parser"),
                ("artifact_parser_version", "6.0.3"),
                ("judge_live_probe_receipt_sha256", "3" * 64),
                ("judge_live_probe_execution_sha256", "4" * 64),
            )
        )

        def runtime_gate_stops_before_subprocess(observation):
            calls = []
            original_run = step5.subprocess.run
            step5.operator_runtime_observation = lambda: dict(observation)

            def forbidden_backend_probe(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("backend probe launched before runtime gate")

            step5.subprocess.run = forbidden_backend_probe
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    try:
                        step5.phase_gates(SimpleNamespace(), good_cfg)
                    except SystemExit:
                        stopped = True
                    else:
                        stopped = False
            finally:
                step5.subprocess.run = original_run
            return stopped and not calls

        missing_image_observation = dict(exact_runtime_observation)
        missing_image_observation["operator_image_sha256"] = None
        wrong_parser_observation = dict(exact_runtime_observation)
        wrong_parser_observation["artifact_parser_version"] = "6.0.3"
        wrong_parser_observation[
            "artifact_parser_distribution_version"] = "6.0.3"
        operator_runtime_gate_ok = (
            runtime_gate_stops_before_subprocess(missing_image_observation)
            and runtime_gate_stops_before_subprocess(wrong_parser_observation)
        )
        step5.operator_runtime_observation = (
            lambda: dict(exact_runtime_observation))
        ok &= check(
            "operator image/parser pins bind config and gate before backend",
            runtime_digest_ok and operator_runtime_gate_ok,
            notes)
        leaky_fetch_cfg = json.loads(json.dumps(good_cfg))
        leaky_fetch_cfg["drift_fetch_cmd"] = [
            "curl", "-fsSL", "{url}", "-o", "{dest}",
        ]
        ok &= check(
            "operator rejects source-fetch configs that expose URL in argv",
            any("drift_fetch_cmd differs" in problem
                for problem in non_pending_problems(leaky_fetch_cfg)),
            notes)
        # Scored phases require a durable gate receipt for THIS host
        # and config: `--phases schedule,runs` cannot bypass the
        # mandatory gates (on macOS, the host-side sandbox check), and
        # a hand-written receipt cannot stand in for gates that never
        # ran — the recorded gate list and every gate's transcript
        # (present, digest-matching, PASSING) are part of the proof.
        receipt_dir = ws / "step5-receipt"
        receipt_dir.mkdir(exist_ok=True)
        missing_receipt = step5.gate_receipt_problem(receipt_dir,
                                                     good_cfg)
        required_gates = ["preflight"]
        if sys.platform == "darwin":
            required_gates.append("macos_sandbox_check")
        artifacts = {}
        for gate_name in required_gates:
            transcript = receipt_dir / f"{gate_name}.txt"
            transcript.write_text(
                step5.GATE_TRANSCRIPT_MARKERS[gate_name] + " passed\n",
                encoding="utf-8")
            artifacts[gate_name] = {
                "path": str(transcript),
                "sha256": step5.file_digest(transcript),
            }

        def write_receipt(**overrides):
            body = {"identity": step5.gate_identity(good_cfg),
                    "gates": list(step5.REQUIRED_GATES),
                    "operator_runtime_observed":
                        dict(exact_runtime_observation),
                    "artifacts": json.loads(json.dumps(artifacts))}
            body.update(overrides)
            step5.gate_receipt_path(receipt_dir).write_text(
                json.dumps(body), encoding="utf-8")

        write_receipt()
        fresh_receipt = step5.gate_receipt_problem(receipt_dir,
                                                   good_cfg)
        other_cfg = json.loads(json.dumps(good_cfg))
        other_cfg["timeout_seconds"] = 1800
        stale_receipt = step5.gate_receipt_problem(receipt_dir,
                                                   other_cfg)
        write_receipt(gates=["preflight"])
        partial_gates = step5.gate_receipt_problem(receipt_dir, good_cfg)
        write_receipt(artifacts={})
        no_transcripts = step5.gate_receipt_problem(receipt_dir, good_cfg)
        write_receipt()
        (receipt_dir / "preflight.txt").write_text(
            "preflight FAILED: 1/157\n", encoding="utf-8")
        tampered = step5.gate_receipt_problem(receipt_dir, good_cfg)
        forged = json.loads(json.dumps(artifacts))
        forged["preflight"]["sha256"] = step5.file_digest(
            receipt_dir / "preflight.txt")
        write_receipt(artifacts=forged)
        not_passing = step5.gate_receipt_problem(receipt_dir, good_cfg)
        real_task = ws / "step5-real-preflight-task.md"
        real_task.write_text(
            "---\ntarget-repo: rpa\n"
            f"target-sha: {step5.FROZEN_CANDIDATE_SHA}\n---\n\n"
            "## Task prompt\n\nSynthetic real-backend probe.\n",
            encoding="utf-8")
        original_verified_seal = step5.verified_seal
        fake_seal_files = {
            name: hashlib.sha256(
                f"sealed task {index}".encode("utf-8")).hexdigest()
            for index, name in enumerate(step5.REGISTERED_HOLDOUT_TASKS)
        }
        step5.verified_seal = lambda _config: (
            ws / "synthetic-seal-manifest.json", {}, fake_seal_files)
        missing_real_receipt = step5.real_preflight_receipt_problem(
            receipt_dir, good_cfg, real_task)
        real_root = step5.real_preflight_root(receipt_dir)
        dev_cfg = json.loads(json.dumps(good_cfg))
        dev_cfg["nonstandard_config"] = True
        real_root.mkdir()
        dev_cfg_path = real_root / "dev-config.json"
        dev_cfg_path.write_text(
            json.dumps(dev_cfg), encoding="utf-8")
        real_task_digest = step5.file_digest(real_task)
        real_record_paths = {}
        for index, arm in enumerate(sorted(
                step5.REGISTERED_INSTALL_SHA256), start=1):
            arm_root = real_root / arm
            arm_root.mkdir()
            record_path = arm_root / f"run-{index:012x}.json"
            real_nodes = [{
                "model": step5.REGISTERED_MODEL,
                "effort": step5.REGISTERED_EFFORT,
                "input_tokens": 10,
                "output_tokens": 5,
                "tool_calls": 1,
                "subagent": False,
                "subagent_launches": 0,
            }]
            record_path.write_text(json.dumps({
                "run_id": f"{index:012x}",
                "arm": arm,
                "task": str(real_task.resolve()),
                "attempt": 1,
                "config_digest": runner.config_digest(dev_cfg),
                "task_sha256": real_task_digest,
                "protocol_version": step5.REGISTERED_PROTOCOL_VERSION,
                "environment_policy_id": (
                    step5.REGISTERED_ENVIRONMENT_POLICY_ID),
                "runtime_pins": runner.protocol_v2_runtime_pins(dev_cfg),
                "status": "completed",
                "failure_kind": None,
                "artifact_gate": "passed",
                "backend_version": step5.REGISTERED_BACKEND_VERSION,
                "installation_sha256": (
                    step5.REGISTERED_INSTALL_SHA256[arm]),
                "registered_model": step5.REGISTERED_MODEL,
                "effort": step5.REGISTERED_EFFORT,
                "entrypoint": step5.REGISTERED_ENTRYPOINT,
                "target_sha": step5.FROZEN_CANDIDATE_SHA,
                "telemetry_eligible": True,
                "telemetry_exclusion_reason": None,
                "nodes": real_nodes,
                "accounting": runner.account(real_nodes),
                "wall_seconds": 1.0,
                "effort_capture": "per_node",
            }), encoding="utf-8")
            real_record_paths[arm] = record_path
        real_records = step5._verified_real_preflight_records(
            real_root, dev_cfg, real_task)
        real_receipt = {
            "identity": step5.real_preflight_identity(good_cfg, real_task),
            "dev_config": str(dev_cfg_path.resolve()),
            "records": real_records,
        }
        step5.real_preflight_receipt_path(receipt_dir).write_text(
            json.dumps(real_receipt), encoding="utf-8")
        valid_real_receipt = step5.real_preflight_receipt_problem(
            receipt_dir, good_cfg, real_task)
        candidate_record = real_record_paths["candidate"]
        candidate_bytes = candidate_record.read_bytes()
        candidate_record.write_text("{}\n", encoding="utf-8")
        tampered_real_receipt = step5.real_preflight_receipt_problem(
            receipt_dir, good_cfg, real_task)
        candidate_record.write_bytes(candidate_bytes)
        candidate_doc = json.loads(candidate_bytes.decode("utf-8"))
        candidate_doc["attempt"] = 2
        candidate_record.write_text(
            json.dumps(candidate_doc), encoding="utf-8")
        try:
            step5._verified_real_preflight_records(
                real_root, dev_cfg, real_task)
            noncontiguous_real_rejected = False
        except runner.InfraFailure:
            noncontiguous_real_rejected = True
        candidate_doc["attempt"] = 1
        candidate_doc["backend_version"] = "drifted backend"
        candidate_record.write_text(
            json.dumps(candidate_doc), encoding="utf-8")
        try:
            step5._verified_real_preflight_records(
                real_root, dev_cfg, real_task)
            runtime_real_rejected = False
        except runner.InfraFailure:
            runtime_real_rejected = True
        candidate_record.write_bytes(candidate_bytes)
        renamed_seal_files = dict(fake_seal_files)
        renamed_seal_files[step5.REGISTERED_HOLDOUT_TASKS[0]] = (
            real_task_digest)
        step5.verified_seal = lambda _config: (
            ws / "synthetic-seal-manifest.json", {}, renamed_seal_files)
        try:
            step5.real_preflight_identity(good_cfg, real_task)
            renamed_holdout_rejected = False
        except runner.InfraFailure:
            renamed_holdout_rejected = True
        step5.verified_seal = original_verified_seal
        real_gate_ok = (
            missing_real_receipt and not valid_real_receipt
            and tampered_real_receipt
            and noncontiguous_real_rejected and runtime_real_rejected
            and renamed_holdout_rejected
            and step5._real_preflight_final_ok("baseline", {
                "status": "workflow_failure",
                "failure_kind": "artifact_contract",
                "artifact_gate": "failed",
            })
            and not step5._real_preflight_final_ok("candidate", {
                "status": "workflow_failure",
                "failure_kind": "artifact_contract",
                "artifact_gate": "failed",
            })
            and "next" not in step5.DEFAULT_PHASES
            and "real-preflight" in step5.DEFAULT_PHASES
            and getattr(step5, "phase_" + "real-preflight".replace(
                "-", "_")) is step5.phase_real_preflight)
        canonical_task_dir = ws / "step5-canonical-tasks"
        canonical_task_dir.mkdir()
        for task_name in step5.REGISTERED_HOLDOUT_TASKS:
            (canonical_task_dir / task_name).write_text(
                "synthetic canonicalization input\n", encoding="utf-8")
        shuffled = [str(canonical_task_dir / n) for n in (
            step5.REGISTERED_HOLDOUT_TASKS[3],
            step5.REGISTERED_HOLDOUT_TASKS[0],
            step5.REGISTERED_HOLDOUT_TASKS[5],
            step5.REGISTERED_HOLDOUT_TASKS[1],
            step5.REGISTERED_HOLDOUT_TASKS[4],
            step5.REGISTERED_HOLDOUT_TASKS[2],
        )]
        ordered, order_problem = step5.canonical_tasks(shuffled)
        canonical_ok = (
            not order_problem
            and [Path(x).name for x in ordered]
            == list(step5.REGISTERED_HOLDOUT_TASKS)
            and bool(step5.canonical_tasks(shuffled[:5])[1])
            and bool(step5.canonical_tasks(shuffled + shuffled[:1])[1]))
        relative_tasks = [
            os.path.relpath(canonical_task_dir / name, Path.cwd())
            for name in step5.REGISTERED_HOLDOUT_TASKS
        ]
        relative_ordered, relative_problem = step5.canonical_tasks(
            relative_tasks)
        canonical_ok &= (
            not relative_problem
            and relative_ordered
            == [str((canonical_task_dir / name).resolve())
                for name in step5.REGISTERED_HOLDOUT_TASKS])
        mapped_repos = {}
        mapped_shas = {}
        for name in runner.REGISTERED_HOLDOUT_REPOS:
            mapped_repos[name], mapped_shas[name] = make_git_repo(
                ws, f"step5-map-{name}")
        normalized_repos, repo_normalize_problem = step5.canonical_repos([
            f"NeoMenu={os.path.relpath(mapped_repos['neomenu'], Path.cwd())}",
            f"rpa={os.path.relpath(mapped_repos['rpa'], Path.cwd())}",
            "livekit-voice-agent="
            f"{os.path.relpath(mapped_repos['livekit-voice-agent'], Path.cwd())}",
        ])
        _duplicate_repos, duplicate_repo_problem = step5.canonical_repos([
            f"rpa={mapped_repos['rpa']}",
            f"dsmolchanov/rpa={mapped_repos['rpa']}",
            f"neomenu={mapped_repos['neomenu']}",
            f"livekit-voice-agent={mapped_repos['livekit-voice-agent']}",
        ])
        _missing_repos, missing_repo_problem = step5.canonical_repos([
            f"rpa={mapped_repos['rpa']}",
            f"neomenu={mapped_repos['neomenu']}",
        ])
        canonical_ok &= (
            not repo_normalize_problem
            and normalized_repos == [
                "livekit-voice-agent="
                f"{mapped_repos['livekit-voice-agent'].resolve()}",
                f"neomenu={mapped_repos['neomenu'].resolve()}",
                f"rpa={mapped_repos['rpa'].resolve()}",
            ]
            and bool(duplicate_repo_problem)
            and bool(missing_repo_problem))
        pin_tasks = []
        pin_repos = (
            "rpa", "livekit-voice-agent", "neomenu",
            "rpa", "livekit-voice-agent", "neomenu",
        )
        pin_task_dir = ws / "step5-pin-tasks"
        pin_task_dir.mkdir()
        for index, repo_name in enumerate(pin_repos, start=1):
            pin_task = pin_task_dir / f"holdout-v2-{index}.md"
            pin_task.write_text(
                f"---\ntarget-repo: {repo_name}\n"
                f"target-sha: {mapped_shas[repo_name]}\n---\n",
                encoding="utf-8")
            pin_tasks.append(str(pin_task))
        pin_mapping_ok = not step5.task_repo_pin_problem(
            pin_tasks, normalized_repos)
        pin_task_bytes = Path(pin_tasks[-1]).read_bytes()
        Path(pin_tasks[-1]).write_text(
            pin_task_bytes.decode("utf-8").replace(
                mapped_shas[pin_repos[-1]], "0" * 40),
            encoding="utf-8")
        pin_mapping_ok &= bool(step5.task_repo_pin_problem(
            pin_tasks, normalized_repos))
        Path(pin_tasks[-1]).write_bytes(pin_task_bytes)
        scoped_cfg = json.loads(json.dumps(good_cfg))
        scoped_cfg["arms"]["ablation"]["schedule_tasks"] = list(
            step5.REGISTERED_ABLATION_TASKS)
        ablation_scope_ok = not step5.ablation_scope_problem(
            scoped_cfg, ordered)
        scoped_cfg["arms"]["ablation"]["schedule_tasks"].reverse()
        ablation_scope_ok &= bool(step5.ablation_scope_problem(
            scoped_cfg, ordered))
        scoped_cfg["arms"]["ablation"]["schedule_tasks"] = [
            str(Path(ordered[index]).resolve()) for index in (0, 2)
        ]
        ablation_scope_ok &= bool(step5.ablation_scope_problem(
            scoped_cfg, ordered))

        # Protocol v2 has one population per judge role. Selection is by
        # immutable artifact-gate binding, not by terminal status: documents
        # produced before timeout/abort stay in, while a true no-document
        # outcome stays out. There is no legacy primary/diagnostic command.
        population_dir = ws / "step5-v2-population"
        population_dir.mkdir()
        population_specs = (
            ("111111111111", "completed", "passed", "anon", None),
            ("222222222222", "workflow_failure", "failed", "diag",
             "timeout"),
            ("333333333333", "workflow_failure", "passed", "anon",
             "abort"),
        )
        population_results = []
        for run_id, status, gate, suffix, failure_kind in population_specs:
            artifact = population_dir / f"run-{run_id}-{suffix}.md"
            artifact.write_text(
                f"# anonymized synthetic document {run_id}\n",
                encoding="utf-8")
            digest = step5.file_digest(artifact)
            population_results.append({
                "run_id": run_id,
                "status": status,
                "failure_kind": failure_kind,
                "artifact_gate": gate,
                "artifact_sha256": digest if suffix == "anon" else None,
                "diagnostic_sha256": digest if suffix == "diag" else None,
                "protocol_version": step5.REGISTERED_PROTOCOL_VERSION,
                "environment_policy_id": (
                    step5.REGISTERED_ENVIRONMENT_POLICY_ID),
                "runtime_pins": runner.protocol_v2_runtime_pins(good_cfg),
                "telemetry_policy_id": (
                    step5.REGISTERED_AGGREGATION_POLICY["telemetry"]),
                "telemetry_eligible": True,
                "telemetry_exclusion_reason": None,
            })
        population_results.append({
            "run_id": "444444444444",
            "status": "workflow_failure",
            "failure_kind": "missing_document",
            "artifact_gate": "not_evaluated",
            "artifact_sha256": None,
            "diagnostic_sha256": None,
            "protocol_version": step5.REGISTERED_PROTOCOL_VERSION,
            "environment_policy_id": (
                step5.REGISTERED_ENVIRONMENT_POLICY_ID),
            "runtime_pins": runner.protocol_v2_runtime_pins(good_cfg),
            "telemetry_policy_id": (
                step5.REGISTERED_AGGREGATION_POLICY["telemetry"]),
            "telemetry_eligible": True,
            "telemetry_exclusion_reason": None,
        })
        all_docs = step5.all_docs_population(
            population_results, population_dir)
        population_names = [Path(path).name for path in all_docs]

        def population_refused(mutator):
            rows = json.loads(json.dumps(population_results))
            mutator(rows)
            try:
                step5.all_docs_population(rows, population_dir)
            except runner.InfraFailure:
                return True
            return False

        population_fail_closed = all((
            population_refused(lambda rows: rows[0].update(
                diagnostic_sha256="a" * 64)),
            population_refused(lambda rows: rows[1].update(
                environment_policy_id="ambient-env")),
            population_refused(lambda rows: rows[3].update(
                artifact_sha256="b" * 64)),
            population_refused(lambda rows: rows.append(rows[0])),
        ))
        command_root = ws / "step5-v2-command-seal"
        (command_root / "snapshots").mkdir(parents=True)
        command_tasks = []
        archetypes = (
            "1 subsystem", "2 largest", "3 narrow where-is",
            "4 thoughts", "5 external", "6 premise",
        )
        repos = ("rpa", "livekit-voice-agent", "neomenu",
                 "rpa", "livekit-voice-agent", "neomenu")
        for index, name in enumerate(step5.REGISTERED_HOLDOUT_TASKS):
            task_path = command_root / name
            task_path.write_text(
                "---\n"
                f"archetype: \"{archetypes[index]}\"\n"
                f"target-repo: {repos[index]}\n"
                f"target-sha: {'a' * 40}\n"
                + ("external-snapshots: true\n" if index == 4 else "")
                + "---\n\n## Task prompt\n\n"
                + "Synthetic operator task.\n",
                encoding="utf-8")
            command_tasks.append(str(task_path))
        drift_path = ws / "step5-v2-drift.json"
        drift_path.write_text(json.dumps({
            step5.REGISTERED_HOLDOUT_TASKS[4]: {"changed": {}},
        }), encoding="utf-8")
        command_args = SimpleNamespace(
            config=str(ws / "operator-config.json"),
            out=str(ws / "operator-output"),
            tasks=command_tasks,
            repos=["rpa=/clones/rpa", "livekit-voice-agent=/clones/livekit",
                   "neomenu=/clones/neomenu"],
            scorer_seed=step5.REGISTERED_SCORER_SEED,
            verifier_seed=step5.REGISTERED_VERIFIER_SEED,
            drift_report=str(drift_path),
        )
        command_seal = {
            "task_contexts": dict(seal_package.CANONICAL_TASK_CONTEXTS),
            "judge_prompts": dict(
                seal_package.CANONICAL_JUDGE_PROMPTS),
            "snapshot_sources": {
                "snapshots/reference.txt":
                    "https://example.invalid/reference.txt",
            },
            "files": {
                "snapshots/reference.txt": "1" * 64,
            },
        }
        judge_commands, aggregate_command = step5._next_commands(
            command_args, ws / "schedule-manifest.json", all_docs,
            command_root / "seal-manifest.json", command_seal)
        drift_path.write_text(json.dumps({
            step5.REGISTERED_HOLDOUT_TASKS[4]: {"changed": {}},
            step5.REGISTERED_HOLDOUT_TASKS[0]: {"changed": {}},
        }), encoding="utf-8")
        try:
            step5._next_commands(
                command_args, ws / "schedule-manifest.json", all_docs,
                command_root / "seal-manifest.json", command_seal)
            extra_drift_entry_rejected = False
        except runner.InfraFailure:
            extra_drift_entry_rejected = True
        drift_path.write_text(json.dumps({
            step5.REGISTERED_HOLDOUT_TASKS[4]: {"changed": {}},
        }), encoding="utf-8")
        seed_args = SimpleNamespace(
            seed=step5.REGISTERED_SCHEDULE_SEED,
            scorer_seed=step5.REGISTERED_SCORER_SEED,
            verifier_seed=step5.REGISTERED_VERIFIER_SEED,
            drift_report=str(drift_path),
        )
        fixed_seeds_ok = not step5.phase_seed_problem(
            ["schedule", "next"], seed_args)
        for field in ("seed", "scorer_seed", "verifier_seed"):
            drifted_seed_args = SimpleNamespace(**vars(seed_args))
            setattr(drifted_seed_args, field,
                    getattr(drifted_seed_args, field) + 1)
            fixed_seeds_ok &= bool(step5.phase_seed_problem(
                ["schedule", "next"], drifted_seed_args))
        missing_drift_args = SimpleNamespace(**vars(seed_args))
        missing_drift_args.drift_report = None
        fixed_seeds_ok &= bool(step5.phase_seed_problem(
            ["schedule", "next"], missing_drift_args))
        registered_schedule = {
            "seed": step5.REGISTERED_SCHEDULE_SEED,
            "entries": ["synthetic-fixed-order"],
        }
        registered_schedule_path = ws / "step5-registered-schedule.json"
        registered_schedule_path.write_text(
            json.dumps(registered_schedule), encoding="utf-8")
        schedule_calls = []
        original_make_schedule = runner.make_schedule

        def fixed_schedule_probe(config, tasks, replicates, seed,
                                 allow_nonstandard=False):
            schedule_calls.append((config, tasks, replicates, seed,
                                   allow_nonstandard))
            return registered_schedule

        runner.make_schedule = fixed_schedule_probe
        try:
            schedule_seed_ok = (
                step5.verify_registered_schedule(
                    registered_schedule_path, good_cfg, command_tasks)
                == registered_schedule)
            drifted_schedule = json.loads(json.dumps(registered_schedule))
            drifted_schedule["seed"] += 1
            registered_schedule_path.write_text(
                json.dumps(drifted_schedule), encoding="utf-8")
            try:
                step5.verify_registered_schedule(
                    registered_schedule_path, good_cfg, command_tasks)
            except runner.InfraFailure:
                schedule_seed_ok &= True
            else:
                schedule_seed_ok = False
        finally:
            runner.make_schedule = original_make_schedule
        schedule_seed_ok &= (
            len(schedule_calls) == 2
            and all(call[2:] == (
                step5.REGISTERED_REPLICATES,
                step5.REGISTERED_SCHEDULE_SEED,
                False,
            ) for call in schedule_calls))

        def option_values(command, start, end):
            first = command.index(start) + 1
            last = command.index(end, first)
            return command[first:last]

        exact_commands_ok = (
            len(judge_commands) == 2
            and all(option_values(command, "--docs", "--manifest")
                    == all_docs for command in judge_commands)
            and all("--diagnostic-axis" not in command
                    for command in judge_commands)
            and all("--task-snapshots" in command
                    and "--drift-report" in command
                    for command in judge_commands)
            and "--evidence-repos" not in judge_commands[0]
            and "--evidence-repos" in judge_commands[1]
            and judge_commands[0][
                judge_commands[0].index("--scoring-seed") + 1]
            == str(step5.REGISTERED_SCORER_SEED)
            and judge_commands[1][
                judge_commands[1].index("--scoring-seed") + 1]
            == str(step5.REGISTERED_VERIFIER_SEED)
            and aggregate_command[0] == sys.executable
            and aggregate_command[1]
            == str((HERE / "aggregate_results.py").resolve())
            and "scoring-scorer-all-docs-manifest.json" in " ".join(
                aggregate_command)
            and "scoring-verifier-all-docs-manifest.json" in " ".join(
                aggregate_command))
        step5_freeze_proofs = {
            "constants_in_plan": constants_in_plan,
            "shared_registration": shared_registration_consistent,
            "sandbox_interpreter_behavior": fake_python_rejected,
            "registration_state": registration_state_ok,
            "clean_warnings": not clean_warnings,
            "config_drifts": all(drifts),
            "missing_receipt": bool(missing_receipt),
            "fresh_receipt": not fresh_receipt,
            "stale_receipt": bool(stale_receipt),
            "partial_gates": bool(partial_gates),
            "missing_transcripts": bool(no_transcripts),
            "tampered_transcript": bool(tampered),
            "nonpassing_transcript": bool(not_passing),
            "canonical_tasks": canonical_ok,
            "ablation_scope": ablation_scope_ok,
            "repo_pin_mapping": pin_mapping_ok,
            "real_preflight_gate": real_gate_ok,
        }
        ok &= check(
            "step-5 driver restates the freeze record and refuses drift",
            all(step5_freeze_proofs.values()), notes,
            "failed=" + ",".join(
                name for name, passed in step5_freeze_proofs.items()
                if not passed))

        ok &= check(
            "direct standard-v2 drift fails before output or backend launch",
            direct_drift_prelaunch, notes)

        ok &= check(
            "step-5 v2 handoff derives one all-doc population and two roles",
            population_names == [
                "run-111111111111-anon.md",
                "run-222222222222-diag.md",
                "run-333333333333-anon.md",
            ]
            and population_fail_closed and exact_commands_ok
            and fixed_seeds_ok and schedule_seed_ok
            and extra_drift_entry_rejected,
            notes)

        ok &= check(
            "macOS wrapper registered (behavior validated on the operator host)",
            mac_help.returncode == 0
            and "--confine-to" in mac_help.stdout
            and "(deny default)" in wrap_text
            and "build_pinned_gitdir" in wrap_text
            and notmac.returncode != 0
            and (sys.platform == "darwin"
                 or "operator" in (notmac.stdout + notmac.stderr))
            and rebuild_ok,
            notes)
        step5.operator_runtime_observation = original_runtime_observation

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
            and ("cannot read task file" in record_bin.get("failure", "")
                 or "cannot decode task file"
                 in record_bin.get("failure", "")),
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
            profile = Path(r["profile"])
            settings = r.get("judge_settings", {})
            iso_ok &= not str(cwd).startswith(str(ws))
            iso_ok &= not cwd.exists()
            iso_ok &= not profile.exists()
            iso_ok &= bool(settings.get("permissions", {}).get("deny"))
        ok &= check(
            "blind judge isolated and temp root removed (outside run tree, "
            "fs tools denied)",
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
        sm_path = resume_out / "scoring-scorer-primary-manifest.json"
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
        smp = rec_out / "scoring-scorer-primary-manifest.json"
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
        fmp = forged_out / "scoring-scorer-primary-manifest.json"
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
        gmp = gone_out / "scoring-scorer-primary-manifest.json"
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
            bindoc_ok = ("cannot read scoring document" in str(exc)
                         or "scoring document is not UTF-8" in str(exc))
        ok &= check(
            "missing or non-UTF-8 scoring document classified as infra",
            missdoc_ok and bindoc_ok, notes)
        malformed_out = ws / "judge-batch-malformed"
        malformed_out.mkdir()
        (malformed_out / ".scoring-scorer-primary.lock").write_text(
            "", encoding="utf-8")
        (malformed_out / "scoring-scorer-primary-manifest.json").write_text(
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
                          / "scoring-scorer-primary-manifest.json").exists()
            sid_crash = json.loads(
                (flaky_out / "scoring-scorer-primary-manifest.json")
                .read_text(encoding="utf-8"))["scoring_id"]
            flaky_res = runner.score(flaky_cfg, docs, judge, flaky_out,
                                     scoring_seed=5, allow_unscheduled=True)
        finally:
            os.environ.pop("MOCK_STATE_FILE", None)
        sm_flaky = json.loads(
            (flaky_out / "scoring-scorer-primary-manifest.json")
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
        complex_fingerprint = (
            "---\n'researcher': Quoted Secret\nbranch: >\n"
            "  Block Scalar Secret\nlast_updated_by: |\n"
            "  Another Secret\n---\n\nbody\n")
        complex_doc = ws / "complex-fingerprint.md"
        complex_doc.write_text(complex_fingerprint, encoding="utf-8")
        try:
            runner.assert_blind_scorable(complex_doc)
            complex_raw_refused = False
        except runner.InfraFailure as exc:
            complex_raw_refused = "not anonymized" in str(exc)
        complex_anon = runner.anonymize(complex_fingerprint, "complex")
        complex_anon_doc = ws / "complex-fingerprint-anon.md"
        complex_anon_doc.write_text(complex_anon, encoding="utf-8")
        try:
            runner.assert_blind_scorable(complex_anon_doc)
            complex_anon_accepted = True
        except runner.InfraFailure:
            complex_anon_accepted = False
        explicit_fingerprint = (
            "---\n? researcher\n: Explicit Secret\n"
            "? [branch]\n: Block Branch Secret\n"
            "- ? researcher\n  : List Explicit Secret\n"
            "{? branch: Flow Explicit Secret}\n"
            "last_updated_by: !!str |\n  Tagged Block Secret\n"
            "**RESEARCHER**: Bold Case Secret\n"
            "**Last-Updated-By**: Bold Updated Secret\n"
            "# malformed frontmatter without a closing delimiter\n")
        explicit_doc = ws / "explicit-fingerprint.md"
        explicit_doc.write_text(explicit_fingerprint, encoding="utf-8")
        try:
            runner.assert_blind_scorable(explicit_doc)
            explicit_raw_refused = False
        except runner.InfraFailure as exc:
            explicit_raw_refused = "fingerprint key" in str(exc)
        explicit_anon = runner.anonymize(
            explicit_fingerprint, "explicit")
        explicit_anon_doc = ws / "explicit-fingerprint-anon.md"
        explicit_anon_doc.write_text(explicit_anon, encoding="utf-8")
        try:
            runner.assert_blind_scorable(explicit_anon_doc)
            explicit_anon_accepted = True
        except runner.InfraFailure:
            explicit_anon_accepted = False
        nested_delimiter_fingerprint = (
            "---\nresearcher: |\n  Alice\n  ---\n"
            "  SecretSurname\n- researcher: Sequence Secret\n"
            "---\n\nbody\n")
        nested_delimiter_doc = ws / "nested-delimiter-fingerprint.md"
        nested_delimiter_doc.write_text(
            nested_delimiter_fingerprint, encoding="utf-8")
        try:
            runner.assert_blind_scorable(nested_delimiter_doc)
            nested_delimiter_raw_refused = False
        except runner.InfraFailure as exc:
            nested_delimiter_raw_refused = "not anonymized" in str(exc)
        nested_delimiter_anon = runner.anonymize(
            nested_delimiter_fingerprint, "nested")
        nested_delimiter_anon_doc = (
            ws / "nested-delimiter-fingerprint-anon.md")
        nested_delimiter_anon_doc.write_text(
            nested_delimiter_anon, encoding="utf-8")
        try:
            runner.assert_blind_scorable(nested_delimiter_anon_doc)
            nested_delimiter_anon_accepted = True
        except runner.InfraFailure:
            nested_delimiter_anon_accepted = False
        ok &= check(
            "all YAML fingerprint spellings are refused and fully masked",
            bom_ok and off_ok
            and "Real Name" not in anon_bom
            and "[anonymized:tid]" in anon_bom
            and complex_raw_refused and complex_anon_accepted
            and "Quoted Secret" not in complex_anon
            and "Block Scalar Secret" not in complex_anon
            and "Another Secret" not in complex_anon
            and "[anonymized:complex]" in complex_anon
            and explicit_raw_refused and explicit_anon_accepted
            and "Explicit Secret" not in explicit_anon
            and "Block Branch Secret" not in explicit_anon
            and "List Explicit Secret" not in explicit_anon
            and "Flow Explicit Secret" not in explicit_anon
            and "Tagged Block Secret" not in explicit_anon
            and "Bold Case Secret" not in explicit_anon
            and "Bold Updated Secret" not in explicit_anon
            and "[anonymized:explicit]" in explicit_anon
            and nested_delimiter_raw_refused
            and nested_delimiter_anon_accepted
            and "Alice" not in nested_delimiter_anon
            and "SecretSurname" not in nested_delimiter_anon
            and "Sequence Secret" not in nested_delimiter_anon
            and "[anonymized:nested]" in nested_delimiter_anon,
            notes)

        malformed_alias_fingerprint = (
            "---\nidentity: &who Malformed Alias Secret\n"
            "researcher: *who\n"
            "# malformed frontmatter without a closing delimiter\n")
        malformed_alias_anon = runner.anonymize(
            malformed_alias_fingerprint, "malformed-alias")
        malformed_alias_doc = ws / "malformed-alias-anon.md"
        malformed_alias_doc.write_text(
            malformed_alias_anon, encoding="utf-8")
        try:
            runner.assert_blind_scorable(malformed_alias_doc)
            malformed_alias_ok = True
        except runner.InfraFailure:
            malformed_alias_ok = False
        ok &= check(
            "malformed fingerprint aliases erase their anchor definitions",
            malformed_alias_ok
            and "Malformed Alias Secret" not in malformed_alias_anon,
            notes)
        pend_out = ws / "judge-batch-pending"
        p1 = runner.score(config, docs, judge, pend_out, scoring_seed=5,
                          allow_unscheduled=True)
        pmp = pend_out / "scoring-scorer-primary-manifest.json"
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
        unsafe_atomic_results = []
        for target_kind in ("symlink", "directory", "hardlink"):
            target = ws / f"unsafe-atomic-{target_kind}.json"
            victim = ws / f"unsafe-atomic-{target_kind}-victim.txt"
            victim.write_text("unchanged\n", encoding="utf-8")
            if target_kind == "symlink":
                target.symlink_to(victim)
            elif target_kind == "directory":
                target.mkdir()
            else:
                os.link(victim, target)
            try:
                runner.atomic_write_text(target, "replacement\n")
                unsafe_atomic_blocked = False
            except runner.InfraFailure:
                unsafe_atomic_blocked = True
            unsafe_atomic_results.append(
                unsafe_atomic_blocked
                and victim.read_text(encoding="utf-8") == "unchanged\n"
                and (target.is_dir() if target_kind == "directory" else True)
            )
        ok &= check(
            "atomic writer refuses symlink/directory/hardlink targets",
            all(unsafe_atomic_results), notes)
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
        bad_live_sha = hashlib.sha256(
            (refetch_bad / "b" / "index.html").read_bytes()).hexdigest()
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_ok)
        drift_ok_file = ws / "drift-unchanged.json"
        drift_ok_file.write_text(json.dumps(
            {task_snap.name: {"changed": {}}}), encoding="utf-8")
        drift_bad_file = ws / "drift-drifted.json"
        drift_bad_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "observed_sha256": bad_live_sha,
                    "material": True,
                    "rationale": "ground-truth section replaced"}}}}),
            encoding="utf-8")
        drift_cosmetic_file = ws / "drift-cosmetic.json"
        drift_cosmetic_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "observed_sha256": bad_live_sha,
                    "material": False,
                    "rationale": "footer timestamp only; ground-truth "
                                 "sections untouched"}}}}),
            encoding="utf-8")
        drift_noadj_file = ws / "drift-noadj.json"
        drift_noadj_file.write_text(json.dumps(
            {task_snap.name: {"changed": {}}}), encoding="utf-8")
        drift_list_file = ws / "drift-list.json"
        drift_list_file.write_text(json.dumps(
            {task_snap.name: {"changed": []}}), encoding="utf-8")
        drift_numeric_file = ws / "drift-numeric-rationale.json"
        drift_numeric_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "observed_sha256": bad_live_sha,
                    "material": True, "rationale": 7}}}}),
            encoding="utf-8")
        drift_extra_file = ws / "drift-extra-field.json"
        drift_extra_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "observed_sha256": bad_live_sha,
                    "material": True,
                    "rationale": "material section changed",
                    "extra": "not registered"}}}}),
            encoding="utf-8")
        drift_wrong_sha_file = ws / "drift-wrong-observed-sha.json"
        drift_wrong_sha_file.write_text(json.dumps(
            {task_snap.name: {"changed": {
                "external-snapshots/b/index.html": {
                    "observed_sha256": "0" * 64,
                    "material": True,
                    "rationale": "material section changed"}}}}),
            encoding="utf-8")
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
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_ok)
        malformed_unchanged_ok = True
        malformed_unchanged_outputs = []
        for label, malformed_path in (
            ("list", drift_list_file),
            ("stale", drift_bad_file),
        ):
            malformed_out = ws / f"judge-drift-{label}-unchanged"
            malformed_unchanged_outputs.append(malformed_out)
            try:
                runner.score(
                    snap_cfg, snap_docs, judge, malformed_out,
                    scoring_seed=5, manifest_path=snap_manifest_path,
                    score_task_paths=[str(task_snap)], task_contexts=snap_ctx,
                    seal_manifest_path=seal_file,
                    task_snapshots={task_snap.name: str(snap_dir)},
                    drift_report_path=malformed_path)
                malformed_unchanged_ok = False
            except runner.InfraFailure:
                malformed_unchanged_ok &= not list(
                    malformed_out.glob("scoring-*-manifest.json"))
        malformed_changed_ok = True
        os.environ["MOCK_LIVE_ROOT"] = str(refetch_bad)
        for label, malformed_path in (
            ("list", drift_list_file),
            ("numeric", drift_numeric_file),
            ("extra", drift_extra_file),
            ("wrong-sha", drift_wrong_sha_file),
        ):
            malformed_out = ws / f"judge-drift-malformed-{label}"
            try:
                runner.score(
                    snap_cfg, snap_docs, judge, malformed_out,
                    scoring_seed=5, manifest_path=snap_manifest_path,
                    score_task_paths=[str(task_snap)],
                    task_contexts=snap_ctx, seal_manifest_path=seal_file,
                    task_snapshots={task_snap.name: str(snap_dir)},
                    drift_report_path=malformed_path)
                malformed_changed_ok = False
            except runner.InfraFailure:
                malformed_changed_ok &= not list(
                    malformed_out.glob("scoring-*-manifest.json"))
        ok &= check(
            "malformed drift maps/rationales refused before batch creation",
            malformed_unchanged_ok
            and all(not list(path.glob("scoring-*-manifest.json"))
                    for path in malformed_unchanged_outputs)
            and malformed_changed_ok,
            notes)
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
                    "observed_sha256": bad_live_sha,
                    "material": True,
                    "rationale": "a different recorded basis"}}}}),
            encoding="utf-8")
        mdr_manifest = (ws / "judge-drifted"
                        / "scoring-verifier-primary-manifest.json")
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
            claim_ok = "exactly one `changed` object" in str(exc)
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
        sd_manifest = ws / "judge-scorer-drift" / "scoring-scorer-primary-manifest.json"
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
            noadj_ok = "must adjudicate exactly" in str(exc)
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
            localcopy_ok = "exactly one `changed` object" in str(exc)
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
            and all(r.get("axis") == "primary" for r in two_res)
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
        # Registered amendment (owner decision, 2026-07-28): gate-failed
        # replicates stay counted workflow failures for the primary
        # outcome, but their documents' content is blind-scored on a
        # separate diagnostic axis — and NEVER leaks into the primary
        # batch.
        cfg_diag, _ = build_config(ws, "bad-artifact")
        sched_diag = runner.make_schedule(cfg_diag, [str(task_s)], 1,
                                          seed=17, allow_nonstandard=True)
        sched_diag_path = ws / "schedule-diag.json"
        sched_diag_path.write_text(json.dumps(sched_diag),
                                   encoding="utf-8")
        man_diag = runner.run_schedule(cfg_diag, sched_diag_path,
                                       {"mock-repo": str(repo_s)},
                                       ws / "out-diag", [str(task_s)])
        diag_recs = [r for r in man_diag["results"]
                     if r.get("status") == "workflow_failure"
                     and r.get("diagnostic_sha256")]
        diag_docs = [ws / "out-diag" / f"run-{r['run_id']}-diag.md"
                     for r in diag_recs]
        diag_digest_ok = bool(diag_recs) and all(
            hashlib.sha256(d.read_bytes()).hexdigest()
            == r["diagnostic_sha256"]
            for d, r in zip(diag_docs, diag_recs))
        man_diag_path = ws / "out-diag" / "schedule-manifest.json"
        try:
            runner.score(cfg_diag, diag_docs, judge,
                         ws / "judge-diag-prim", scoring_seed=7,
                         manifest_path=man_diag_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            diag_prim_refused = False
        except runner.InfraFailure as exc:
            diag_prim_refused = "exactly once" in str(exc)
        dres = runner.score(cfg_diag, diag_docs, judge, ws / "judge-diag",
                            scoring_seed=7, manifest_path=man_diag_path,
                            score_task_paths=[str(task_s)],
                            task_contexts=sched_ctx,
                            seal_manifest_path=seal_file,
                            diagnostic_axis=True)
        # A malformed metadata STRUCTURE (unclosed frontmatter) is one
        # of the gate failures the diagnostic axis exists to score: the
        # anonymizer must mask fingerprint keys anyway, or one broken
        # replicate would abort the whole blind-scoring batch.
        broken_doc = ("---\n"
                      "researcher: Real Name\n"
                      "git_commit: 1234567deadbeef\n"
                      "# Research: unclosed frontmatter\n"
                      "**Researcher**: Real Name\n")
        masked = runner.anonymize(broken_doc, "probe")
        masked_path = ws / "run-probe-diag.md"
        masked_path.write_text(masked, encoding="utf-8")
        try:
            runner.assert_blind_scorable(masked_path)
            unclosed_masked_ok = "Real Name" not in masked
        except runner.InfraFailure:
            unclosed_masked_ok = False
        # Primary and diagnostic batches share an output directory:
        # state is namespaced by role AND axis, so a completed primary
        # batch must not reject the diagnostic batch.
        shared_out = ws / "judge-diag-shared"
        try:
            runner.score(cfg_diag, [], judge, shared_out,
                         scoring_seed=7,
                         manifest_path=man_diag_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file)
            empty_v1_refused = False
        except runner.InfraFailure as exc:
            empty_v1_refused = "protocol-v2" in str(exc)
        dres_shared = runner.score(cfg_diag, diag_docs, judge, shared_out,
                                   scoring_seed=7,
                                   manifest_path=man_diag_path,
                                   score_task_paths=[str(task_s)],
                                   task_contexts=sched_ctx,
                                   seal_manifest_path=seal_file,
                                   diagnostic_axis=True)
        try:
            runner.score(cfg_diag, diag_docs, judge,
                         ws / "judge-diag-verif", scoring_seed=7,
                         manifest_path=man_diag_path,
                         score_task_paths=[str(task_s)],
                         task_contexts=sched_ctx,
                         seal_manifest_path=seal_file,
                         evidence_repos={"mock-repo": str(repo_s)},
                         diagnostic_axis=True)
            diag_verif_refused = False
        except runner.InfraFailure as exc:
            diag_verif_refused = "blind SCORER" in str(exc)
        ok &= check(
            "gate-failed replicates scored on the diagnostic axis only",
            diag_digest_ok and diag_prim_refused
            and len(dres) == len(diag_recs)
            and all(r.get("axis") == "diagnostic" for r in dres)
            and unclosed_masked_ok
            and empty_v1_refused
            and len(dres_shared) == len(diag_recs)
            and diag_verif_refused,
            notes)
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
            sdrift_ok = ("task file changed" in str(exc)
                         or "schedule does not match" in str(exc))
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
        vdeny = vres[0].get("judge_settings", {}).get(
            "permissions", {}).get("deny", [])
        sandbox_echo = (echo_dir / "sandbox.txt").read_text(
            encoding="utf-8").strip()
        ok &= check(
            "verifier judge gets read-only evidence worktree at pinned sha",
            vres[0].get("role") == "verifier"
            and vres[0].get("evidence_sha") == ev_sha
            and "README.md" in listing
            and not Path(vres[0]["cwd"]).exists()
            and not Path(vres[0]["profile"]).exists()
            and "Read" not in vdeny and "Bash" in vdeny and "Write" in vdeny,
            notes)
        ok &= check(
            "judge session sandbox confined to its evidence worktree",
            sandbox_echo == vres[0].get("cwd"),
            notes)

        # Protocol v2 is intentionally exercised through manifest-bound
        # nonstandard schedules, not through direct/unscheduled scoring.
        # These fixtures cover the same seal, record, and retry boundaries
        # as holdout while keeping synthetic preflight small and offline.
        repo_v2, sha_v2 = make_git_repo(ws, "protocol-v2")

        # A process may die cleanly between two infrastructure attempts.
        # The next invocation must consume the persisted attempt-1 record
        # and continue at attempt 2, never restart a fresh 1..3 budget.
        v2_partial = make_v2_fixture(
            ws, "partial-infra", repo_v2, sha_v2,
            run_mode="flaky-infra", execute_run=False)
        partial_schedule = json.loads(
            v2_partial["schedule"].read_text(encoding="utf-8"))
        partial_digest = runner.schedule_digest(partial_schedule)
        v2_partial["run_output"].mkdir(parents=True, exist_ok=True)
        (v2_partial["run_output"] / ".run-schedule.lock").write_text(
            "", encoding="utf-8")
        partial_first = runner.run_task(
            v2_partial["config"], "mock", v2_partial["task"], repo_v2,
            v2_partial["run_output"], attempt=1, scheduled=True,
            schedule_binding={
                "schedule_digest": partial_digest,
                "schedule_index": 0,
            },
        )
        partial_manifest = runner.run_schedule(
            v2_partial["config"], v2_partial["schedule"],
            {"mock-repo": str(repo_v2)}, v2_partial["run_output"],
            [str(v2_partial["task"])],
        )
        partial_records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(v2_partial["run_output"].glob("run-*.json"))
            if path.name.count("-") == 1
        ]
        ok &= check(
            "protocol-v2 retry budget persists across schedule resume",
            partial_first.get("status") == "infra_failure"
            and partial_manifest.get("complete") is True
            and partial_manifest["results"][0].get("attempts") == 2
            and sorted(record.get("attempt") for record in partial_records)
            == [1, 2],
            notes)

        v2_infra_exhaust = make_v2_fixture(
            ws, "run-infra-exhaust", repo_v2, sha_v2,
            run_mode="infra-crash", execute_run=False)
        try:
            runner.run_schedule(
                v2_infra_exhaust["config"], v2_infra_exhaust["schedule"],
                {"mock-repo": str(repo_v2)},
                v2_infra_exhaust["run_output"],
                [str(v2_infra_exhaust["task"])],
            )
            run_exhaust_first = False
        except runner.InfraFailure as exc:
            run_exhaust_first = "terminally invalid" in str(exc)
        run_terminal = (v2_infra_exhaust["run_output"]
                        / "schedule-entry-0-terminal-invalid.json")
        exhaust_before = {
            path.name: path.read_bytes()
            for path in sorted(v2_infra_exhaust["run_output"].glob("*.json"))
        }
        try:
            runner.run_schedule(
                v2_infra_exhaust["config"], v2_infra_exhaust["schedule"],
                {"mock-repo": str(repo_v2)},
                v2_infra_exhaust["run_output"],
                [str(v2_infra_exhaust["task"])],
            )
            run_exhaust_resume = False
        except runner.InfraFailure as exc:
            run_exhaust_resume = "cannot be resumed" in str(exc)
        exhaust_after = {
            path.name: path.read_bytes()
            for path in sorted(v2_infra_exhaust["run_output"].glob("*.json"))
        }
        ok &= check(
            "protocol-v2 run retry exhaustion is terminal across resume",
            run_exhaust_first and run_exhaust_resume
            and json.loads(run_terminal.read_text(
                encoding="utf-8")).get("kind")
            == "infrastructure_retries_exhausted"
            and len([name for name in exhaust_before
                     if name.startswith("run-")]) == 3
            and exhaust_after == exhaust_before,
            notes)

        v2_ambiguous = make_v2_fixture(
            ws, "run-ambiguous", repo_v2, sha_v2,
            run_mode="normal", execute_run=False)
        ambiguous_schedule = json.loads(
            v2_ambiguous["schedule"].read_text(encoding="utf-8"))
        ambiguous_digest = runner.schedule_digest(ambiguous_schedule)
        ambiguous_journal = v2_ambiguous["run_output"] / (
            "run-a11b1a11b1a1.json")
        ambiguous_journal.parent.mkdir(parents=True)
        (v2_ambiguous["run_output"] / ".run-schedule.lock").write_text(
            "", encoding="utf-8")
        ambiguous_journal.write_text(json.dumps({
            "run_id": "a11b1a11b1a1",
            "arm": "mock",
            "task": str(v2_ambiguous["task"]),
            "attempt": 1,
            "status": "in_progress",
            "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
            "runtime_pins": runner.protocol_v2_runtime_pins(
                v2_ambiguous["config"]),
            "schedule_digest": ambiguous_digest,
            "schedule_index": 0,
            "task_sha256": ambiguous_schedule["task_digests"][
                str(v2_ambiguous["task"])],
            "config_digest": runner.config_digest(v2_ambiguous["config"]),
        }, indent=2) + "\n", encoding="utf-8")
        try:
            runner.run_schedule(
                v2_ambiguous["config"], v2_ambiguous["schedule"],
                {"mock-repo": str(repo_v2)}, v2_ambiguous["run_output"],
                [str(v2_ambiguous["task"])],
            )
            run_ambiguous_first = False
        except runner.InfraFailure as exc:
            run_ambiguous_first = "ambiguous_post_launch" in str(exc)
        run_invalid = (v2_ambiguous["run_output"]
                       / "schedule-entry-0-terminal-invalid.json")
        ambiguous_journal.unlink()
        try:
            runner.run_schedule(
                v2_ambiguous["config"], v2_ambiguous["schedule"],
                {"mock-repo": str(repo_v2)}, v2_ambiguous["run_output"],
                [str(v2_ambiguous["task"])],
            )
            run_ambiguous_resume = False
        except runner.InfraFailure as exc:
            run_ambiguous_resume = "cannot be resumed" in str(exc)
        ok &= check(
            "protocol-v2 ambiguous run journal terminally invalidates round",
            run_ambiguous_first and run_ambiguous_resume
            and run_invalid.exists()
            and not list(v2_ambiguous["run_output"].glob("run-*.json")),
            notes)

        v2_residue = make_v2_fixture(
            ws, "run-artifact-residue", repo_v2, sha_v2,
            run_mode="normal")
        residue_summary = v2_residue["manifest"]["results"][0]
        residue_record = (v2_residue["run_output"]
                          / f"run-{residue_summary['run_id']}.json")
        residue_record.unlink()
        try:
            runner.run_schedule(
                v2_residue["config"], v2_residue["schedule"],
                {"mock-repo": str(repo_v2)}, v2_residue["run_output"],
                [str(v2_residue["task"])],
            )
            residue_first = False
        except runner.InfraFailure as exc:
            residue_first = "orphan_artifact_material" in str(exc)
        residue_marker = (v2_residue["run_output"]
                          / "schedule-entry-0-terminal-invalid.json")
        for residue_artifact in v2_residue["run_output"].glob("run-*.md"):
            residue_artifact.unlink()
        try:
            runner.run_schedule(
                v2_residue["config"], v2_residue["schedule"],
                {"mock-repo": str(repo_v2)}, v2_residue["run_output"],
                [str(v2_residue["task"])],
            )
            residue_resume = False
        except runner.InfraFailure as exc:
            residue_resume = "cannot be resumed" in str(exc)
        ok &= check(
            "orphan run artifact residue irreversibly invalidates round",
            residue_first and residue_resume and residue_marker.exists()
            and not list(v2_residue["run_output"].glob("run-*.json")),
            notes)

        v2_concurrent_run = make_v2_fixture(
            ws, "run-concurrent", repo_v2, sha_v2,
            run_mode="slow-normal", execute_run=False)

        def concurrent_run_schedule():
            try:
                return runner.run_schedule(
                    v2_concurrent_run["config"],
                    v2_concurrent_run["schedule"],
                    {"mock-repo": str(repo_v2)},
                    v2_concurrent_run["run_output"],
                    [str(v2_concurrent_run["task"])],
                )
            except runner.InfraFailure as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_run_outcomes = list(pool.map(
                lambda _index: concurrent_run_schedule(), range(2)))
        concurrent_run_records = [
            path for path in v2_concurrent_run["run_output"].glob(
                "run-*.json") if path.name.count("-") == 1
        ]
        concurrent_run_manifest = json.loads(
            v2_concurrent_run["manifest_path"].read_text(encoding="utf-8"))
        ok &= check(
            "protocol-v2 output advisory lock blocks concurrent schedule",
            sum(isinstance(item, dict) for item in concurrent_run_outcomes) == 1
            and sum(isinstance(item, runner.InfraFailure)
                    for item in concurrent_run_outcomes) == 1
            and concurrent_run_manifest.get("complete") is True
            and len(concurrent_run_records) == 1
            and not list(v2_concurrent_run["run_output"].glob("*.claim")),
            notes)

        # A resume must scan ALL future slots before launching the first
        # unfinished one.  Slot 1 material is valid-shaped and immutable, but
        # it is out of order while the manifest prefix is empty.
        v2_future_run = make_v2_fixture(
            ws, "run-future-slot", repo_v2, sha_v2, execute_run=False,
            task_numbers=(1, 2))
        future_run_receipt = (
            v2_future_run["root"] / "unexpected-run-launch.txt")
        v2_future_run["config"]["backend_cmd"].extend([
            "--prompt-receipt-file", str(future_run_receipt)])
        future_schedule = runner.make_schedule(
            v2_future_run["config"],
            [str(task) for task in v2_future_run["tasks"]],
            1, seed=runner.PILOT_V2_SCHEDULE_SEED,
            allow_nonstandard=True)
        v2_future_run["schedule"].write_text(
            json.dumps(future_schedule, indent=2) + "\n", encoding="utf-8")
        future_entry = future_schedule["entries"][1]
        v2_future_run["run_output"].mkdir()
        (v2_future_run["run_output"] / ".run-schedule.lock").write_text(
            "", encoding="utf-8")
        (v2_future_run["run_output"] / "run-f001f001f001.json").write_text(
            json.dumps({
                "run_id": "f001f001f001",
                "arm": future_entry["arm"],
                "task": future_entry["task"],
                "attempt": 1,
                "status": "infra_failure",
                "blocking": False,
                "protocol_version": runner.PILOT_V2_PROTOCOL_VERSION,
                "environment_policy_id": (
                    runner.PILOT_V2_ENVIRONMENT_POLICY_ID),
                "runtime_pins": runner.protocol_v2_runtime_pins(
                    v2_future_run["config"]),
                "schedule_digest": runner.schedule_digest(future_schedule),
                "schedule_index": future_entry["index"],
                "task_sha256": future_schedule["task_digests"][
                    future_entry["task"]],
                "config_digest": runner.config_digest(
                    v2_future_run["config"]),
            }, indent=2) + "\n", encoding="utf-8")
        try:
            runner.run_schedule(
                v2_future_run["config"], v2_future_run["schedule"],
                {"mock-repo": str(repo_v2)},
                v2_future_run["run_output"],
                [str(task) for task in v2_future_run["tasks"]],
            )
            future_run_blocked = False
        except runner.InfraFailure as exc:
            future_run_blocked = "out_of_order_future_material" in str(exc)
        ok &= check(
            "protocol-v2 future run slot refused before earlier backend call",
            future_run_blocked and not future_run_receipt.exists()
            and (v2_future_run["run_output"]
                 / "schedule-entry-1-terminal-invalid.json").exists(),
            notes)

        v2_tampered_prefix = make_v2_fixture(
            ws, "run-tampered-prefix", repo_v2, sha_v2,
            run_mode="normal", task_numbers=(1, 2))
        prefix_manifest = json.loads(
            v2_tampered_prefix["manifest_path"].read_text(encoding="utf-8"))
        removed_summary = prefix_manifest["results"].pop()
        prefix_manifest["complete"] = False
        v2_tampered_prefix["manifest_path"].write_text(
            json.dumps(prefix_manifest, indent=2) + "\n", encoding="utf-8")
        for removed_path in v2_tampered_prefix["run_output"].glob(
                f"run-{removed_summary['run_id']}*"):
            removed_path.unlink()
        retained_summary = prefix_manifest["results"][0]
        retained_record_path = v2_tampered_prefix["run_output"] / (
            f"run-{retained_summary['run_id']}.json")
        retained_record = json.loads(
            retained_record_path.read_text(encoding="utf-8"))
        retained_record["nodes"][0]["model"] = "tampered-model"
        retained_record_path.write_text(
            json.dumps(retained_record, indent=2) + "\n", encoding="utf-8")
        before_prefix_records = list(
            v2_tampered_prefix["run_output"].glob("run-*.json"))
        try:
            runner.run_schedule(
                v2_tampered_prefix["config"],
                v2_tampered_prefix["schedule"],
                {"mock-repo": str(repo_v2)},
                v2_tampered_prefix["run_output"],
                [str(task) for task in v2_tampered_prefix["tasks"]])
            tampered_prefix_blocked = False
        except runner.InfraFailure as exc:
            tampered_prefix_blocked = "runtime/accounting" in str(exc)
        ok &= check(
            "tampered completed prefix blocks the next scheduled backend",
            tampered_prefix_blocked
            and len(list(v2_tampered_prefix["run_output"].glob(
                "run-*.json"))) == len(before_prefix_records), notes)

        prefix_state_results = []
        for prefix_case in (
                "missing-artifact", "attempt-mismatch", "blocking-prior"):
            prefix_fixture = make_v2_fixture(
                ws, f"run-prefix-{prefix_case}", repo_v2, sha_v2,
                run_mode="normal", task_numbers=(1, 2))
            prefix_doc = json.loads(
                prefix_fixture["manifest_path"].read_text(encoding="utf-8"))
            removed = prefix_doc["results"].pop()
            prefix_doc["complete"] = False
            for removed_path in prefix_fixture["run_output"].glob(
                    f"run-{removed['run_id']}*"):
                removed_path.unlink()
            retained = prefix_doc["results"][0]
            retained_path = prefix_fixture["run_output"] / (
                f"run-{retained['run_id']}.json")
            retained_record = json.loads(
                retained_path.read_text(encoding="utf-8"))
            expected_fragment = None
            if prefix_case == "missing-artifact":
                (prefix_fixture["run_output"]
                 / f"run-{retained['run_id']}-anon.md").unlink()
                expected_fragment = "lacks its bound anon artifact"
            elif prefix_case == "attempt-mismatch":
                prefix_doc["results"][0]["attempts"] = 2
                expected_fragment = "final attempt differs"
            else:
                prefix_doc["results"][0]["attempts"] = 2
                retained_record["attempt"] = 2
                retained_path.write_text(
                    json.dumps(retained_record, indent=2) + "\n",
                    encoding="utf-8")
                prior = json.loads(json.dumps(retained_record))
                prior.update({
                    "run_id": "b10cb10cb10c",
                    "attempt": 1,
                    "status": "infra_failure",
                    "blocking": True,
                    "failure": "synthetic blocking infrastructure state",
                    "failure_kind": None,
                    "artifact_gate": "not_evaluated",
                    "raw_sha256": None,
                    "artifact_sha256": None,
                    "diagnostic_sha256": None,
                    "telemetry_eligible": False,
                    "telemetry_exclusion_reason":
                        "not_a_final_workflow_outcome",
                })
                (prefix_fixture["run_output"]
                 / "run-b10cb10cb10c.json").write_text(
                     json.dumps(prior, indent=2) + "\n", encoding="utf-8")
                expected_fragment = "terminally invalid"
            prefix_fixture["manifest_path"].write_text(
                json.dumps(prefix_doc, indent=2) + "\n", encoding="utf-8")
            before_bound_records = {
                path.name for path in prefix_fixture["run_output"].glob(
                    "run-*.json")
            }
            try:
                runner.run_schedule(
                    prefix_fixture["config"], prefix_fixture["schedule"],
                    {"mock-repo": str(repo_v2)},
                    prefix_fixture["run_output"],
                    [str(task) for task in prefix_fixture["tasks"]])
                prefix_blocked = False
            except runner.InfraFailure as exc:
                prefix_blocked = expected_fragment in str(exc)
            after_bound_records = {
                path.name for path in prefix_fixture["run_output"].glob(
                    "run-*.json")
            }
            prefix_state_results.append(
                prefix_blocked
                and after_bound_records == before_bound_records)
        ok &= check(
            "completed-prefix artifacts, attempt parity, and blocking "
            "history fail closed before the next backend",
            all(prefix_state_results), notes)

        v2_foreign_claim = make_v2_fixture(
            ws, "run-foreign-claim", repo_v2, sha_v2, execute_run=False)
        foreign_claim_receipt = (
            v2_foreign_claim["root"] / "unexpected-run-launch.txt")
        v2_foreign_claim["config"]["backend_cmd"].extend([
            "--prompt-receipt-file", str(foreign_claim_receipt)])
        foreign_claim_schedule = runner.make_schedule(
            v2_foreign_claim["config"],
            [str(v2_foreign_claim["task"])], 1,
            seed=runner.PILOT_V2_SCHEDULE_SEED,
            allow_nonstandard=True)
        v2_foreign_claim["schedule"].write_text(
            json.dumps(foreign_claim_schedule, indent=2) + "\n",
            encoding="utf-8")
        v2_foreign_claim["run_output"].mkdir()
        (v2_foreign_claim["run_output"] / ".run-schedule.lock").write_text(
            "", encoding="utf-8")
        (v2_foreign_claim["run_output"]
         / "schedule-entry-99.claim").write_text("{}\n", encoding="utf-8")
        try:
            runner.run_schedule(
                v2_foreign_claim["config"], v2_foreign_claim["schedule"],
                {"mock-repo": str(repo_v2)},
                v2_foreign_claim["run_output"],
                [str(v2_foreign_claim["task"])],
            )
            foreign_claim_blocked = False
        except runner.InfraFailure as exc:
            foreign_claim_blocked = "foreign_schedule_material" in str(exc)
        ok &= check(
            "unknown schedule-entry material refused before backend call",
            foreign_claim_blocked and not foreign_claim_receipt.exists(),
            notes)

        unsafe_run_lock_results = []
        for lock_kind in ("symlink", "directory", "hardlink"):
            lock_fixture = make_v2_fixture(
                ws, f"run-lock-{lock_kind}", repo_v2, sha_v2,
                execute_run=False)
            lock_fixture["run_output"].mkdir()
            lock_path = lock_fixture["run_output"] / ".run-schedule.lock"
            victim = lock_fixture["root"] / "lock-victim.txt"
            victim.write_text("must remain intact\n", encoding="utf-8")
            if lock_kind == "symlink":
                lock_path.symlink_to(victim)
            elif lock_kind == "directory":
                lock_path.mkdir()
            else:
                os.link(victim, lock_path)
            try:
                runner.run_schedule(
                    lock_fixture["config"], lock_fixture["schedule"],
                    {"mock-repo": str(repo_v2)}, lock_fixture["run_output"],
                    [str(lock_fixture["task"])])
                unsafe_lock_blocked = False
            except runner.InfraFailure:
                unsafe_lock_blocked = True
            unsafe_run_lock_results.append(
                unsafe_lock_blocked
                and victim.read_text(encoding="utf-8")
                == "must remain intact\n"
                and not list(lock_fixture["run_output"].glob("run-*")))
        ok &= check(
            "run lock refuses symlink/directory/hardlink without mutation",
            all(unsafe_run_lock_results), notes)

        missing_run_lock = make_v2_fixture(
            ws, "run-lock-missing-with-state", repo_v2, sha_v2,
            run_mode="normal")
        missing_run_lock_path = (
            missing_run_lock["run_output"] / ".run-schedule.lock")
        missing_run_lock_path.unlink()
        run_state_before = {
            path.name: path.read_bytes()
            for path in missing_run_lock["run_output"].glob("run-*.json")
        }
        try:
            runner.run_schedule(
                missing_run_lock["config"], missing_run_lock["schedule"],
                {"mock-repo": str(repo_v2)}, missing_run_lock["run_output"],
                [str(task) for task in missing_run_lock["tasks"]])
            missing_run_lock_blocked = False
        except runner.InfraFailure as exc:
            missing_run_lock_blocked = "persistent lock is missing" in str(exc)
        ok &= check(
            "missing persistent run lock with state is never recreated",
            missing_run_lock_blocked and not missing_run_lock_path.exists()
            and run_state_before == {
                path.name: path.read_bytes()
                for path in missing_run_lock["run_output"].glob("run-*.json")
            }, notes)

        wrong_seed_fixture = make_v2_fixture(
            ws, "wrong-schedule-seed", repo_v2, sha_v2,
            execute_run=False)
        try:
            runner.make_schedule(
                wrong_seed_fixture["config"],
                [str(wrong_seed_fixture["task"])], 1,
                seed=runner.PILOT_V2_SCHEDULE_SEED + 1,
                allow_nonstandard=True)
            wrong_schedule_seed_rejected = False
        except runner.InfraFailure as exc:
            wrong_schedule_seed_rejected = "registered schedule seed" in str(exc)
        ok &= check(
            "protocol-v2 rejects alternate self-consistent schedule seed",
            wrong_schedule_seed_rejected, notes)

        v2_reversed_docs = make_v2_fixture(
            ws, "reversed-docs", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto",
            task_numbers=(1, 2))
        try:
            runner.score(
                v2_reversed_docs["config"],
                list(reversed(v2_reversed_docs["docs"])),
                v2_reversed_docs["prompts"]["scorer"],
                v2_reversed_docs["root"] / "judges",
                scoring_seed=runner.PILOT_V2_SCORER_SEED,
                manifest_path=v2_reversed_docs["manifest_path"],
                score_task_paths=[
                    str(task) for task in v2_reversed_docs["tasks"]],
                task_contexts={
                    name: str(path)
                    for name, path in v2_reversed_docs["contexts"].items()
                },
                seal_manifest_path=v2_reversed_docs["seal"],
            )
            reversed_docs_blocked = False
        except runner.InfraFailure as exc:
            reversed_docs_blocked = "canonical manifest order" in str(exc)
        ok &= check(
            "protocol-v2 all-doc input order is canonical before shuffle",
            reversed_docs_blocked
            and not v2_reversed_docs["prompt_receipt"].exists()
            and not v2_reversed_docs["transport_receipt"].exists(), notes)

        v2_raw_mutation = make_v2_fixture(
            ws, "raw-mutation", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        raw_result = v2_raw_mutation["manifest"]["results"][0]
        raw_path = v2_raw_mutation["run_output"] / (
            f"run-{raw_result['run_id']}-raw.md")
        raw_path.write_bytes(raw_path.read_bytes() + b"\nmutated\n")
        try:
            score_v2_fixture(
                v2_raw_mutation, "scorer",
                v2_raw_mutation["root"] / "judges")
            raw_mutation_blocked = False
        except runner.InfraFailure as exc:
            raw_mutation_blocked = "raw run artifact digest" in str(exc)
        ok &= check(
            "raw artifact mutation blocks protocol-v2 judge prelaunch",
            raw_mutation_blocked
            and not v2_raw_mutation["prompt_receipt"].exists()
            and not v2_raw_mutation["transport_receipt"].exists(), notes)

        v2_missing_contradiction = make_v2_fixture(
            ws, "missing-doc-contradiction", repo_v2, sha_v2,
            run_mode="no-artifact", judge_mode="judge-auto")
        missing_summary = v2_missing_contradiction["manifest"]["results"][0]
        missing_run_id = missing_summary["run_id"]
        missing_record_path = v2_missing_contradiction["run_output"] / (
            f"run-{missing_run_id}.json")
        missing_record = json.loads(
            missing_record_path.read_text(encoding="utf-8"))
        contradiction_bytes = b"# impossible produced document\n"
        contradiction_sha = hashlib.sha256(contradiction_bytes).hexdigest()
        for suffix in ("raw", "anon"):
            (v2_missing_contradiction["run_output"] / (
                f"run-{missing_run_id}-{suffix}.md"
            )).write_bytes(contradiction_bytes)
        missing_record.update({
            "artifact_gate": "passed",
            "raw_sha256": contradiction_sha,
            "artifact_sha256": contradiction_sha,
            "artifact_defects": [],
        })
        missing_record_path.write_text(
            json.dumps(missing_record, indent=2) + "\n", encoding="utf-8")
        missing_manifest = json.loads(
            v2_missing_contradiction["manifest_path"].read_text(
                encoding="utf-8"))
        missing_manifest["results"][0].update({
            "artifact_gate": "passed",
            "raw_sha256": contradiction_sha,
            "artifact_sha256": contradiction_sha,
        })
        v2_missing_contradiction["manifest_path"].write_text(
            json.dumps(missing_manifest, indent=2) + "\n", encoding="utf-8")
        contradiction_doc = v2_missing_contradiction["run_output"] / (
            f"run-{missing_run_id}-anon.md")
        try:
            runner.score(
                v2_missing_contradiction["config"], [contradiction_doc],
                v2_missing_contradiction["prompts"]["scorer"],
                v2_missing_contradiction["root"] / "judges",
                scoring_seed=runner.PILOT_V2_SCORER_SEED,
                manifest_path=v2_missing_contradiction["manifest_path"],
                score_task_paths=[str(v2_missing_contradiction["task"])],
                task_contexts={
                    v2_missing_contradiction["task"].name:
                        str(v2_missing_contradiction["context"]),
                },
                seal_manifest_path=v2_missing_contradiction["seal"],
            )
            missing_contradiction_blocked = False
        except runner.InfraFailure as exc:
            missing_contradiction_blocked = "missing-document" in str(exc)
        ok &= check(
            "missing-document outcome cannot acquire produced material",
            missing_contradiction_blocked
            and not v2_missing_contradiction["prompt_receipt"].exists(),
            notes)

        v2_run_root_swap = make_v2_fixture(
            ws, "run-root-swap", repo_v2, sha_v2, execute_run=False)
        original_run_locked = runner._run_schedule_locked
        moved_run_root = v2_run_root_swap["root"] / "bound-runs-moved"
        redirected_run_root = v2_run_root_swap["root"] / "redirected-runs"

        def swap_run_root(*args, **kwargs):
            bound_root = Path(args[3])
            bound_root.rename(moved_run_root)
            redirected_run_root.mkdir()
            bound_root.symlink_to(redirected_run_root, target_is_directory=True)
            return original_run_locked(*args, **kwargs)

        runner._run_schedule_locked = swap_run_root
        try:
            try:
                runner.run_schedule(
                    v2_run_root_swap["config"],
                    v2_run_root_swap["schedule"],
                    {"mock-repo": str(repo_v2)},
                    v2_run_root_swap["run_output"],
                    [str(v2_run_root_swap["task"])])
                run_root_swap_blocked = False
            except runner.InfraFailure as exc:
                run_root_swap_blocked = "changed identity" in str(exc)
        finally:
            runner._run_schedule_locked = original_run_locked
        ok &= check(
            "run output-root swap cannot split state from its lock",
            run_root_swap_blocked
            and not list(moved_run_root.glob("run-*"))
            and not list(redirected_run_root.glob("run-*")), notes)

        v2_score_root_swap = make_v2_fixture(
            ws, "score-root-swap", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        original_score_locked = runner._score_locked
        score_root = v2_score_root_swap["root"] / "judges"
        moved_score_root = v2_score_root_swap["root"] / "judges-moved"
        redirected_score_root = v2_score_root_swap["root"] / "judges-redirected"

        def swap_score_root(*args, **kwargs):
            bound_root = Path(args[3])
            bound_root.rename(moved_score_root)
            redirected_score_root.mkdir()
            bound_root.symlink_to(
                redirected_score_root, target_is_directory=True)
            return original_score_locked(*args, **kwargs)

        runner._score_locked = swap_score_root
        try:
            try:
                score_v2_fixture(v2_score_root_swap, "scorer", score_root)
                score_root_swap_blocked = False
            except runner.InfraFailure as exc:
                score_root_swap_blocked = "changed identity" in str(exc)
        finally:
            runner._score_locked = original_score_locked
        ok &= check(
            "judge output-root swap cannot split state from its lock",
            score_root_swap_blocked
            and not v2_score_root_swap["prompt_receipt"].exists()
            and not list(redirected_score_root.glob("judge-*")), notes)

        v2_valid = make_v2_fixture(
            ws, "valid", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        v2_judge_out = v2_valid["root"] / "judges"
        v2_scorer = score_v2_fixture(
            v2_valid, "scorer", v2_judge_out)
        scorer_prompt_receipt = v2_valid["prompt_receipt"].read_text(
            encoding="utf-8").strip()
        scorer_transport_rows = [
            json.loads(line)
            for line in v2_valid["transport_receipt"].read_text(
                encoding="utf-8").splitlines()
        ]
        v2_verifier = score_v2_fixture(
            v2_valid, "verifier", v2_judge_out)
        verifier_prompt_receipt = v2_valid["prompt_receipt"].read_text(
            encoding="utf-8").strip()
        verifier_transport_rows = [
            json.loads(line)
            for line in v2_valid["transport_receipt"].read_text(
                encoding="utf-8").splitlines()
        ]
        expected_prompt_receipts = {}
        expected_composed_prompts = {}
        for judge_role in ("scorer", "verifier"):
            composed = runner.compose_v2_judge_prompt(
                v2_valid["prompts"][judge_role].read_text(encoding="utf-8"),
                v2_valid["rubric"].read_text(encoding="utf-8"),
                v2_valid["schemas"][judge_role].read_text(encoding="utf-8"),
                v2_valid["context"].read_text(encoding="utf-8"),
                v2_valid["docs"][0].read_text(encoding="utf-8"),
            )
            expected_prompt_receipts[judge_role] = hashlib.sha256(
                composed.encode("utf-8")).hexdigest()
            expected_composed_prompts[judge_role] = composed
        v2_scorer_manifest = (
            v2_judge_out / "scoring-scorer-all-docs-manifest.json")
        v2_verifier_manifest = (
            v2_judge_out / "scoring-verifier-all-docs-manifest.json")
        scorer_manifest_doc = json.loads(v2_scorer_manifest.read_text(
            encoding="utf-8"))
        verifier_manifest_doc = json.loads(v2_verifier_manifest.read_text(
            encoding="utf-8"))
        judge_private_materials = [
            v2_valid["prompts"][role].read_text(encoding="utf-8")
            for role in ("scorer", "verifier")
        ] + [
            v2_valid["rubric"].read_text(encoding="utf-8"),
            v2_valid["context"].read_text(encoding="utf-8"),
            v2_valid["docs"][0].read_text(encoding="utf-8"),
        ]
        role_transport_rows = dict(zip(
            ("scorer", "verifier"), verifier_transport_rows,
            strict=True))
        transport_schema_ok = all(
            row["argv"].count("--json-schema") == 1
            and row["argv"][row["argv"].index("--json-schema") + 1]
            == judge_contract.structured_output_schema_text(role)
            and all(
                material not in argv_part
                for material in judge_private_materials
                for argv_part in row["argv"])
            for role, row in role_transport_rows.items()
        )
        prompt_suffix_ok = all(
            prompt.endswith(judge_contract.output_contract_reminder(role))
            and prompt.count(judge_contract.output_contract_reminder(role))
            == 1
            and prompt.rfind(
                v2_valid["docs"][0].read_text(encoding="utf-8"))
            < prompt.rfind(judge_contract.output_contract_reminder(role))
            for role, prompt in expected_composed_prompts.items()
        )
        result_pin_ok = True
        for role, batch, results in (
            ("scorer", scorer_manifest_doc, v2_scorer),
            ("verifier", verifier_manifest_doc, v2_verifier),
        ):
            digest = judge_contract.structured_output_schema_sha256(role)
            result = results[0]
            result_pin_ok &= (
                batch["identity"].get("judge_output_policy")
                == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
                and batch["identity"].get(
                    "structured_output_schema_sha256") == digest
                and batch["identity"].get(
                    "final_response_contract_sha256")
                == judge_contract.final_response_contract_sha256(role)
                and result.get("judge_output_policy")
                == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
                and result.get("structured_output_schema_sha256") == digest
                and result.get("final_response_contract_sha256")
                == judge_contract.final_response_contract_sha256(role)
                and result.get("structured_output")
                == result.get("parsed_response")
                and not runner._validate_v2_judge_response_pair(
                    result["response"], result["structured_output"], role)[1]
            )
        ok &= check(
            "protocol-v2 scorer and verifier accept sealed all-docs JSON",
            len(v2_scorer) == len(v2_verifier) == 1
            and v2_scorer[0].get("role") == "scorer"
            and v2_verifier[0].get("role") == "verifier"
            and v2_scorer[0].get("axis") == "all-docs"
            and v2_verifier[0].get("axis") == "all-docs"
            and v2_scorer[0].get("protocol_version") == 2
            and v2_verifier[0].get("protocol_version") == 2
            and v2_scorer[0].get("attempt") == 1
            and v2_verifier[0].get("attempt") == 1
            and v2_scorer[0].get("parsed_response", {}).get("total") == 8
            and v2_verifier[0].get("evidence_accuracy") == 0.5
            and scorer_prompt_receipt
            == expected_prompt_receipts["scorer"]
            and verifier_prompt_receipt
            == expected_prompt_receipts["verifier"]
            and len(scorer_transport_rows) == 1
            and len(verifier_transport_rows) == 2
            and [row["prompt"] for row in verifier_transport_rows]
            == [expected_composed_prompts["scorer"],
                expected_composed_prompts["verifier"]]
            and all(row["prompt_source"] == "stdin"
                    for row in verifier_transport_rows)
            and all(
                row["prompt"] not in argv_part
                for row in verifier_transport_rows
                for argv_part in row["argv"]
            )
            and transport_schema_ok and prompt_suffix_ok and result_pin_ok
            and scorer_manifest_doc["complete"] is True
            and verifier_manifest_doc["complete"] is True,
            notes)

        # Scoring re-audits the completed run namespace before electing a
        # judge batch.  A copied terminal record is not hidden merely because
        # the manifest still points at the original final run.
        v2_foreign_run = make_v2_fixture(
            ws, "score-foreign-run", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        foreign_summary = v2_foreign_run["manifest"]["results"][0]
        foreign_source = (v2_foreign_run["run_output"]
                          / f"run-{foreign_summary['run_id']}.json")
        foreign_record = json.loads(
            foreign_source.read_text(encoding="utf-8"))
        foreign_record["run_id"] = "f0e1f0e1f0e1"
        (v2_foreign_run["run_output"]
         / "run-f0e1f0e1f0e1.json").write_text(
             json.dumps(foreign_record, indent=2) + "\n", encoding="utf-8")
        try:
            score_v2_fixture(
                v2_foreign_run, "scorer",
                v2_foreign_run["root"] / "judges")
            foreign_run_blocked = False
        except runner.InfraFailure as exc:
            foreign_run_blocked = "run slot" in str(exc)
        ok &= check(
            "foreign completed-run material blocks first judge launch",
            foreign_run_blocked
            and not v2_foreign_run["prompt_receipt"].exists(), notes)

        v2_foreign_scoring = make_v2_fixture(
            ws, "judge-foreign-scoring", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        foreign_scoring_out = v2_foreign_scoring["root"] / "judges"
        foreign_scoring_out.mkdir()
        (foreign_scoring_out
         / "scoring-scorer-primary-manifest.json").write_text(
             "{}\n", encoding="utf-8")
        try:
            score_v2_fixture(
                v2_foreign_scoring, "scorer", foreign_scoring_out)
            foreign_scoring_blocked = False
        except runner.InfraFailure as exc:
            foreign_scoring_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "foreign scoring namespace blocks first judge launch",
            foreign_scoring_blocked
            and not v2_foreign_scoring["prompt_receipt"].exists(), notes)

        v2_foreign_judge = make_v2_fixture(
            ws, "judge-foreign-id", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        foreign_judge_out = v2_foreign_judge["root"] / "judges"
        foreign_judge_out.mkdir()
        (foreign_judge_out
         / "judge-deadbeef-0-attempt-1.json").write_text(
             "{}\n", encoding="utf-8")
        try:
            score_v2_fixture(v2_foreign_judge, "scorer", foreign_judge_out)
            foreign_judge_blocked = False
        except runner.InfraFailure as exc:
            foreign_judge_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "foreign judge id blocks first judge launch",
            foreign_judge_blocked
            and not v2_foreign_judge["prompt_receipt"].exists(), notes)

        unsafe_judge_lock_results = []
        for lock_kind in ("symlink", "directory", "hardlink"):
            lock_fixture = make_v2_fixture(
                ws, f"judge-lock-{lock_kind}", repo_v2, sha_v2,
                run_mode="normal", judge_mode="judge-auto")
            lock_out = lock_fixture["root"] / "judges"
            lock_out.mkdir()
            lock_path = lock_out / ".scoring-scorer-all-docs.lock"
            victim = lock_fixture["root"] / "judge-lock-victim.txt"
            victim.write_text("must remain intact\n", encoding="utf-8")
            if lock_kind == "symlink":
                lock_path.symlink_to(victim)
            elif lock_kind == "directory":
                lock_path.mkdir()
            else:
                os.link(victim, lock_path)
            try:
                score_v2_fixture(lock_fixture, "scorer", lock_out)
                unsafe_lock_blocked = False
            except runner.InfraFailure:
                unsafe_lock_blocked = True
            unsafe_judge_lock_results.append(
                unsafe_lock_blocked
                and victim.read_text(encoding="utf-8")
                == "must remain intact\n"
                and not lock_fixture["prompt_receipt"].exists())
        ok &= check(
            "judge lock refuses symlink/directory/hardlink without mutation",
            all(unsafe_judge_lock_results), notes)

        missing_judge_lock = make_v2_fixture(
            ws, "judge-lock-missing-with-state", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        missing_judge_lock_out = missing_judge_lock["root"] / "judges"
        missing_judge_lock_out.mkdir()
        missing_judge_manifest = (
            missing_judge_lock_out
            / "scoring-scorer-all-docs-manifest.json")
        missing_judge_manifest.write_text("{}\n", encoding="utf-8")
        missing_judge_lock_path = (
            missing_judge_lock_out / ".scoring-scorer-all-docs.lock")
        try:
            score_v2_fixture(
                missing_judge_lock, "scorer", missing_judge_lock_out)
            missing_judge_lock_blocked = False
        except runner.InfraFailure as exc:
            missing_judge_lock_blocked = (
                "persistent lock is missing" in str(exc))
        ok &= check(
            "missing persistent judge lock with state is never recreated",
            missing_judge_lock_blocked
            and not missing_judge_lock_path.exists()
            and not missing_judge_lock["prompt_receipt"].exists()
            and not list(missing_judge_lock_out.glob("judge-*")), notes)

        v2_wrong_judge_seed = make_v2_fixture(
            ws, "judge-wrong-seed", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        try:
            runner.score(
                v2_wrong_judge_seed["config"],
                v2_wrong_judge_seed["docs"],
                v2_wrong_judge_seed["prompts"]["scorer"],
                v2_wrong_judge_seed["root"] / "judges",
                scoring_seed=runner.PILOT_V2_SCORER_SEED + 1,
                manifest_path=v2_wrong_judge_seed["manifest_path"],
                score_task_paths=[str(v2_wrong_judge_seed["task"])],
                task_contexts={
                    v2_wrong_judge_seed["task"].name:
                        str(v2_wrong_judge_seed["context"]),
                },
                seal_manifest_path=v2_wrong_judge_seed["seal"],
            )
            wrong_judge_seed_rejected = False
        except runner.InfraFailure as exc:
            wrong_judge_seed_rejected = "registered scoring seed" in str(exc)
        ok &= check(
            "protocol-v2 rejects alternate scorer seed before backend",
            wrong_judge_seed_rejected
            and not v2_wrong_judge_seed["prompt_receipt"].exists(), notes)

        v2_premature_verifier = make_v2_fixture(
            ws, "judge-premature-verifier", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        premature_out = v2_premature_verifier["root"] / "judges"
        premature_out.mkdir()
        (premature_out
         / "scoring-verifier-all-docs-manifest.json").write_text(
             "{}\n", encoding="utf-8")
        try:
            score_v2_fixture(
                v2_premature_verifier, "scorer", premature_out)
            premature_verifier_blocked = False
        except runner.InfraFailure as exc:
            premature_verifier_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "scorer starts only with no verifier counterpart material",
            premature_verifier_blocked
            and not v2_premature_verifier["prompt_receipt"].exists(), notes)

        v2_incomplete_counterpart = make_v2_fixture(
            ws, "judge-incomplete-counterpart", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        incomplete_out = v2_incomplete_counterpart["root"] / "judges"
        score_v2_fixture(v2_incomplete_counterpart, "scorer", incomplete_out)
        incomplete_receipt = v2_incomplete_counterpart[
            "prompt_receipt"].read_bytes()
        incomplete_manifest_path = (
            incomplete_out / "scoring-scorer-all-docs-manifest.json")
        incomplete_manifest = json.loads(
            incomplete_manifest_path.read_text(encoding="utf-8"))
        incomplete_manifest["complete"] = False
        incomplete_manifest_path.write_text(
            json.dumps(incomplete_manifest) + "\n", encoding="utf-8")
        try:
            score_v2_fixture(
                v2_incomplete_counterpart, "verifier", incomplete_out)
            incomplete_counterpart_blocked = False
        except runner.InfraFailure as exc:
            incomplete_counterpart_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "incomplete scorer counterpart blocks verifier backend",
            incomplete_counterpart_blocked
            and v2_incomplete_counterpart["prompt_receipt"].read_bytes()
            == incomplete_receipt, notes)

        v2_corrupt_counterpart = make_v2_fixture(
            ws, "judge-corrupt-counterpart", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        corrupt_counterpart_out = v2_corrupt_counterpart["root"] / "judges"
        score_v2_fixture(
            v2_corrupt_counterpart, "scorer", corrupt_counterpart_out)
        corrupt_receipt = v2_corrupt_counterpart["prompt_receipt"].read_bytes()
        corrupt_scorer_manifest = json.loads(
            (corrupt_counterpart_out
             / "scoring-scorer-all-docs-manifest.json").read_text(
                 encoding="utf-8"))
        corrupt_scorer_id = corrupt_scorer_manifest["scoring_id"]
        (corrupt_counterpart_out
         / f"judge-{corrupt_scorer_id}-0.json").write_text(
             "{}\n", encoding="utf-8")
        try:
            score_v2_fixture(
                v2_corrupt_counterpart, "verifier",
                corrupt_counterpart_out)
            corrupt_counterpart_blocked = False
        except runner.InfraFailure as exc:
            corrupt_counterpart_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "corrupt scorer counterpart blocks verifier backend",
            corrupt_counterpart_blocked
            and v2_corrupt_counterpart["prompt_receipt"].read_bytes()
            == corrupt_receipt, notes)

        v2_future_judge = make_v2_fixture(
            ws, "judge-future-slot", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-invalid-then-valid",
            task_numbers=(1, 2))
        future_judge_out = v2_future_judge["root"] / "judges"
        score_v2_fixture(v2_future_judge, "scorer", future_judge_out)
        future_judge_manifest_path = (
            future_judge_out / "scoring-scorer-all-docs-manifest.json")
        future_judge_manifest = json.loads(
            future_judge_manifest_path.read_text(encoding="utf-8"))
        future_judge_id = future_judge_manifest["scoring_id"]
        future_judge_manifest.update({"complete": False, "results": []})
        future_judge_manifest_path.write_text(
            json.dumps(future_judge_manifest) + "\n", encoding="utf-8")
        for slot_zero_path in future_judge_out.glob(
                f"judge-{future_judge_id}-0*"):
            slot_zero_path.unlink()
        judge_state_before = (
            v2_future_judge["root"] / "judge-state.txt").read_bytes()
        try:
            score_v2_fixture(v2_future_judge, "scorer", future_judge_out)
            future_judge_blocked = False
        except runner.InfraFailure as exc:
            future_judge_blocked = "terminally invalid" in str(exc)
        ok &= check(
            "future same-id judge slot blocks earlier backend launch",
            future_judge_blocked
            and (v2_future_judge["root"]
                 / "judge-state.txt").read_bytes() == judge_state_before,
            notes)

        v2_empty_judges = make_v2_fixture(
            ws, "judge-empty-population", repo_v2, sha_v2,
            run_mode="no-artifact", judge_mode="judge-auto")
        empty_judge_out = v2_empty_judges["root"] / "judges"
        empty_scorer = score_v2_fixture(
            v2_empty_judges, "scorer", empty_judge_out)
        empty_verifier = score_v2_fixture(
            v2_empty_judges, "verifier", empty_judge_out)
        ok &= check(
            "protocol-v2 empty all-doc population records two zero-call batches",
            empty_scorer == empty_verifier == []
            and json.loads((empty_judge_out
                            / "scoring-scorer-all-docs-manifest.json")
                           .read_text(encoding="utf-8"))["complete"] is True
            and json.loads((empty_judge_out
                            / "scoring-verifier-all-docs-manifest.json")
                           .read_text(encoding="utf-8"))["complete"] is True
            and not list(empty_judge_out.glob("judge-*"))
            and not v2_empty_judges["prompt_receipt"].exists(),
            notes)

        v2_empty_external = make_v2_fixture(
            ws, "judge-empty-external-drift", repo_v2, sha_v2,
            run_mode="no-artifact", judge_mode="judge-auto",
            task_numbers=(5,))
        empty_external_live = v2_empty_external["root"] / "live"
        empty_external_live.mkdir()
        changed_live_bytes = b"materially changed live reference\n"
        (empty_external_live / "reference.txt").write_bytes(
            changed_live_bytes)
        changed_live_sha = hashlib.sha256(changed_live_bytes).hexdigest()
        empty_external_report = (
            v2_empty_external["root"] / "drift-report.json")
        empty_external_report.write_text(json.dumps({
            v2_empty_external["task"].name: {"changed": {
                "snapshots/reference.txt": {
                    "observed_sha256": changed_live_sha,
                    "material": True,
                    "rationale": "material source change despite zero docs",
                },
            }},
        }), encoding="utf-8")
        empty_external_out = v2_empty_external["root"] / "judges"
        empty_external_states = []
        os.environ["MOCK_LIVE_ROOT"] = str(empty_external_live)
        try:
            for judge_role in ("scorer", "verifier"):
                external_kwargs = {
                    "scoring_seed": (
                        runner.PILOT_V2_SCORER_SEED
                        if judge_role == "scorer"
                        else runner.PILOT_V2_VERIFIER_SEED),
                    "manifest_path": v2_empty_external["manifest_path"],
                    "score_task_paths": [str(v2_empty_external["task"])],
                    "task_contexts": {
                        v2_empty_external["task"].name:
                            str(v2_empty_external["context"]),
                    },
                    "seal_manifest_path": v2_empty_external["seal"],
                    "task_snapshots": {
                        v2_empty_external["task"].name:
                            str(v2_empty_external["root"]
                                / "sealed" / "snapshots"),
                    },
                    "drift_report_path": empty_external_report,
                }
                if judge_role == "verifier":
                    external_kwargs["evidence_repos"] = {
                        "mock-repo": str(repo_v2)}
                external_results = runner.score(
                    v2_empty_external["config"], [],
                    v2_empty_external["prompts"][judge_role],
                    empty_external_out, **external_kwargs)
                role_state = json.loads((empty_external_out / (
                    f"scoring-{judge_role}-all-docs-manifest.json"
                )).read_text(encoding="utf-8"))
                empty_external_states.append((external_results, role_state))
        finally:
            os.environ.pop("MOCK_LIVE_ROOT", None)
        expected_empty_receipt = {
            "observed_sha256": {
                "snapshots/reference.txt": changed_live_sha},
            "changed": ["snapshots/reference.txt"],
            "material": True,
            "adjudications": {
                "snapshots/reference.txt": {
                    "observed_sha256": changed_live_sha,
                    "material": True,
                    "rationale": "material source change despite zero docs",
                },
            },
        }
        ok &= check(
            "zero-doc external task still records both live-drift receipts",
            all(results == [] and state["complete"] is True
                and state["identity"]["drift_decisions"]["tasks"] == {
                    v2_empty_external["task"].name: expected_empty_receipt}
                for results, state in empty_external_states)
            and not list(empty_external_out.glob("judge-*"))
            and not v2_empty_external["prompt_receipt"].exists(), notes)

        v2_background_judge = make_v2_fixture(
            ws, "judge-background-child", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-background-child")
        background_judge_rows = score_v2_fixture(
            v2_background_judge, "scorer",
            v2_background_judge["root"] / "judges")
        time.sleep(1.2)
        ok &= check(
            "successful judge parent cannot leave a background tool child",
            len(background_judge_rows) == 1
            and background_judge_rows[0].get("schema_valid") is True
            and not (v2_background_judge["root"]
                     / "judge-child-survived").exists(),
            notes)

        v2_duplicate = make_v2_fixture(
            ws, "duplicate-terminal", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        duplicate_summary = v2_duplicate["manifest"]["results"][0]
        canonical_duplicate_source = (
            v2_duplicate["run_output"]
            / f"run-{duplicate_summary['run_id']}.json")
        duplicate_record = json.loads(
            canonical_duplicate_source.read_text(encoding="utf-8"))
        duplicate_record["run_id"] = "d00bd00bd00b"
        duplicate_path = (
            v2_duplicate["run_output"] / "run-d00bd00bd00b.json")
        duplicate_path.write_text(
            json.dumps(duplicate_record, indent=2) + "\n",
            encoding="utf-8")
        duplicate_artifacts = []
        for suffix in ("raw", "anon"):
            copied = (v2_duplicate["run_output"]
                      / f"run-d00bd00bd00b-{suffix}.md")
            copied.write_bytes((v2_duplicate["run_output"] / (
                f"run-{duplicate_summary['run_id']}-{suffix}.md"
            )).read_bytes())
            duplicate_artifacts.append(copied)
        try:
            runner.run_schedule(
                v2_duplicate["config"], v2_duplicate["schedule"],
                {"mock-repo": str(repo_v2)}, v2_duplicate["run_output"],
                [str(v2_duplicate["task"])],
            )
            duplicate_terminal_first = False
        except runner.InfraFailure as exc:
            duplicate_terminal_first = (
                "duplicate_terminal_outcomes" in str(exc))
        duplicate_invalid_path = (
            v2_duplicate["run_output"]
            / "schedule-entry-0-terminal-invalid.json")
        duplicate_path.unlink()
        for duplicate_artifact in duplicate_artifacts:
            duplicate_artifact.unlink()
        try:
            runner.run_schedule(
                v2_duplicate["config"], v2_duplicate["schedule"],
                {"mock-repo": str(repo_v2)}, v2_duplicate["run_output"],
                [str(v2_duplicate["task"])],
            )
            duplicate_terminal_resume = False
        except runner.InfraFailure as exc:
            duplicate_terminal_resume = "cannot be resumed" in str(exc)
        ok &= check(
            "protocol-v2 duplicate terminal run persists invalidation",
            duplicate_terminal_first and duplicate_terminal_resume
            and duplicate_invalid_path.exists(),
            notes)

        v2_concurrent_judge = make_v2_fixture(
            ws, "judge-concurrent", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-slow-auto")
        concurrent_judge_out = v2_concurrent_judge["root"] / "judges"

        def concurrent_score():
            try:
                return score_v2_fixture(
                    v2_concurrent_judge, "scorer", concurrent_judge_out)
            except runner.InfraFailure as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_judge_outcomes = list(pool.map(
                lambda _index: concurrent_score(), range(2)))
        concurrent_judge_manifest = json.loads(
            (concurrent_judge_out
             / "scoring-scorer-all-docs-manifest.json").read_text(
                 encoding="utf-8"))
        concurrent_scoring_id = concurrent_judge_manifest["scoring_id"]
        concurrent_attempts = list(concurrent_judge_out.glob(
            f"judge-{concurrent_scoring_id}-0-attempt-*.json"))
        ok &= check(
            "protocol-v2 role/axis advisory lock blocks concurrent scoring",
            sum(isinstance(item, list)
                for item in concurrent_judge_outcomes) == 1
            and sum(isinstance(item, runner.InfraFailure)
                    for item in concurrent_judge_outcomes) == 1
            and concurrent_judge_manifest.get("complete") is True
            and len(concurrent_attempts) == 1,
            notes)

        v2_gate = make_v2_fixture(
            ws, "gate-failed", repo_v2, sha_v2,
            run_mode="bad-artifact", judge_mode="judge-auto")
        gate_summary = v2_gate["manifest"]["results"][0]
        v2_gate_out = v2_gate["root"] / "judges"
        gate_scorer = score_v2_fixture(v2_gate, "scorer", v2_gate_out)
        gate_verifier = score_v2_fixture(v2_gate, "verifier", v2_gate_out)
        ok &= check(
            "protocol-v2 gate-failed document reaches both judge roles",
            gate_summary.get("status") == "workflow_failure"
            and gate_summary.get("failure_kind") == "artifact_contract"
            and gate_summary.get("artifact_gate") == "failed"
            and len(gate_scorer) == len(gate_verifier) == 1
            and gate_scorer[0].get("role") == "scorer"
            and gate_verifier[0].get("role") == "verifier"
            and gate_scorer[0].get("axis") == "all-docs"
            and gate_verifier[0].get("axis") == "all-docs"
            and Path(gate_scorer[0]["doc"]).name.endswith("-diag.md")
            and gate_scorer[0]["doc"] == gate_verifier[0]["doc"],
            notes)

        telemetry_ok = True
        for fixture, expected_status, expected_gate, expected_kind in (
            (v2_valid, "completed", "passed", None),
            (v2_gate, "workflow_failure", "failed", "artifact_contract"),
        ):
            summary = fixture["manifest"]["results"][0]
            run_record = json.loads(
                (fixture["run_output"]
                 / f"run-{summary['run_id']}.json").read_text(
                     encoding="utf-8"))
            telemetry_ok &= (
                summary.get("protocol_version") == 2
                and run_record.get("protocol_version") == 2
                and summary.get("status") == expected_status
                and run_record.get("status") == expected_status
                and summary.get("artifact_gate") == expected_gate
                and run_record.get("artifact_gate") == expected_gate
                and summary.get("failure_kind") == expected_kind
                and run_record.get("failure_kind") == expected_kind
                and summary.get("telemetry_policy_id")
                == runner.PILOT_V2_AGGREGATION_POLICY["telemetry"]
                and run_record.get("telemetry_policy_id")
                == runner.PILOT_V2_AGGREGATION_POLICY["telemetry"]
                and summary.get("telemetry_eligible") is True
                and run_record.get("telemetry_eligible") is True
                and summary.get("telemetry_exclusion_reason") is None
                and run_record.get("telemetry_exclusion_reason") is None
                and isinstance(run_record.get("accounting", {}).get("tree"),
                               dict)
                and isinstance(run_record.get("wall_seconds"), (int, float))
            )
        ok &= check(
            "protocol-v2 final outcomes carry reconciled telemetry fields",
            telemetry_ok, notes)

        v2_retry = make_v2_fixture(
            ws, "retry", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-invalid-then-valid")
        retry_out = v2_retry["root"] / "judges"
        retry_state = v2_retry["root"] / "judge-state.txt"
        retry_results = score_v2_fixture(
            v2_retry, "scorer", retry_out)
        try:
            retry_manifest_path = (
                retry_out / "scoring-scorer-all-docs-manifest.json")
            retry_manifest = json.loads(
                retry_manifest_path.read_text(encoding="utf-8"))
            retry_id = retry_manifest["scoring_id"]
            attempt_paths = sorted(retry_out.glob(
                f"judge-{retry_id}-0-attempt-*.json"))
            attempt_records = [json.loads(path.read_text(encoding="utf-8"))
                               for path in attempt_paths]
            canonical_path = retry_out / f"judge-{retry_id}-0.json"
            canonical_record = json.loads(
                canonical_path.read_text(encoding="utf-8"))
            immutable_attempts = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in attempt_paths
            }
            retry_transport_rows = [
                json.loads(line)
                for line in v2_retry["transport_receipt"].read_text(
                    encoding="utf-8").splitlines()
            ]
            scorer_structured_digest = (
                judge_contract.structured_output_schema_sha256("scorer"))
            retry_two_ok = (
                len(retry_results) == 1
                and retry_results[0].get("attempt") == 2
                and len(attempt_records) == 2
                and attempt_records[0].get("attempt") == 1
                and attempt_records[0].get("schema_valid") is False
                and attempt_records[0].get("validation", {}).get("valid")
                is False
                and attempt_records[1].get("attempt") == 2
                and attempt_records[1].get("schema_valid") is True
                and attempt_records[1].get("validation", {}).get("valid")
                is True
                and "parsed_response" not in attempt_records[0]
                and attempt_records[1].get("structured_output")
                == attempt_records[1].get("parsed_response")
                and all(
                    record.get("judge_output_policy")
                    == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
                    and record.get("structured_output_schema_sha256")
                    == scorer_structured_digest
                    and record.get("final_response_contract_sha256")
                    == judge_contract.final_response_contract_sha256(
                        "scorer")
                    for record in attempt_records)
                and len(retry_transport_rows) == 2
                and retry_transport_rows[0]["prompt"]
                == retry_transport_rows[1]["prompt"]
                and retry_transport_rows[0]["prompt"].endswith(
                    judge_contract.output_contract_reminder("scorer"))
                and canonical_record == attempt_records[1]
                and retry_state.read_text(encoding="utf-8") == "2"
            )

            # Simulate the crash window after the valid attempt file lands
            # but before its canonical promotion and batch-manifest append.
            retry_manifest["complete"] = False
            retry_manifest["results"] = []
            retry_manifest_path.write_text(
                json.dumps(retry_manifest), encoding="utf-8")
            canonical_path.unlink()
            adopted_results = score_v2_fixture(
                v2_retry, "scorer", retry_out)
            immutable_after = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(retry_out.glob(
                    f"judge-{retry_id}-0-attempt-*.json"))
            }
            orphan_ok = (
                len(adopted_results) == 1
                and adopted_results[0] == attempt_records[1]
                and json.loads(canonical_path.read_text(
                    encoding="utf-8")) == attempt_records[1]
                and immutable_after == immutable_attempts
                and retry_state.read_text(encoding="utf-8") == "2"
            )
        finally:
            retry_state.unlink(missing_ok=True)
        ok &= check(
            "protocol-v2 invalid response retries then accepts attempt two",
            retry_two_ok, notes)
        ok &= check(
            "protocol-v2 valid orphan attempt adopted without relaunch",
            orphan_ok, notes)

        # A stream can remain well below the byte cap yet exceed the JSON
        # decoder's nesting limit. That is model/transport output, not a
        # harness crash: preserve it as an invalid attempt, consume exactly
        # one retry, and clear the pending claim after the record is durable.
        v2_deep_stream = make_v2_fixture(
            ws, "deep-json-stream", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-auto")
        deep_stream_out = v2_deep_stream["root"] / "judges"
        deep_json_line = "[" * 10000 + "0" + "]" * 10000
        deep_response = json.dumps(mock_claude.SCORER_RESPONSE)
        deep_stream_text = "\n".join((
            json.dumps({
                "type": "node", "model": "opus", "effort": "high",
                "tool_calls": 0,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }),
            deep_json_line,
            json.dumps({
                "type": "result", "subtype": "success",
                "session_id": "deep-json-attempt",
                "result": deep_response,
                "structured_output": mock_claude.SCORER_RESPONSE,
            }),
        ))
        original_capped_judge = runner.spawn_judge_session_capped
        deep_launches = 0

        def deep_first_capped_judge(*args, **kwargs):
            nonlocal deep_launches
            deep_launches += 1
            if deep_launches == 1:
                encoded = deep_stream_text.encode("utf-8")
                return (
                    deep_stream_text, len(encoded),
                    hashlib.sha256(encoded).hexdigest(), [], False,
                )
            return original_capped_judge(*args, **kwargs)

        runner.spawn_judge_session_capped = deep_first_capped_judge
        try:
            deep_results = score_v2_fixture(
                v2_deep_stream, "scorer", deep_stream_out)
        finally:
            runner.spawn_judge_session_capped = original_capped_judge
        deep_manifest = json.loads((
            deep_stream_out / "scoring-scorer-all-docs-manifest.json"
        ).read_text(encoding="utf-8"))
        deep_scoring_id = deep_manifest["scoring_id"]
        deep_attempt_paths = sorted(deep_stream_out.glob(
            f"judge-{deep_scoring_id}-0-attempt-*.json"))
        deep_attempts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in deep_attempt_paths
        ]
        deep_invalid_defects = (
            deep_attempts[0].get("validation", {}).get("defects", [])
            if len(deep_attempts) == 2 else [])
        ok &= check(
            "deep malformed judge JSON records invalid attempt then retries",
            deep_launches == 2
            and len(deep_results) == 1
            and deep_results[0].get("attempt") == 2
            and len(deep_attempts) == 2
            and deep_attempts[0].get("schema_valid") is False
            and deep_attempts[0].get("transport_invalid") is True
            and deep_attempts[0].get("raw_stream") == deep_stream_text
            and any("maximum recursion depth" in defect
                    for defect in deep_invalid_defects)
            and deep_attempts[1].get("schema_valid") is True
            and deep_manifest.get("complete") is True
            and not list(deep_stream_out.glob("*.pending"))
            and not list(deep_stream_out.glob("*-terminal-invalid.json"))
            and not list(deep_stream_out.glob("*-exhausted.json")),
            notes)

        v2_exhausted = make_v2_fixture(
            ws, "exhausted", repo_v2, sha_v2,
            run_mode="normal", judge_mode="judge-invalid")
        exhausted_out = v2_exhausted["root"] / "judges"
        try:
            score_v2_fixture(v2_exhausted, "scorer", exhausted_out)
            first_exhausted = False
        except runner.InfraFailure as exc:
            first_exhausted = "attempts exhausted" in str(exc)
        exhausted_manifest = json.loads(
            (exhausted_out
             / "scoring-scorer-all-docs-manifest.json").read_text(
                 encoding="utf-8"))
        exhausted_id = exhausted_manifest["scoring_id"]
        exhausted_attempts = sorted(exhausted_out.glob(
            f"judge-{exhausted_id}-0-attempt-*.json"))
        terminal_path = (
            exhausted_out / f"judge-{exhausted_id}-0-exhausted.json")
        terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
        exhausted_bytes = {
            path.name: path.read_bytes()
            for path in [*exhausted_attempts, terminal_path]
        }
        try:
            score_v2_fixture(v2_exhausted, "scorer", exhausted_out)
            terminal_resume = False
        except runner.InfraFailure as exc:
            terminal_resume = "already exhausted" in str(exc)
        exhausted_after = {
            path.name: path.read_bytes()
            for path in [*sorted(exhausted_out.glob(
                f"judge-{exhausted_id}-0-attempt-*.json")), terminal_path]
        }
        ok &= check(
            "protocol-v2 exhaustion is terminal after three attempts",
            first_exhausted and terminal_resume
            and len(exhausted_attempts) == 3
            and all(json.loads(path.read_text(
                encoding="utf-8"))["validation"]["valid"] is False
                    for path in exhausted_attempts)
            and terminal.get("status") == "exhausted"
            and terminal.get("max_attempts") == 3
            and terminal.get("judge_output_policy")
            == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
            and terminal.get("structured_output_schema_sha256")
            == judge_contract.structured_output_schema_sha256("scorer")
            and terminal.get("final_response_contract_sha256")
            == judge_contract.final_response_contract_sha256("scorer")
            and all(
                json.loads(path.read_text(encoding="utf-8")).get(
                    "judge_output_policy")
                == runner.PILOT_V2_JUDGE_OUTPUT_POLICY
                and json.loads(path.read_text(encoding="utf-8")).get(
                    "structured_output_schema_sha256")
                == judge_contract.structured_output_schema_sha256("scorer")
                and json.loads(path.read_text(encoding="utf-8")).get(
                    "final_response_contract_sha256")
                == judge_contract.final_response_contract_sha256("scorer")
                for path in exhausted_attempts)
            and len(terminal.get("attempt_response_sha256", [])) == 3
            and exhausted_after == exhausted_bytes
            and not list(exhausted_out.glob(
                f"judge-{exhausted_id}-0-attempt-4.*")),
            notes)

        pending_out = v2_valid["root"] / "pending-judges"
        score_v2_fixture(v2_valid, "scorer", pending_out)
        pending_manifest_path = (
            pending_out / "scoring-scorer-all-docs-manifest.json")
        pending_manifest = json.loads(
            pending_manifest_path.read_text(encoding="utf-8"))
        pending_id = pending_manifest["scoring_id"]
        pending_manifest["complete"] = False
        pending_manifest["results"] = []
        pending_manifest_path.write_text(
            json.dumps(pending_manifest), encoding="utf-8")
        (pending_out / f"judge-{pending_id}-0.json").unlink()
        (pending_out / f"judge-{pending_id}-0-attempt-1.json").unlink()
        pending_attempt = (
            pending_out / f"judge-{pending_id}-0-attempt-1.pending")
        pending_attempt.write_text("{}\n", encoding="utf-8")
        try:
            score_v2_fixture(v2_valid, "scorer", pending_out)
            v2_pending_ok = False
        except runner.InfraFailure as exc:
            v2_pending_ok = "ambiguous post-launch state" in str(exc)
        judge_invalid = (pending_out
                         / f"judge-{pending_id}-0-terminal-invalid.json")
        pending_attempt.unlink()
        try:
            score_v2_fixture(v2_valid, "scorer", pending_out)
            v2_pending_resume = False
        except runner.InfraFailure as exc:
            v2_pending_resume = "cannot be resumed" in str(exc)
        ok &= check(
            "protocol-v2 ambiguous judge attempt terminally blocks resume",
            v2_pending_ok and v2_pending_resume and judge_invalid.exists()
            and not list(pending_out.glob(
                f"judge-{pending_id}-0-attempt-*.json")),
            notes)

        corrupt_out = v2_valid["root"] / "corrupt-attempt-judges"
        score_v2_fixture(v2_valid, "scorer", corrupt_out)
        corrupt_manifest_path = (
            corrupt_out / "scoring-scorer-all-docs-manifest.json")
        corrupt_manifest = json.loads(
            corrupt_manifest_path.read_text(encoding="utf-8"))
        corrupt_id = corrupt_manifest["scoring_id"]
        corrupt_manifest.update({"complete": False, "results": []})
        corrupt_manifest_path.write_text(
            json.dumps(corrupt_manifest), encoding="utf-8")
        (corrupt_out / f"judge-{corrupt_id}-0.json").unlink()
        corrupt_attempt = (
            corrupt_out / f"judge-{corrupt_id}-0-attempt-1.json")
        corrupt_attempt_record = json.loads(
            corrupt_attempt.read_text(encoding="utf-8"))
        corrupt_attempt_record["final_response_contract_sha256"] = "e" * 64
        corrupt_attempt.write_text(
            json.dumps(corrupt_attempt_record, indent=2) + "\n",
            encoding="utf-8")
        corrupt_transport_before = v2_valid["transport_receipt"].read_bytes()
        try:
            score_v2_fixture(v2_valid, "scorer", corrupt_out)
            corrupt_attempt_blocked = False
        except runner.InfraFailure as exc:
            corrupt_attempt_blocked = "invalid_attempt_history" in str(exc)
        corrupt_transport_after = v2_valid["transport_receipt"].read_bytes()
        corrupt_marker = (
            corrupt_out / f"judge-{corrupt_id}-0-terminal-invalid.json")
        corrupt_attempt.unlink()
        try:
            score_v2_fixture(v2_valid, "scorer", corrupt_out)
            corrupt_delete_resume = False
        except runner.InfraFailure as exc:
            corrupt_delete_resume = "cannot be resumed" in str(exc)
        ok &= check(
            "tampered judge-contract digest blocks orphan adoption without relaunch",
            corrupt_attempt_blocked and corrupt_delete_resume
            and corrupt_transport_after == corrupt_transport_before
            and corrupt_marker.exists()
            and not list(corrupt_out.glob(
                f"judge-{corrupt_id}-0-attempt-*.json")),
            notes)

        extra_out = v2_valid["root"] / "extra-attempt-judges"
        score_v2_fixture(v2_valid, "scorer", extra_out)
        extra_manifest_path = (
            extra_out / "scoring-scorer-all-docs-manifest.json")
        extra_manifest = json.loads(
            extra_manifest_path.read_text(encoding="utf-8"))
        extra_id = extra_manifest["scoring_id"]
        extra_manifest["complete"] = False
        extra_manifest_path.write_text(
            json.dumps(extra_manifest), encoding="utf-8")
        extra_attempt = extra_out / f"judge-{extra_id}-0-attempt-4.json"
        extra_attempt.write_text("{}\n", encoding="utf-8")
        try:
            score_v2_fixture(v2_valid, "scorer", extra_out)
            extra_material_blocked = False
        except runner.InfraFailure as exc:
            extra_material_blocked = "terminally invalid" in str(exc)
        batch_marker = (
            extra_out / "scoring-scorer-all-docs-terminal-invalid.json")
        extra_attempt.unlink()
        try:
            score_v2_fixture(v2_valid, "scorer", extra_out)
            extra_material_resume = False
        except runner.InfraFailure as exc:
            extra_material_resume = "terminally invalid" in str(exc)
        ok &= check(
            "out-of-protocol judge material terminally invalidates batch",
            extra_material_blocked and extra_material_resume
            and batch_marker.exists(),
            notes)

        wrong_judge_material_ok = True
        for material_kind in (
                "directory-attempt", "dangling-pending",
                "dangling-sidecar", "orphan-sidecar"):
            fixture = make_v2_fixture(
                ws, f"wrong-judge-{material_kind}", repo_v2, sha_v2,
                run_mode="normal", judge_mode="judge-invalid-then-valid")
            judge_out = fixture["root"] / "judges-wrong-material"
            score_v2_fixture(fixture, "scorer", judge_out)
            judge_manifest_path = (
                judge_out / "scoring-scorer-all-docs-manifest.json")
            judge_manifest = json.loads(
                judge_manifest_path.read_text(encoding="utf-8"))
            judge_id = judge_manifest["scoring_id"]
            judge_manifest.update({"complete": False, "results": []})
            judge_manifest_path.write_text(
                json.dumps(judge_manifest), encoding="utf-8")
            (judge_out / f"judge-{judge_id}-0.json").unlink()
            for attempt_path in judge_out.glob(
                    f"judge-{judge_id}-0-attempt-*.json"):
                attempt_path.unlink()
            if material_kind == "directory-attempt":
                wrong_path = (
                    judge_out / f"judge-{judge_id}-0-attempt-1.json")
                wrong_path.mkdir()
            elif material_kind == "dangling-pending":
                wrong_path = (
                    judge_out / f"judge-{judge_id}-0-attempt-1.pending")
                wrong_path.symlink_to(
                    fixture["root"] / "missing-judge-pending")
            else:
                wrong_path = judge_out / (
                    f"judge-{judge_id}-0-attempt-1-raw-stream.txt")
                if material_kind == "dangling-sidecar":
                    wrong_path.symlink_to(
                        fixture["root"] / "missing-judge-sidecar")
                else:
                    wrong_path.write_text(
                        "orphan launch evidence\n", encoding="utf-8")
            state_path = fixture["root"] / "judge-state.txt"
            state_before = state_path.read_bytes()
            try:
                score_v2_fixture(fixture, "scorer", judge_out)
                first_block = False
            except runner.InfraFailure as exc:
                first_block = "terminally invalid" in str(exc)
            batch_invalid = (
                judge_out
                / "scoring-scorer-all-docs-terminal-invalid.json")
            slot_invalid = (
                judge_out / f"judge-{judge_id}-0-terminal-invalid.json")
            durable_marker = (
                slot_invalid if material_kind == "orphan-sidecar"
                else batch_invalid)
            if wrong_path.is_dir() and not wrong_path.is_symlink():
                wrong_path.rmdir()
            else:
                wrong_path.unlink()
            try:
                score_v2_fixture(fixture, "scorer", judge_out)
                resume_block = False
            except runner.InfraFailure as exc:
                resume_block = "terminally invalid" in str(exc)
            wrong_judge_material_ok &= (
                first_block and resume_block and durable_marker.is_file()
                and state_path.read_bytes() == state_before)
        ok &= check(
            "wrong-type/orphan judge material durably blocks before launch",
            wrong_judge_material_ok, notes)

        scorer_schema = v2_valid["schemas"]["scorer"]
        original_schema = scorer_schema.read_bytes()
        try:
            scorer_schema.write_text("{}\n", encoding="utf-8")
            try:
                score_v2_fixture(
                    v2_valid, "scorer", v2_valid["root"] / "schema-drift")
                schema_drift_ok = False
            except runner.InfraFailure as exc:
                schema_drift_ok = (
                    "response schema" in str(exc)
                    or "atomic seal package" in str(exc))
        finally:
            scorer_schema.write_bytes(original_schema)
        original_seal = v2_valid["seal"].read_bytes()
        try:
            v2_valid["seal"].write_bytes(original_seal + b"\n")
            try:
                score_v2_fixture(
                    v2_valid, "scorer", v2_valid["root"] / "seal-drift")
                v2_seal_drift_ok = False
            except runner.InfraFailure as exc:
                v2_seal_drift_ok = "seal_package_sha256" in str(exc)
        finally:
            v2_valid["seal"].write_bytes(original_seal)
        ok &= check(
            "protocol-v2 schema and package-seal drift fail closed",
            schema_drift_ok and v2_seal_drift_ok, notes)

        aggregate_fixture = make_v2_aggregation_fixture(ws, sha_v2)
        portable_tasks = [
            str(aggregate_fixture["root"] / "sealed"
                / f"holdout-v2-{index}.md")
            for index in range(1, 7)
        ]
        portable_config = json.loads(json.dumps(
            aggregate_fixture["config"]))
        portable_config["arms"]["ablation"]["schedule_tasks"] = [
            "holdout-v2-1.md", "holdout-v2-3.md",
        ]
        try:
            portable_schedule = runner.make_schedule(
                portable_config, portable_tasks, 3,
                seed=runner.PILOT_V2_SCHEDULE_SEED)
            portable_scope_ok = (
                len(portable_schedule["entries"]) == 42
                and {Path(entry["task"]).name for entry in
                     portable_schedule["entries"]
                     if entry["arm"] == "ablation"}
                == {"holdout-v2-1.md", "holdout-v2-3.md"}
            )
        except runner.InfraFailure:
            portable_scope_ok = False
        unknown_config = json.loads(json.dumps(portable_config))
        unknown_config["arms"]["ablation"]["schedule_tasks"][1] = (
            "holdout-v2-unknown.md")
        try:
            runner.make_schedule(
                unknown_config, portable_tasks, 3,
                seed=runner.PILOT_V2_SCHEDULE_SEED,
                allow_nonstandard=True)
            portable_unknown_rejected = False
        except runner.InfraFailure:
            portable_unknown_rejected = True
        duplicate_dir = aggregate_fixture["root"] / "duplicate-task-name"
        duplicate_dir.mkdir()
        duplicate_task = duplicate_dir / "holdout-v2-1.md"
        duplicate_task.write_bytes(Path(portable_tasks[0]).read_bytes())
        try:
            runner.make_schedule(
                portable_config, [*portable_tasks, str(duplicate_task)], 3,
                seed=runner.PILOT_V2_SCHEDULE_SEED,
                allow_nonstandard=True)
            portable_duplicate_rejected = False
        except runner.InfraFailure:
            portable_duplicate_rejected = True
        ok &= check(
            "portable ablation basenames resolve uniquely to canonical tasks",
            portable_scope_ok and portable_unknown_rejected
            and portable_duplicate_rejected,
            notes)
        source_seal = json.loads(
            aggregate_fixture["seal"].read_text(encoding="utf-8"))
        builder_package = aggregate_fixture["root"] / "builder-package"
        builder_package.mkdir()
        for relative in source_seal["files"]:
            source = aggregate_fixture["seal"].parent / relative
            destination = builder_package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        builder_metadata = aggregate_fixture["root"] / "builder-metadata.json"
        builder_metadata.write_text(
            json.dumps({
                key: value for key, value in source_seal.items()
                if key != "files"
            }, ensure_ascii=False, allow_nan=False, indent=2,
                sort_keys=True) + "\n",
            encoding="utf-8",
        )
        built_registration = seal_package.build_package(
            builder_package, builder_metadata)
        verified_registration = seal_package.verify_package(
            builder_package, builder_package / seal_package.MANIFEST_NAME)
        extra_package_file = builder_package / "unregistered-extra.txt"
        extra_package_file.write_text("extra\n", encoding="utf-8")
        try:
            seal_package.verify_package(
                builder_package,
                builder_package / seal_package.MANIFEST_NAME)
            extra_file_rejected = False
        except seal_package.SealError:
            extra_file_rejected = True
        extra_package_file.unlink()
        policy_package = (
            aggregate_fixture["root"] / "judge-policy-drift-package")
        policy_package.mkdir()
        for relative in source_seal["files"]:
            source = aggregate_fixture["seal"].parent / relative
            destination = policy_package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        policy_metadata_doc = {
            key: value for key, value in source_seal.items()
            if key != "files"
        }
        policy_metadata_doc["judge_output_policy"] = {
            **runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
            "result_binding": "structured-output-only",
        }
        policy_metadata = (
            aggregate_fixture["root"] / "judge-policy-drift-metadata.json")
        policy_metadata.write_text(
            json.dumps(policy_metadata_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            seal_package.build_package(policy_package, policy_metadata)
            judge_policy_drift_rejected = False
        except seal_package.SealError:
            judge_policy_drift_rejected = True
        runtime_metadata_doc = {
            key: value for key, value in source_seal.items()
            if key != "files"
        }
        runtime_metadata_doc["judge_config"] = {
            **runtime_metadata_doc["judge_config"],
            "judge_model": "self-consistent-but-unregistered",
        }
        runtime_metadata = (
            aggregate_fixture["root"] / "runtime-drift-metadata.json")
        runtime_metadata.write_text(
            json.dumps(runtime_metadata_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        try:
            seal_package.build_package(policy_package, runtime_metadata)
            runtime_registration_drift_rejected = False
        except seal_package.SealError:
            runtime_registration_drift_rejected = True
        missing_probe_package = (
            aggregate_fixture["root"] / "missing-live-probe-package")
        missing_probe_package.mkdir()
        for relative in source_seal["files"]:
            source = aggregate_fixture["seal"].parent / relative
            destination = missing_probe_package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        missing_probe_metadata_doc = {
            key: value for key, value in source_seal.items()
            if key not in {"files", "judge_live_probe"}
        }
        missing_probe_metadata = (
            aggregate_fixture["root"] / "missing-live-probe-metadata.json")
        missing_probe_metadata.write_text(
            json.dumps(missing_probe_metadata_doc, indent=2,
                       sort_keys=True) + "\n",
            encoding="utf-8")
        try:
            seal_package.build_package(
                missing_probe_package, missing_probe_metadata)
            missing_probe_binding_rejected = False
        except seal_package.SealError:
            missing_probe_binding_rejected = True
        forged_probe_binding = {
            "probe_version": pilot_registration.LIVE_PROBE_VERSION,
            "receipt_sha256": "3" * 64,
            "execution_sha256": "4" * 64,
        }
        forged_probe_metadata_doc = {
            key: value for key, value in source_seal.items()
            if key != "files"
        }
        forged_probe_metadata_doc["judge_live_probe"] = forged_probe_binding
        missing_probe_metadata.write_text(
            json.dumps(forged_probe_metadata_doc, indent=2,
                       sort_keys=True) + "\n", encoding="utf-8")
        try:
            seal_package.build_package(
                missing_probe_package, missing_probe_metadata)
            forged_probe_sealer_rejected = False
        except seal_package.SealError:
            forged_probe_sealer_rejected = True
        drifted_probe_seal_doc = json.loads(json.dumps(source_seal))
        drifted_probe_seal_doc["judge_live_probe"] = forged_probe_binding
        forged_probe_config = json.loads(json.dumps(
            aggregate_fixture["config"]))
        forged_probe_config["judge_live_probe_receipt_sha256"] = "3" * 64
        forged_probe_config["judge_live_probe_execution_sha256"] = "4" * 64
        try:
            runner.validate_sealed_judge_config(
                forged_probe_config, drifted_probe_seal_doc,
                aggregate_fixture["seal"], source_seal["files"])
            drifted_probe_binding_rejected = False
        except runner.InfraFailure as exc:
            drifted_probe_binding_rejected = "public" in str(exc)
        saved_public_probe_registration = (
            pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
            pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256,
        )
        pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_RECEIPT_SHA256)
        pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256 = (
            pilot_registration.PENDING_LIVE_PROBE_EXECUTION_SHA256)
        try:
            try:
                seal_package.build_package(
                    missing_probe_package, builder_metadata)
                pending_probe_sealer_rejected = False
            except seal_package.SealError:
                pending_probe_sealer_rejected = True
            try:
                runner.validate_sealed_judge_config(
                    aggregate_fixture["config"], source_seal,
                    aggregate_fixture["seal"], source_seal["files"])
                pending_probe_runner_rejected = False
            except runner.InfraFailure:
                pending_probe_runner_rejected = True
        finally:
            (pilot_registration.REGISTERED_LIVE_PROBE_RECEIPT_SHA256,
             pilot_registration.REGISTERED_LIVE_PROBE_EXECUTION_SHA256) = (
                saved_public_probe_registration)
        query_package = aggregate_fixture["root"] / "query-source-package"
        query_package.mkdir()
        for relative in source_seal["files"]:
            source = aggregate_fixture["seal"].parent / relative
            destination = query_package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        query_snapshot = query_package / "snapshots" / "reference.txt"
        query_snapshot.parent.mkdir(parents=True, exist_ok=True)
        query_snapshot.write_text("snapshot\n", encoding="utf-8")
        query_metadata_doc = {
            key: value for key, value in source_seal.items()
            if key != "files"
        }
        query_metadata_doc["snapshot_sources"] = {
            "snapshots/reference.txt":
                "https://example.invalid/reference?access=credential"
        }
        query_metadata = (
            aggregate_fixture["root"] / "query-source-metadata.json")
        query_metadata.write_text(
            json.dumps(query_metadata_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            seal_package.build_package(query_package, query_metadata)
            query_source_rejected = False
        except seal_package.SealError:
            query_source_rejected = True
        naming_package = (
            aggregate_fixture["root"] / "semantic-name-package")
        naming_package.mkdir()
        for relative in source_seal["files"]:
            source = aggregate_fixture["seal"].parent / relative
            destination = naming_package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        semantic_prompt = (
            naming_package / "judge-prompts" / "private-topic.md")
        semantic_prompt.write_bytes((
            naming_package / seal_package.CANONICAL_JUDGE_PROMPTS["scorer"]
        ).read_bytes())
        naming_metadata_doc = json.loads(json.dumps({
            key: value for key, value in source_seal.items()
            if key != "files"
        }))
        naming_metadata_doc["judge_prompts"]["scorer"] = (
            "judge-prompts/private-topic.md")
        naming_metadata = (
            aggregate_fixture["root"] / "semantic-name-metadata.json")
        naming_metadata.write_text(
            json.dumps(naming_metadata_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            seal_package.build_package(naming_package, naming_metadata)
            semantic_name_rejected = False
        except seal_package.SealError as exc:
            semantic_name_rejected = "registered generic" in str(exc)
        sanitized_registration = json.dumps(
            built_registration, sort_keys=True, allow_nan=False)
        ok &= check(
            "atomic seal builder enforces generic names and refuses extras/URLs",
            built_registration == verified_registration
            and built_registration.get("holdout_tasks")
            == list(seal_package.HOLDOUT_TASKS)
            and len(built_registration.get("seal_package_sha256", "")) == 64
            and extra_file_rejected
            and judge_policy_drift_rejected
            and runtime_registration_drift_rejected
            and missing_probe_binding_rejected
            and forged_probe_sealer_rejected
            and drifted_probe_binding_rejected
            and pending_probe_sealer_rejected
            and pending_probe_runner_rejected
            and query_source_rejected
            and semantic_name_rejected
            and str(aggregate_fixture["root"])
            not in sanitized_registration
            and SECRET not in sanitized_registration,
            notes)
        canonical_schedule = json.loads(
            aggregate_fixture["schedule"].read_text(encoding="utf-8"))
        permuted_schedule = runner.make_schedule(
            aggregate_fixture["config"],
            list(reversed(canonical_schedule["tasks"])), 3,
            seed=runner.PILOT_V2_SCHEDULE_SEED)
        ok &= check(
            "protocol-v2 task arguments normalize to registered base order",
            permuted_schedule == canonical_schedule
            and [Path(task).name for task in permuted_schedule["tasks"]]
            == list(seal_package.HOLDOUT_TASKS), notes)
        aggregate = aggregate_results.aggregate(
            aggregate_fixture["config_path"],
            aggregate_fixture["manifest"],
            aggregate_fixture["judge_manifests"]["scorer"],
            aggregate_fixture["judge_manifests"]["verifier"],
            aggregate_fixture["seal"],
        )
        serialized_aggregate = json.dumps(
            aggregate, sort_keys=True, allow_nan=False)
        ok &= check(
            "protocol-v2 golden aggregation covers standard 42/84 population",
            aggregate_fixture["run_count"] == 42
            and aggregate_fixture["judge_count"] == 84
            and aggregate.get("verdict") == "pass"
            and aggregate.get("holdout", {}).get("token_savings") == {
                "numerator": 1, "denominator": 4, "decimal": "0.25",
            }
            and aggregate.get("holdout", {}).get("wall_time_savings") == {
                "numerator": 1, "denominator": 5, "decimal": "0.2",
            }
            and aggregate.get("ablation", {}).get(
                "redundancy_established") is True
            and aggregate.get("ablation", {}).get("status") == "established"
            and aggregate.get("population", {}).get(
                "scheduled_final_runs") == 42
            and aggregate.get("policy_ids", {}).get("judge_output")
            == aggregate_results.JUDGE_OUTPUT_POLICY["id"]
            and aggregate.get("input_sha256", {}).get(
                "structured_output_schemas") == {
                    role: judge_contract.structured_output_schema_sha256(role)
                for role in ("scorer", "verifier")
                }
            and aggregate.get("input_sha256", {}).get(
                "final_response_contracts") == {
                    role: judge_contract.final_response_contract_sha256(role)
                    for role in ("scorer", "verifier")
                }
            and len(aggregate.get("input_sha256", {}).get(
                "judge_records", [])) == 84
            and str(aggregate_fixture["root"]) not in serialized_aggregate
            and SECRET not in serialized_aggregate
            and "Synthetic aggregate document" not in serialized_aggregate,
            notes)

        empty_aggregate_fixture = make_v2_aggregation_fixture(
            ws, sha_v2, label="empty")
        empty_output = empty_aggregate_fixture["manifest"].parent
        empty_manifest = json.loads(
            empty_aggregate_fixture["manifest"].read_text(encoding="utf-8"))
        for summary in empty_manifest["results"]:
            run_path = empty_output / f"run-{summary['run_id']}.json"
            run_record = json.loads(run_path.read_text(encoding="utf-8"))
            run_record.update({
                "status": "workflow_failure",
                "failure_kind": "missing_document",
                "artifact_gate": "not_evaluated",
                "artifact_sha256": None,
                "diagnostic_sha256": None,
                "raw_sha256": None,
            })
            run_path.write_text(
                json.dumps(run_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            summary.update({
                "status": "workflow_failure",
                "failure_kind": "missing_document",
                "artifact_gate": "not_evaluated",
                "artifact_sha256": None,
                "diagnostic_sha256": None,
                "raw_sha256": None,
            })
            (empty_output / f"run-{summary['run_id']}-raw.md").unlink()
            (empty_output / f"run-{summary['run_id']}-anon.md").unlink()
        empty_aggregate_fixture["manifest"].write_text(
            json.dumps(empty_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        for judge_path in empty_output.glob("judge-*"):
            judge_path.unlink()
        for role in ("scorer", "verifier"):
            role_path = empty_aggregate_fixture["judge_manifests"][role]
            role_manifest = json.loads(role_path.read_text(encoding="utf-8"))
            role_manifest["identity"]["docs"] = []
            role_manifest["identity"]["drift_decisions"]["inconclusive"] = []
            role_manifest["identity"]["drift_decisions"]["notes_digest"] = (
                hashlib.sha256(b"{}").hexdigest())
            role_manifest["results"] = []
            role_path.write_text(
                json.dumps(role_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        empty_aggregate = aggregate_results.aggregate(
            empty_aggregate_fixture["config_path"],
            empty_aggregate_fixture["manifest"],
            empty_aggregate_fixture["judge_manifests"]["scorer"],
            empty_aggregate_fixture["judge_manifests"]["verifier"],
            empty_aggregate_fixture["seal"],
        )
        ok &= check(
            "protocol-v2 all-no-document 42-run population aggregates",
            empty_aggregate.get("verdict") == "indeterminate"
            and empty_aggregate.get("population", {}).get(
                "scheduled_final_runs") == 42
            and empty_aggregate.get("population", {}).get(
                "scoreable_documents") == 0
            and empty_aggregate.get("population", {}).get(
                "conclusive_tasks") == 0,
            notes)
        empty_seal_doc = json.loads(
            empty_aggregate_fixture["seal"].read_text(encoding="utf-8"))
        empty_source_key = next(iter(empty_seal_doc["snapshot_sources"]))
        changed_observed = "f" * 64
        changed_task_receipt = {
            "observed_sha256": {empty_source_key: changed_observed},
            "changed": [empty_source_key],
            "material": True,
            "adjudications": {
                empty_source_key: {
                    "observed_sha256": changed_observed,
                    "material": True,
                    "rationale": "material live-source change with no docs",
                },
            },
        }
        for role in ("scorer", "verifier"):
            role_path = empty_aggregate_fixture["judge_manifests"][role]
            role_manifest = json.loads(role_path.read_text(encoding="utf-8"))
            role_manifest["identity"]["drift_decisions"]["tasks"][
                "holdout-v2-5.md"] = changed_task_receipt
            role_path.write_text(
                json.dumps(role_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        zero_doc_material_aggregate = aggregate_results.aggregate(
            empty_aggregate_fixture["config_path"],
            empty_aggregate_fixture["manifest"],
            empty_aggregate_fixture["judge_manifests"]["scorer"],
            empty_aggregate_fixture["judge_manifests"]["verifier"],
            empty_aggregate_fixture["seal"],
        )
        ok &= check(
            "zero-doc external drift still requires a fresh seal",
            zero_doc_material_aggregate.get("population", {}).get(
                "fresh_seal_required") is True
            and zero_doc_material_aggregate.get("verdict")
            == "indeterminate", notes)

        positive_node_path = aggregate_fixture["first_run_record"]
        positive_node_bytes = positive_node_path.read_bytes()
        try:
            zero_node_record = json.loads(
                positive_node_bytes.decode("utf-8"))
            zero_node_record["nodes"][0]["input_tokens"] = 0
            zero_node_record["nodes"][0]["output_tokens"] = 0
            positive_node_path.write_text(
                json.dumps(zero_node_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            try:
                aggregate_results.aggregate(
                    aggregate_fixture["config_path"],
                    aggregate_fixture["manifest"],
                    aggregate_fixture["judge_manifests"]["scorer"],
                    aggregate_fixture["judge_manifests"]["verifier"],
                    aggregate_fixture["seal"],
                )
                zero_node_rejected = False
            except runner.InfraFailure:
                zero_node_rejected = True
        finally:
            positive_node_path.write_bytes(positive_node_bytes)
        ok &= check(
            "aggregate rejects self-consistent-looking zero-token model node",
            zero_node_rejected, notes)

        alternate_seed_manifest = aggregate_fixture[
            "judge_manifests"]["scorer"]
        alternate_seed_bytes = alternate_seed_manifest.read_bytes()
        try:
            alternate_seed_doc = json.loads(
                alternate_seed_bytes.decode("utf-8"))
            alternate_seed_doc["identity"]["scoring_seed"] = (
                runner.PILOT_V2_SCORER_SEED + 1)
            alternate_seed_manifest.write_text(
                json.dumps(alternate_seed_doc, indent=2, sort_keys=True)
                + "\n", encoding="utf-8")
            try:
                aggregate_results.aggregate(
                    aggregate_fixture["config_path"],
                    aggregate_fixture["manifest"],
                    aggregate_fixture["judge_manifests"]["scorer"],
                    aggregate_fixture["judge_manifests"]["verifier"],
                    aggregate_fixture["seal"],
                )
                alternate_aggregate_seed_rejected = False
            except runner.InfraFailure as exc:
                alternate_aggregate_seed_rejected = (
                    "registered seed" in str(exc))
        finally:
            alternate_seed_manifest.write_bytes(alternate_seed_bytes)
        ok &= check(
            "aggregate rejects alternate protocol-v2 role seed",
            alternate_aggregate_seed_rejected, notes)

        def aggregate_golden():
            return aggregate_results.aggregate(
                aggregate_fixture["config_path"],
                aggregate_fixture["manifest"],
                aggregate_fixture["judge_manifests"]["scorer"],
                aggregate_fixture["judge_manifests"]["verifier"],
                aggregate_fixture["seal"],
            )

        aggregate_output = aggregate_fixture["manifest"].parent
        source_run = aggregate_fixture["first_run_record"]
        source_run_doc = json.loads(source_run.read_text(encoding="utf-8"))

        duplicate_run_path = aggregate_output / "run-eeeeeeeeeeee.json"
        duplicate_run = dict(source_run_doc)
        duplicate_run["run_id"] = "eeeeeeeeeeee"
        duplicate_run_path.write_text(
            json.dumps(duplicate_run, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            aggregate_golden()
            duplicate_terminal_rejected = False
        except runner.InfraFailure:
            duplicate_terminal_rejected = True
        finally:
            duplicate_run_path.unlink()

        foreign_run_path = aggregate_output / "run-ffffffffffff.json"
        foreign_run = dict(source_run_doc)
        foreign_run.update({
            "run_id": "ffffffffffff",
            "schedule_digest": "0" * 64,
        })
        foreign_run_path.write_text(
            json.dumps(foreign_run, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            aggregate_golden()
            foreign_run_rejected = False
        except runner.InfraFailure:
            foreign_run_rejected = True
        finally:
            foreign_run_path.unlink()

        claim_path = aggregate_output / "schedule-entry-0.claim"
        claim_path.write_text("{}\n", encoding="utf-8")
        try:
            aggregate_golden()
            aggregate_claim_rejected = False
        except runner.InfraFailure:
            aggregate_claim_rejected = True
        finally:
            claim_path.unlink()
        terminal_marker_path = (
            aggregate_output / "schedule-entry-0-terminal-invalid.json")
        terminal_marker_path.write_text("{}\n", encoding="utf-8")
        try:
            aggregate_golden()
            aggregate_terminal_marker_rejected = False
        except runner.InfraFailure:
            aggregate_terminal_marker_rejected = True
        finally:
            terminal_marker_path.unlink()
        ok &= check(
            "protocol-v2 aggregation audits exact run-directory material",
            duplicate_terminal_rejected and foreign_run_rejected
            and aggregate_claim_rejected
            and aggregate_terminal_marker_rejected,
            notes)

        orphan_artifact_names = (
            "run-cafebabecafe-raw.md",
            "run-cafebabecafe-anon.md",
            "run-cafebabecafe-diag.md",
            "run-cafebabecafe-extra-1.md",
            f"run-{source_run_doc['run_id']}-extra-1.md",
            f"run-{source_run_doc['run_id']}-diag.md",
        )
        orphan_artifact_rejections = []
        for artifact_name in orphan_artifact_names:
            artifact_path = aggregate_output / artifact_name
            artifact_path.write_text(
                "# Residual observed artifact\n", encoding="utf-8")
            try:
                aggregate_golden()
                orphan_artifact_rejections.append(False)
            except runner.InfraFailure:
                orphan_artifact_rejections.append(True)
            finally:
                artifact_path.unlink()

        source_raw_path = aggregate_output / (
            f"run-{source_run_doc['run_id']}-raw.md")
        source_raw_bytes = source_raw_path.read_bytes()
        source_raw_path.unlink()
        try:
            aggregate_golden()
            missing_raw_rejected = False
        except runner.InfraFailure:
            missing_raw_rejected = True
        finally:
            source_raw_path.write_bytes(source_raw_bytes)
        ok &= check(
            "protocol-v2 aggregation allowlists exact run artifacts",
            all(orphan_artifact_rejections)
            and len(orphan_artifact_rejections) == len(orphan_artifact_names)
            and missing_raw_rejected,
            notes)

        retry_manifest_path = aggregate_fixture["manifest"]
        retry_manifest_bytes = retry_manifest_path.read_bytes()
        retry_final_bytes = source_run.read_bytes()
        retry_prior_path = aggregate_output / "run-dddddddddddd.json"
        try:
            retry_manifest_doc = json.loads(
                retry_manifest_bytes.decode("utf-8"))
            retry_manifest_doc["results"][0]["attempts"] = 2
            retry_manifest_path.write_text(
                json.dumps(retry_manifest_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            retry_final = json.loads(retry_final_bytes.decode("utf-8"))
            retry_final["attempt"] = 2
            source_run.write_text(
                json.dumps(retry_final, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            retry_prior = dict(retry_final)
            retry_prior.update({
                "run_id": "dddddddddddd",
                "attempt": 1,
                "status": "infra_failure",
                "failure_kind": None,
                "artifact_gate": "not_evaluated",
                "artifact_sha256": None,
                "diagnostic_sha256": None,
                "raw_sha256": None,
                "telemetry_eligible": False,
                "telemetry_exclusion_reason": "not_a_final_workflow_outcome",
            })
            retry_prior_path.write_text(
                json.dumps(retry_prior, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            contiguous_retry_accepted = (
                aggregate_golden().get("verdict") == "pass")
            retry_prior_path.unlink()
            try:
                aggregate_golden()
                missing_retry_rejected = False
            except runner.InfraFailure:
                missing_retry_rejected = True
        finally:
            retry_prior_path.unlink(missing_ok=True)
            retry_manifest_path.write_bytes(retry_manifest_bytes)
            source_run.write_bytes(retry_final_bytes)
        ok &= check(
            "protocol-v2 aggregation requires contiguous infra retry history",
            contiguous_retry_accepted and missing_retry_rejected,
            notes)

        seeded_manifest_path = aggregate_fixture["judge_manifests"]["scorer"]
        seeded_manifest_bytes = seeded_manifest_path.read_bytes()
        try:
            seeded_manifest = json.loads(
                seeded_manifest_bytes.decode("utf-8"))
            seeded_docs = seeded_manifest["identity"]["docs"]
            seeded_docs[0], seeded_docs[1] = seeded_docs[1], seeded_docs[0]
            seeded_manifest_path.write_text(
                json.dumps(seeded_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                aggregate_golden()
                seeded_mapping_rejected = False
            except runner.InfraFailure:
                seeded_mapping_rejected = True
        finally:
            seeded_manifest_path.write_bytes(seeded_manifest_bytes)
        ok &= check(
            "protocol-v2 aggregation recomputes seeded judge presentation",
            seeded_mapping_rejected, notes)

        ritual_manifest = json.loads(
            aggregate_fixture["manifest"].read_text(encoding="utf-8"))
        ritual_summary = next(
            item for item in ritual_manifest["results"]
            if item["arm"] == "candidate")
        ritual_path = aggregate_output / (
            f"run-{ritual_summary['run_id']}.json")
        ritual_bytes = ritual_path.read_bytes()
        try:
            ritual_record = json.loads(ritual_bytes.decode("utf-8"))
            statement_stops = [
                runner.classify_stop(text, answered=True)
                for text in (
                    "Hello.",
                    "Please provide the query.",
                    "I need confirmation before I proceed.",
                )
            ]
            ritual_record["interventions"] = len(statement_stops)
            ritual_record["interventions_log"] = statement_stops
            ritual_path.write_text(
                json.dumps(ritual_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            ritual_aggregate = aggregate_golden()
            statement_ritual_stops_counted = (
                ritual_aggregate.get("verdict") == "fail"
                and ritual_aggregate.get("gates", {}).get(
                    "ritual_stops", {}).get("count") == 3
            )
        finally:
            ritual_path.write_bytes(ritual_bytes)
        ok &= check(
            "protocol-v2 ritual gate counts statement-shaped stops",
            statement_ritual_stops_counted, notes)

        baseline_manifest_path = aggregate_fixture["manifest"]
        baseline_manifest_bytes = baseline_manifest_path.read_bytes()
        baseline_manifest = json.loads(
            baseline_manifest_bytes.decode("utf-8"))
        baseline_summary = next(
            item for item in baseline_manifest["results"]
            if item["arm"] == "baseline")
        baseline_path = aggregate_output / (
            f"run-{baseline_summary['run_id']}.json")
        baseline_bytes = baseline_path.read_bytes()
        try:
            baseline_record = json.loads(baseline_bytes.decode("utf-8"))
            baseline_record.update({
                "status": "workflow_failure",
                "failure_kind": "timeout",
            })
            baseline_path.write_text(
                json.dumps(baseline_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            baseline_summary.update({
                "status": "workflow_failure",
                "failure_kind": "timeout",
            })
            baseline_manifest_path.write_text(
                json.dumps(baseline_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            baseline_aggregate = aggregate_golden()
            baseline_task_name = Path(baseline_record["task"]).name
            produced_timeout_excluded = (
                baseline_aggregate.get("population", {}).get(
                    "scoreable_documents") == 42
                and baseline_aggregate.get("population", {}).get(
                    "conclusive_tasks") == 5
                and baseline_aggregate.get("population", {}).get(
                    "excluded_tasks", {}).get(baseline_task_name)
                == "baseline_no_document"
            )
        finally:
            baseline_manifest_path.write_bytes(baseline_manifest_bytes)
            baseline_path.write_bytes(baseline_bytes)
        ok &= check(
            "protocol-v2 baseline terminal failure excludes produced-doc task",
            produced_timeout_excluded, notes)

        protected_output_ok = True
        aggregate_cli_args = [
            "--config", str(aggregate_fixture["config_path"]),
            "--manifest", str(aggregate_fixture["manifest"]),
            "--scorer-manifest", str(
                aggregate_fixture["judge_manifests"]["scorer"]),
            "--verifier-manifest", str(
                aggregate_fixture["judge_manifests"]["verifier"]),
            "--seal-manifest", str(aggregate_fixture["seal"]),
        ]
        for protected_path in (
                aggregate_fixture["first_run_record"],
                aggregate_fixture["seal"]):
            before = protected_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                return_code = aggregate_results.main([
                    *aggregate_cli_args, "--output", str(protected_path)])
            protected_output_ok &= (
                return_code == 2 and protected_path.read_bytes() == before)
        ok &= check(
            "protocol-v2 aggregate output cannot overwrite input material",
            protected_output_ok, notes)

        foreign_judge = (
            aggregate_fixture["manifest"].parent
            / "judge-deadbeef-0.json")
        foreign_judge.write_text("{}\n", encoding="utf-8")
        try:
            aggregate_results.aggregate(
                aggregate_fixture["config_path"],
                aggregate_fixture["manifest"],
                aggregate_fixture["judge_manifests"]["scorer"],
                aggregate_fixture["judge_manifests"]["verifier"],
                aggregate_fixture["seal"],
            )
            foreign_judge_rejected = False
        except runner.InfraFailure as exc:
            foreign_judge_rejected = "unregistered scoring batch" in str(exc)
        finally:
            foreign_judge.unlink()
        ok &= check(
            "protocol-v2 aggregation rejects foreign judge batch material",
            foreign_judge_rejected, notes)

        aggregate_scorer_path = aggregate_fixture[
            "judge_manifests"]["scorer"]
        aggregate_scorer_bytes = aggregate_scorer_path.read_bytes()
        aggregate_seal_doc = json.loads(
            aggregate_fixture["seal"].read_text(encoding="utf-8"))
        sealed_snapshot_key = next(iter(
            aggregate_seal_doc["snapshot_sources"]))

        def forged_drift_rejected(task_name, drift, expected_text):
            manifest_doc = json.loads(
                aggregate_scorer_bytes.decode("utf-8"))
            result = next(
                row for row in manifest_doc["results"]
                if Path(row["task"]).name == task_name)
            slot = result["presentation_index"]
            scoring_id = manifest_doc["scoring_id"]
            canonical_path = aggregate_scorer_path.parent / (
                f"judge-{scoring_id}-{slot}.json")
            canonical_bytes = canonical_path.read_bytes()
            result.update({
                "inconclusive": True,
                "schema_valid": False,
                "parsed_response": None,
                "source_drift": drift,
            })
            canonical_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            aggregate_scorer_path.write_text(
                json.dumps(manifest_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            try:
                aggregate_golden()
                return False
            except runner.InfraFailure as exc:
                return expected_text in str(exc)
            finally:
                canonical_path.write_bytes(canonical_bytes)
                aggregate_scorer_path.write_bytes(aggregate_scorer_bytes)

        valid_drift_shape = {
            "changed": [sealed_snapshot_key],
            "material": True,
            "adjudications": {
                sealed_snapshot_key: {
                    "observed_sha256": "f" * 64,
                    "material": True,
                    "rationale": "synthetic changed authoritative bytes",
                },
            },
        }
        nonexternal_drift_rejected = forged_drift_rejected(
            "holdout-v2-1.md", valid_drift_shape,
            "task-level live-byte receipt")
        malformed_drift = json.loads(json.dumps(valid_drift_shape))
        malformed_drift["unexpected"] = True
        malformed_aggregate_drift_rejected = forged_drift_rejected(
            "holdout-v2-5.md", malformed_drift,
            "task-level live-byte receipt")
        ok &= check(
            "protocol-v2 aggregate rejects forged/noncanonical drift",
            nonexternal_drift_rejected
            and malformed_aggregate_drift_rejected,
            notes)

        scorer_batch = json.loads(
            aggregate_fixture["judge_manifests"]["scorer"].read_text(
                encoding="utf-8"))
        scorer_batch_id = scorer_batch["scoring_id"]
        same_batch_residue_names = (
            f"judge-{scorer_batch_id}-0-attempt-4.json",
            f"judge-{scorer_batch_id}-42.json",
            f"judge-{scorer_batch_id}-0-exhausted.json",
            f"judge-{scorer_batch_id}-0-terminal-invalid.json",
            f"judge-{scorer_batch_id}-0-attempt-2.pending",
            f"judge-{scorer_batch_id}-0-attempt-1-raw-stream.txt",
        )
        same_batch_residue_rejections = []
        for residue_name in same_batch_residue_names:
            residue_path = aggregate_output / residue_name
            residue_path.write_text("{}\n", encoding="utf-8")
            try:
                aggregate_golden()
                same_batch_residue_rejections.append(False)
            except runner.InfraFailure:
                same_batch_residue_rejections.append(True)
            finally:
                residue_path.unlink()
        ok &= check(
            "protocol-v2 aggregation rejects same-batch judge residue",
            all(same_batch_residue_rejections)
            and len(same_batch_residue_rejections)
            == len(same_batch_residue_names),
            notes)

        aggregate_task5 = (
            aggregate_fixture["root"] / "sealed" / "holdout-v2-5.md")
        aggregate_task5_bytes = aggregate_task5.read_bytes()
        try:
            aggregate_task5.write_text(
                aggregate_task5_bytes.decode("utf-8").replace(
                    "external-snapshots: true\n", ""),
                encoding="utf-8")
            aggregate_tasks = [
                str(aggregate_fixture["root"] / "sealed"
                    / f"holdout-v2-{number}.md")
                for number in range(1, 7)
            ]
            try:
                runner.make_schedule(
                    aggregate_fixture["config"], aggregate_tasks, 3,
                    seed=runner.PILOT_V2_SCHEDULE_SEED)
                external_flag_rejected = False
            except runner.InfraFailure as exc:
                external_flag_rejected = "external-snapshots" in str(exc)
        finally:
            aggregate_task5.write_bytes(aggregate_task5_bytes)
        ok &= check(
            "protocol-v2 archetype 5 cannot bypass snapshot drift gate",
            external_flag_rejected, notes)

        scorer_manifest_path = aggregate_fixture["judge_manifests"]["scorer"]
        scorer_manifest_bytes = scorer_manifest_path.read_bytes()
        scorer_manifest_doc = json.loads(scorer_manifest_bytes.decode("utf-8"))
        scorer_id = scorer_manifest_doc["scoring_id"]
        scorer_canonical_path = scorer_manifest_path.parent / (
            f"judge-{scorer_id}-0.json")
        scorer_attempt_path = scorer_manifest_path.parent / (
            f"judge-{scorer_id}-0-attempt-1.json")
        scorer_canonical_bytes = scorer_canonical_path.read_bytes()
        scorer_attempt_bytes = scorer_attempt_path.read_bytes()
        try:
            tampered_result = dict(scorer_manifest_doc["results"][0])
            tampered_result["profile_settings"] = {}
            scorer_manifest_doc["results"][0] = tampered_result
            scorer_manifest_path.write_text(
                json.dumps(scorer_manifest_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tampered_bytes = (
                json.dumps(tampered_result, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            scorer_canonical_path.write_bytes(tampered_bytes)
            scorer_attempt_path.write_bytes(tampered_bytes)
            try:
                aggregate_results.aggregate(
                    aggregate_fixture["config_path"],
                    aggregate_fixture["manifest"], scorer_manifest_path,
                    aggregate_fixture["judge_manifests"]["verifier"],
                    aggregate_fixture["seal"],
                )
                judge_isolation_drift_ok = False
            except runner.InfraFailure:
                judge_isolation_drift_ok = True
        finally:
            scorer_manifest_path.write_bytes(scorer_manifest_bytes)
            scorer_canonical_path.write_bytes(scorer_canonical_bytes)
            scorer_attempt_path.write_bytes(scorer_attempt_bytes)
        ok &= check(
            "protocol-v2 aggregation rejects judge isolation-settings drift",
            judge_isolation_drift_ok, notes)

        independent_output_pin_rejections = []
        for field, forged_value in (
            ("judge_output_policy", {
                **runner.PILOT_V2_JUDGE_OUTPUT_POLICY,
                "result_binding": "forged-but-self-consistent",
            }),
            ("structured_output_schema_sha256", "f" * 64),
            ("final_response_contract_sha256", "e" * 64),
        ):
            forged_manifest = json.loads(
                scorer_manifest_bytes.decode("utf-8"))
            forged_result = dict(forged_manifest["results"][0])
            forged_manifest["identity"][field] = forged_value
            forged_result[field] = forged_value
            forged_manifest["results"][0] = forged_result
            forged_result_bytes = (
                json.dumps(forged_result, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            scorer_manifest_path.write_text(
                json.dumps(
                    forged_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            scorer_canonical_path.write_bytes(forged_result_bytes)
            scorer_attempt_path.write_bytes(forged_result_bytes)
            try:
                aggregate_results.aggregate(
                    aggregate_fixture["config_path"],
                    aggregate_fixture["manifest"], scorer_manifest_path,
                    aggregate_fixture["judge_manifests"]["verifier"],
                    aggregate_fixture["seal"],
                )
                independent_output_pin_rejections.append(False)
            except runner.InfraFailure:
                independent_output_pin_rejections.append(True)
            finally:
                scorer_manifest_path.write_bytes(scorer_manifest_bytes)
                scorer_canonical_path.write_bytes(scorer_canonical_bytes)
                scorer_attempt_path.write_bytes(scorer_attempt_bytes)
        ok &= check(
            "aggregation independently rejects self-consistent judge-output pin drift",
            all(independent_output_pin_rejections)
            and len(independent_output_pin_rejections) == 3,
            notes)

        scorer_manifest = json.loads(
            aggregate_fixture["judge_manifests"]["scorer"].read_text(
                encoding="utf-8"))
        incomplete_manifest = dict(scorer_manifest)
        incomplete_manifest["results"] = scorer_manifest["results"][:-1]
        incomplete_path = (
            aggregate_fixture["judge_manifests"]["scorer"].parent
            / "scoring-scorer-incomplete-manifest.json")
        incomplete_path.write_text(
            json.dumps(incomplete_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        try:
            aggregate_results.aggregate(
                aggregate_fixture["config_path"],
                aggregate_fixture["manifest"], incomplete_path,
                aggregate_fixture["judge_manifests"]["verifier"],
                aggregate_fixture["seal"],
            )
            incomplete_aggregate_ok = False
        except runner.InfraFailure:
            incomplete_aggregate_ok = True
        ok &= check(
            "protocol-v2 aggregation rejects incomplete judge population",
            incomplete_aggregate_ok, notes)

        wrong_config = dict(aggregate_fixture["config"])
        wrong_config["protocol_version"] = 1
        wrong_config_path = aggregate_fixture["root"] / "wrong-protocol.json"
        wrong_config_path.write_text(
            json.dumps(wrong_config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        try:
            aggregate_results.aggregate(
                wrong_config_path, aggregate_fixture["manifest"],
                aggregate_fixture["judge_manifests"]["scorer"],
                aggregate_fixture["judge_manifests"]["verifier"],
                aggregate_fixture["seal"],
            )
            wrong_protocol_aggregate_ok = False
        except runner.InfraFailure:
            wrong_protocol_aggregate_ok = True

        run_record_path = aggregate_fixture["first_run_record"]
        original_run_record = run_record_path.read_bytes()
        try:
            mixed_record = json.loads(original_run_record.decode("utf-8"))
            mixed_record["telemetry_policy_id"] = "mixed-policy"
            run_record_path.write_text(
                json.dumps(mixed_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            try:
                aggregate_results.aggregate(
                    aggregate_fixture["config_path"],
                    aggregate_fixture["manifest"],
                    aggregate_fixture["judge_manifests"]["scorer"],
                    aggregate_fixture["judge_manifests"]["verifier"],
                    aggregate_fixture["seal"],
                )
                mixed_telemetry_aggregate_ok = False
            except runner.InfraFailure:
                mixed_telemetry_aggregate_ok = True
        finally:
            run_record_path.write_bytes(original_run_record)
        ok &= check(
            "protocol-v2 aggregation rejects mixed protocol and telemetry",
            wrong_protocol_aggregate_ok and mixed_telemetry_aggregate_ok,
            notes)

    width = max(len(name) for name, _, _ in notes)
    for name, status, detail in notes:
        suffix = f"  ({detail})" if detail else ""
        print(f"preflight: {name.ljust(width)}  {status}{suffix}")
    print(f"preflight {'OK' if ok else 'FAILED'}: "
          f"{sum(1 for _, s, _ in notes if s == 'PASS')}/{len(notes)} capabilities")
    return 0 if ok else 1


def run_preflight():
    production = _registration_state()
    registration_isolation_ok = _registration_isolation_self_test()
    if _registration_state() != production:
        print("preflight FAILED: isolation self-test changed registration")
        return 1
    with isolated_synthetic_registration():
        result = _run_preflight(registration_isolation_ok)
    if _registration_state() != production:
        print("preflight FAILED: production registration was not restored")
        return 1
    return result


if __name__ == "__main__":
    sys.exit(run_preflight())
