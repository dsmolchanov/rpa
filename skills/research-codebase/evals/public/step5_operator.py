#!/usr/bin/env python3
"""Protocol-v2 operator driver for the pilot's fresh sealed round.

Runs on the operator host that holds the sealed package and the target
clones. Every phase is FAIL-CLOSED: a drifted configuration, a rebuilt
installation, a wrong CLI version, a failing sandbox, or an unexpected
task set stops the experiment before any scored run, instead of
producing results that cannot be trusted.

The registered values below come from the pilot plan's freeze record
(`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`)
and are compared against the operator's config — this driver is the
mechanical restatement of that record, not a new decision.

If the registered seal digest is ever reset to the conspicuous all-zero
sentinel, this driver FAILS CLOSED on every config. It never emits the
historical primary/diagnostic scoring commands.

PROTOCOL NOTE: this driver hashes the sealed package and parses only the
holdout frontmatter needed to validate target repo/commit pins. It never
prints sealed prompts or ground truth into the operator's context.

Phases (default: through `runs`; `next` is an explicit judge handoff):

  gates     platform, backend CLI version pin, sandbox validation
            (macOS: the mandatory `macos_sandbox_check.py`), synthetic
            harness preflight
  installs  rebuild the three arm installations from the pinned trees
            and verify their hashes against the registered ones AND
            against the config's arm registrations
  seal      verify the seal manifest against the registered package
            SHA-256 and the six registered holdout task basenames
  real-preflight
            run all three arms sequentially on the registered non-holdout
            throwaway task and persist a record-verified receipt
  schedule  write the pre-registered randomized schedule (3 replicates
            per arm/task cell, recorded seed)
  runs      execute the schedule (resumable: re-run to continue)
  next      derive the one immutable all-document population and print
            exactly two judge commands plus deterministic aggregation.
            Every produced document stays in manifest order: gate-passed
            `-anon` and gate-failed `-diag`, including workflow failures;
            `artifact_gate: not_evaluated` contributes no document. An
            empty population still emits both manifest-producing commands.

Usage:

  step5_operator.py --config CONFIG.json --rpa-clone /path/to/rpa \\
      --repos rpa=/path/to/rpa livekit-voice-agent=/path/... \\
      --tasks /sealed/holdout-v2-1.md ... /sealed/holdout-v2-6.md \\
      --seed 20260801 --out /private-eval-workspace/holdout-runs \\
      --scorer-seed 20260802 --verifier-seed 20260803 \\
      --drift-report /private-eval-workspace/source-drift-v2.json \\
      --real-preflight-task /path/to/throwaway-task.md \\
      [--newer <sha newer than the frozen candidate>] \\
      [--phases gates,installs,seal,real-preflight,schedule,runs,next]
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shlex
import stat
import subprocess
import time
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402 — colocated harness module
import seal_package  # noqa: E402 — colocated atomic-seal verifier

# ---------------------------------------------------------------- #
# Registered values (pilot plan, candidate-freeze record 2026-07-27)
# ---------------------------------------------------------------- #
FROZEN_CANDIDATE_SHA = "b731f06cdff5f38c0fa4c5aa64f93277d69e741d"
REGISTERED_INSTALL_SHA256 = {
    "baseline":
        "2762bf04e9ea82fec520906a0db0382eadff5c99cada5b44ba2f1c49a3e7b28c",
    "candidate":
        "5638b81633610a68192cc5d03dba4d1022175aa1980b27a209b3114d4c4d126c",
    "ablation":
        "a1d44b131ebd5d858756280454b9f7f33cb79a4f13d034b2004d5993b21e9b57",
}
# Resetting the registration to this conspicuous sentinel makes an
# unregistered execution impossible to mistake for a real round.
PENDING_SEAL_PACKAGE_SHA256 = "0" * 64
REGISTERED_SEAL_PACKAGE_SHA256 = PENDING_SEAL_PACKAGE_SHA256
REGISTERED_HOLDOUT_TASKS = tuple(
    f"holdout-v2-{i}.md" for i in range(1, 7))
REGISTERED_ABLATION_TASKS = (
    REGISTERED_HOLDOUT_TASKS[0], REGISTERED_HOLDOUT_TASKS[2])
REGISTERED_MODEL = "claude-opus-5"
REGISTERED_EFFORT = "high"
REGISTERED_ENTRYPOINT = "/rpa:research_codebase"
REGISTERED_BACKEND_VERSION = "2.1.220 (Claude Code)"
REGISTERED_BACKEND_CMD = [
    "claude", "--model", "claude-opus-5", "--effort", "{effort}",
    "--plugin-dir", "{installation}", "--permission-mode",
    "acceptEdits", "--verbose",
]
REGISTERED_BACKEND_VERSION_CMD = ["claude", "--version"]
REGISTERED_JUDGE_BACKEND_CMD = [
    "claude", "--model", "claude-opus-5", "--effort", "{effort}",
]
REGISTERED_JUDGE_MODEL = "claude-opus-5"
REGISTERED_JUDGE_EFFORT = "high"
REGISTERED_DRIFT_FETCH_CMD = [
    "curl", "-q", "-fsSL", "--config", "-", "-o", "{dest}",
]
REGISTERED_ABORT_EXIT_CODES = []
# The wrapper invocation is compared as a COMPLETE shape: a lookalike
# such as `["env", "TAG=ns_sandbox.py", ...]` would satisfy a substring
# test and the runner's placeholder guard while launching the backend
# with no confinement at all.
REGISTERED_SANDBOX_TAIL = ["--confine-to", "{workdir}", "--profile",
                           "{profile}", "--"]
PLATFORM_WRAPPER = {"darwin": "macos_sandbox.py"}
DEFAULT_WRAPPER = "ns_sandbox.py"
REGISTERED_TIMEOUT_SECONDS = 3600
REGISTERED_MAX_INFRA_RETRIES = 2
REGISTERED_REPLICATES = 3
REGISTERED_SCHEDULE_SEED = runner.PILOT_V2_SCHEDULE_SEED
REGISTERED_SCORER_SEED = runner.PILOT_V2_SCORER_SEED
REGISTERED_VERIFIER_SEED = runner.PILOT_V2_VERIFIER_SEED
REGISTERED_PROTOCOL_VERSION = 2
REGISTERED_MAX_JUDGE_ATTEMPTS = 3
REGISTERED_ENVIRONMENT_POLICY_ID = (
    "claude-cli-minimal-env-v2-pyyaml-6.0.2")
REGISTERED_OPERATOR_IMAGE_SHA256 = (
    "sha256:bbe9dbf152c933f4c3a69eae0809983cf698253a7a067fd6b73180ecc85c4975")
REGISTERED_ARTIFACT_PARSER = "pyyaml"
REGISTERED_ARTIFACT_PARSER_VERSION = "6.0.2"
OPERATOR_IMAGE_ENV = "RPA_OPERATOR_IMAGE_SHA256"
REGISTERED_JUDGE_RETRY_POLICY = {
    "max_attempts": REGISTERED_MAX_JUDGE_ATTEMPTS,
    "fresh_session_each_attempt": True,
    "repair": "none",
}
REGISTERED_AGGREGATION_POLICY = {
    "id": "pilot-v2-all-docs-v1",
    "telemetry": "all-final-scheduled-workflow-outcomes-v1",
    "critical": "candidate-absolute-zero-v1",
}

PHASES = (
    "gates", "installs", "seal", "real-preflight", "schedule", "runs",
    "next")
DEFAULT_PHASES = (
    "gates", "installs", "seal", "real-preflight", "schedule", "runs")
# A receipt must attest exactly these gates, each with its recorded,
# digest-matching, PASSING transcript on disk.
REQUIRED_GATES = (
    "operator-runtime-pin", "backend-version-pin", "sandbox", "preflight")
GATE_TRANSCRIPT_MARKERS = {
    "preflight": "preflight OK:",
    "macos_sandbox_check": "macos-sandbox-check OK:",
}


def fail(message):
    print(f"step5: STOP — {message}", file=sys.stderr)
    sys.exit(1)


def ok(message):
    print(f"step5: OK   {message}")


def warn(message):
    print(f"step5: WARN {message}")


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sandbox_problem(cmd):
    """The sandbox invocation must be the registered wrapper, by SHAPE
    and by CONTENT — not merely a command mentioning its filename."""
    expected_name = PLATFORM_WRAPPER.get(sys.platform, DEFAULT_WRAPPER)
    shape = (f'["python3", "<checkout>/…/{expected_name}", '
             f'{", ".join(json.dumps(a) for a in REGISTERED_SANDBOX_TAIL)}]')
    if not isinstance(cmd, list) or len(cmd) != 2 + len(
            REGISTERED_SANDBOX_TAIL):
        return (f"`sandbox_cmd` must be exactly the registered wrapper "
                f"invocation {shape}")
    # The registered shape is `python3 <wrapper> …`: accept only a
    # genuine python3 basename (a `python-evil` shim on PATH would
    # otherwise satisfy a prefix test while ignoring the wrapper and
    # launching the backend unconfined).
    if not re.fullmatch(r"python3(\.\d+)?", Path(str(cmd[0])).name):
        return (f"`sandbox_cmd` must run the wrapper with the "
                f"registered python3 interpreter, got {cmd[0]!r}")
    if [str(a) for a in cmd[2:]] != REGISTERED_SANDBOX_TAIL:
        return (f"`sandbox_cmd` arguments must be exactly "
                f"{REGISTERED_SANDBOX_TAIL} — got {list(cmd[2:])}")
    wrapper = Path(str(cmd[1]))
    if not wrapper.is_file():
        return f"`sandbox_cmd` wrapper not found: {wrapper}"
    if wrapper.name != expected_name:
        return (f"`sandbox_cmd` names {wrapper.name}, but this host "
                f"({sys.platform}) requires the registered "
                f"{expected_name}")
    reference = HERE / expected_name
    if file_digest(wrapper) != file_digest(reference):
        return (f"`sandbox_cmd` wrapper {wrapper} differs in content "
                f"from the registered {reference} — an edited or "
                f"substituted wrapper is refused")
    # Behavioral confirmation that THIS interpreter actually executes
    # THIS wrapper: a static name/digest pair cannot prove the pair
    # runs, and the runner would otherwise discover the mismatch only
    # by launching an unconfined backend.
    probe = subprocess.run([str(cmd[0]), str(wrapper), "--help"],
                           capture_output=True, text=True)
    if probe.returncode != 0 or "--confine-to" not in probe.stdout:
        return (f"`sandbox_cmd` interpreter {cmd[0]!r} does not run "
                f"the registered wrapper {wrapper} (its --help did not "
                f"produce the wrapper's own interface)")
    return None


def canonical_tasks(tasks):
    """Canonical holdout order, independent of CLI argument order.

    `make_schedule` consumes the task ORDER before shuffling with the
    recorded seed, so the same seed with a different argument order
    would produce a different scored interleaving — argument order
    must not be an unregistered input to the experiment.

    Returns (ordered_tasks, problem)."""
    by_name = {}
    for task in tasks:
        resolved = Path(task).resolve()
        if not _ordinary_file(resolved):
            return None, "--tasks contains a missing or non-ordinary file"
        by_name[resolved.name] = str(resolved)
    if len(by_name) != len(tasks):
        return None, "--tasks contains duplicate basenames"
    if set(by_name) != set(REGISTERED_HOLDOUT_TASKS):
        return None, (f"--tasks basenames {sorted(by_name)} do not "
                      f"match the registered holdout set "
                      f"{sorted(REGISTERED_HOLDOUT_TASKS)}")
    return [by_name[name] for name in REGISTERED_HOLDOUT_TASKS], None


def canonical_repos(pairs):
    """Normalize repo mappings once so later commands are cwd-independent."""
    try:
        normalized = {}
        for pair in pairs or []:
            name, separator, path = str(pair).partition("=")
            if not separator or not name.strip() or not path.strip():
                raise runner.InfraFailure(
                    "--repos entries must be nonempty NAME=PATH mappings")
            canonical = runner.canonical_repo_name(name)
            resolved = str(Path(path).resolve())
            if canonical in normalized:
                raise runner.InfraFailure(
                    "--repos maps one canonical repository more than once")
            probe = subprocess.run(
                ["git", "-C", resolved, "rev-parse", "--git-dir"],
                capture_output=True, text=True)
            if probe.returncode != 0:
                raise runner.InfraFailure(
                    "--repos contains a path that is not a usable git clone")
            normalized[canonical] = resolved
    except (OSError, runner.InfraFailure) as exc:
        return None, str(exc)
    if set(normalized) != set(runner.REGISTERED_HOLDOUT_REPOS):
        return None, ("--repos must map exactly the registered repositories "
                      f"{list(runner.REGISTERED_HOLDOUT_REPOS)}")
    return [f"{name}={normalized[name]}" for name in sorted(normalized)], None


def task_repo_pin_problem(tasks, repo_pairs):
    """Prove every sealed target commit is present before run order starts."""
    try:
        repos = runner.parse_repo_mapping(repo_pairs, "--repos")
        for task in tasks:
            task_text = runner.read_task_text(task)
            repo_name = runner.canonical_repo_name(
                runner.task_target_repo(task_text, task))
            target_sha = runner.task_target_sha(task_text, task)
            clone = runner.resolve_repo_mapping(repo_name, repos, "--repos")
            probe = subprocess.run(
                ["git", "-C", clone, "rev-parse", "--verify",
                 f"{target_sha}^{{commit}}"],
                capture_output=True, text=True)
            if (probe.returncode != 0
                    or probe.stdout.strip() != target_sha):
                return ("a sealed task target commit is unavailable or "
                        "does not resolve exactly in its registered clone")
    except (OSError, runner.InfraFailure):
        return "sealed task target repo/SHA validation failed"
    return None


def phase_seed_problem(phases, args):
    """Prospective presentation/schedule seeds are immutable policy."""
    if "schedule" in phases and args.seed != REGISTERED_SCHEDULE_SEED:
        return (f"--seed must be the prospectively registered schedule "
                f"seed {REGISTERED_SCHEDULE_SEED}")
    if "next" in phases:
        if args.scorer_seed != REGISTERED_SCORER_SEED:
            return (f"--scorer-seed must be the prospectively registered "
                    f"seed {REGISTERED_SCORER_SEED}")
        if args.verifier_seed != REGISTERED_VERIFIER_SEED:
            return (f"--verifier-seed must be the prospectively registered "
                    f"seed {REGISTERED_VERIFIER_SEED}")
        if not args.drift_report:
            return "--drift-report is required for the next phase"
    return None


def ablation_scope_problem(config, tasks):
    """The no-subagent arm uses the two exact registered task basenames."""
    if {Path(task).name for task in tasks} != set(REGISTERED_HOLDOUT_TASKS):
        return "the operator task set differs from the registered holdout"
    configured = (config.get("arms", {}).get("ablation", {})
                  .get("schedule_tasks") or [])
    if configured != list(REGISTERED_ABLATION_TASKS):
        return ("the ablation schedule_tasks must be the exact registered "
                f"basenames {list(REGISTERED_ABLATION_TASKS)}")
    return None


def verified_seal(config):
    """Fully verify the v2 package and its registered protocol bindings.

    The verifier reads sealed bytes only to hash and validate them; this
    operator never returns, prints, or interpolates their content.
    """
    seal_path = Path(str(config.get("seal_manifest", ""))).resolve()
    if not seal_path.is_file():
        raise runner.InfraFailure(
            "the registered protocol-v2 seal manifest is unavailable")
    try:
        registration = seal_package.verify_package(
            seal_path.parent, seal_path)
    except (OSError, seal_package.SealError) as exc:
        raise runner.InfraFailure(
            "the protocol-v2 atomic seal failed full package verification"
        ) from exc
    if registration != {
            "holdout_tasks": list(REGISTERED_HOLDOUT_TASKS),
            "seal_package_sha256": REGISTERED_SEAL_PACKAGE_SHA256,
    }:
        raise runner.InfraFailure(
            "the verified atomic seal differs from the registered v2 round")
    seal_doc = runner.load_json_object(seal_path, "seal manifest")
    seal_files = seal_doc.get("files")
    if not isinstance(seal_files, dict):
        raise runner.InfraFailure("the v2 seal has no strict file map")
    if (seal_doc.get("protocol_version") != REGISTERED_PROTOCOL_VERSION
            or seal_doc.get("max_judge_attempts")
            != REGISTERED_MAX_JUDGE_ATTEMPTS
            or seal_doc.get("judge_retry_policy")
            != REGISTERED_JUDGE_RETRY_POLICY
            or seal_doc.get("aggregation_policy")
            != REGISTERED_AGGREGATION_POLICY
            or seal_doc.get("ablation_tasks")
            != list(REGISTERED_ABLATION_TASKS)):
        raise runner.InfraFailure(
            "the verified seal differs from the registered protocol-v2 "
            "retry, aggregation, or ablation policy")
    runner.validate_sealed_judge_config(
        config, seal_doc, seal_path, seal_files)
    return seal_path, seal_doc, seal_files


def _ordinary_file(path):
    try:
        info = Path(path).lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


def all_docs_population(results, runs_out):
    """Derive the single v2 judge population from immutable run summaries.

    Gate-passed documents use ``-anon.md``; gate-failed documents use
    ``-diag.md``. A timeout/abort/subagent outcome is still included whenever
    it produced one such document. Only ``artifact_gate: not_evaluated``
    contributes no judge input.
    """
    if not isinstance(results, list):
        raise runner.InfraFailure("schedule manifest results must be a list")
    docs = []
    seen_run_ids = set()
    for result in results:
        if not isinstance(result, dict):
            raise runner.InfraFailure(
                "schedule manifest result must be an object")
        run_id = result.get("run_id")
        if (not isinstance(run_id, str)
                or re.fullmatch(r"[0-9a-f]{12}", run_id) is None
                or run_id in seen_run_ids):
            raise runner.InfraFailure(
                "v2 manifest has a missing, malformed, or duplicate run id")
        seen_run_ids.add(run_id)
        if (result.get("protocol_version") != REGISTERED_PROTOCOL_VERSION
                or result.get("environment_policy_id")
                != REGISTERED_ENVIRONMENT_POLICY_ID
                or result.get("runtime_pins") != {
                    "operator_image_sha256":
                        REGISTERED_OPERATOR_IMAGE_SHA256,
                    "artifact_parser": REGISTERED_ARTIFACT_PARSER,
                    "artifact_parser_version":
                        REGISTERED_ARTIFACT_PARSER_VERSION,
                }
                or result.get("telemetry_policy_id")
                != REGISTERED_AGGREGATION_POLICY["telemetry"]
                or result.get("telemetry_eligible") is not True
                or result.get("telemetry_exclusion_reason") is not None):
            raise runner.InfraFailure(
                "v2 result differs from the registered protocol, "
                "environment, or telemetry policy")
        status = result.get("status")
        failure_kind = result.get("failure_kind")
        if status not in {"completed", "workflow_failure"}:
            raise runner.InfraFailure(
                "complete v2 schedule contains a nonterminal run outcome")
        if ((status == "completed" and failure_kind is not None)
                or (status == "workflow_failure"
                    and failure_kind not in runner.PILOT_V2_FAILURE_KINDS)):
            raise runner.InfraFailure(
                "v2 terminal status and failure kind do not reconcile")
        gate = result.get("artifact_gate")
        artifact_digest = result.get("artifact_sha256")
        diagnostic_digest = result.get("diagnostic_sha256")
        if gate == "passed":
            name = f"run-{run_id}-anon.md"
            digest = artifact_digest
            if diagnostic_digest is not None:
                raise runner.InfraFailure(
                    "gate-passed v2 result also binds a diagnostic copy")
        elif gate == "failed":
            if status != "workflow_failure":
                raise runner.InfraFailure(
                    "artifact-gate failure is not a workflow failure")
            name = f"run-{run_id}-diag.md"
            digest = diagnostic_digest
            if artifact_digest is not None:
                raise runner.InfraFailure(
                    "gate-failed v2 result also binds a passed artifact")
        elif gate == "not_evaluated":
            if (status != "workflow_failure"
                    or artifact_digest is not None
                    or diagnostic_digest is not None):
                raise runner.InfraFailure(
                    "no-document v2 result carries contradictory artifact "
                    "or terminal status")
            continue
        else:
            raise runner.InfraFailure(
                f"v2 result has invalid artifact_gate {gate!r}")
        if (not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
            raise runner.InfraFailure(
                "produced v2 document has no valid immutable digest")
        path = Path(runs_out) / name
        if not _ordinary_file(path) or file_digest(path) != digest:
            raise runner.InfraFailure(
                "produced v2 judge document is missing, unsafe, or changed")
        docs.append(str(path))
    return docs


def operator_runtime_observation():
    """Read the concrete image/parser implementation used by this process."""
    parser_module = runner.artifact_validator.yaml
    parser_name = None
    parser_version = None
    distribution_version = None
    if parser_module is not None:
        if getattr(parser_module, "__name__", None) == "yaml":
            parser_name = "pyyaml"
        else:
            parser_name = getattr(parser_module, "__name__", None)
        raw_version = getattr(parser_module, "__version__", None)
        if raw_version is not None:
            parser_version = str(raw_version)
        try:
            distribution_version = importlib.metadata.version("PyYAML")
        except importlib.metadata.PackageNotFoundError:
            distribution_version = None
    return {
        "operator_image_sha256": os.environ.get(OPERATOR_IMAGE_ENV),
        "artifact_parser": parser_name,
        "artifact_parser_version": parser_version,
        "artifact_parser_distribution_version": distribution_version,
    }


def operator_runtime_problem(config, observation=None):
    """Fail closed when the process is not the registered operator runtime."""
    observed = (operator_runtime_observation()
                if observation is None else observation)
    expected = runner.protocol_v2_runtime_pins(config)
    for field, value in expected.items():
        if observed.get(field) != value:
            return (f"operator runtime `{field}` observed "
                    f"{observed.get(field)!r}, expected {value!r}")
    if observed.get("artifact_parser_distribution_version") != expected.get(
            "artifact_parser_version"):
        return ("operator runtime PyYAML distribution version observed "
                f"{observed.get('artifact_parser_distribution_version')!r}, "
                f"expected {expected.get('artifact_parser_version')!r}")
    return None


def gate_identity(config):
    """What a gate receipt attests: this config, this host, this
    wrapper build. Any of them changing invalidates the receipt."""
    sandbox = config.get("sandbox_cmd") or []
    wrapper = (str(sandbox[1]) if len(sandbox) > 1
               and Path(str(sandbox[1])).is_file() else None)
    return {
        "config_digest": runner.config_digest(config),
        "host": f"{platform.node()}|{sys.platform}",
        "wrapper_sha256": file_digest(wrapper) if wrapper else None,
        "backend_version": REGISTERED_BACKEND_VERSION,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "runtime_observed": operator_runtime_observation(),
    }


def gate_receipt_path(out):
    return Path(out) / "step5-gates-receipt.json"


def gate_receipt_problem(out, config):
    """Scored phases require a durable receipt proving the mandatory
    gates — on macOS including the host-side sandbox check, which the
    runner never repeats — passed for THIS host and config."""
    runtime_issue = operator_runtime_problem(config)
    if runtime_issue:
        return runtime_issue
    path = gate_receipt_path(out)
    if not path.is_file():
        return (f"no gate receipt at {path} — run the `gates` phase on "
                f"this host before scheduling or running")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"gate receipt unreadable: {exc}"
    current = gate_identity(config)
    if receipt.get("identity") != current:
        return ("gate receipt was recorded for a different host, config "
                "or sandbox wrapper — re-run the `gates` phase")
    if receipt.get("operator_runtime_observed") != current.get(
            "runtime_observed"):
        return ("gate receipt does not bind the currently observed operator "
                "image and artifact parser")
    # Identity alone is derived from local config/host data, so a
    # hand-written or truncated receipt would otherwise stand in for
    # gates that never ran. The recorded gate list and every gate's
    # transcript — present, digest-matching, and showing a PASS — are
    # part of the proof.
    if list(receipt.get("gates") or []) != list(REQUIRED_GATES):
        return (f"gate receipt does not record the registered gates "
                f"{list(REQUIRED_GATES)} — re-run the `gates` phase")
    artifacts = receipt.get("artifacts") or {}
    required = ["preflight"]
    if sys.platform == "darwin":
        required.append("macos_sandbox_check")
    for name in required:
        entry = artifacts.get(name) or {}
        path = Path(str(entry.get("path", "")))
        if not entry or not path.is_file():
            return (f"gate receipt carries no {name} transcript on disk "
                    f"— re-run the `gates` phase")
        if file_digest(path) != entry.get("sha256"):
            return (f"{name} transcript {path} differs from the digest "
                    f"recorded in the gate receipt")
        marker = GATE_TRANSCRIPT_MARKERS[name]
        if marker not in path.read_text(encoding="utf-8",
                                        errors="replace"):
            return (f"{name} transcript {path} does not show a passing "
                    f"run ({marker!r} absent)")
    return None


def real_preflight_receipt_path(out):
    return Path(out) / "real-backend-preflight-receipt.json"


def real_preflight_root(out):
    return Path(out) / "real-backend-preflight"


def real_preflight_identity(config, task):
    task_path = Path(task).resolve()
    if (not _ordinary_file(task_path)
            or task_path.name in REGISTERED_HOLDOUT_TASKS):
        raise runner.InfraFailure(
            "real-backend preflight requires an ordinary non-holdout task")
    task_digest = file_digest(task_path)
    _seal_path, _seal_doc, seal_files = verified_seal(config)
    sealed_task_digests = {
        seal_files.get(name) for name in REGISTERED_HOLDOUT_TASKS
    }
    if None in sealed_task_digests or task_digest in sealed_task_digests:
        raise runner.InfraFailure(
            "real-backend preflight task must be content-distinct from every "
            "sealed holdout task (renaming a sealed prompt is not a "
            "throwaway task)")
    task_text = runner.read_task_text(task_path)
    repository = runner.canonical_repo_name(
        runner.task_target_repo(task_text, task_path))
    target_sha = runner.task_target_sha(task_text, task_path)
    if repository != "rpa" or target_sha != FROZEN_CANDIDATE_SHA:
        raise runner.InfraFailure(
            "real-backend preflight task must target rpa at the frozen "
            "candidate commit")
    return {
        "gate_identity": gate_identity(config),
        "task_sha256": task_digest,
        "target_repo": repository,
        "target_sha": target_sha,
        "environment_policy_id": REGISTERED_ENVIRONMENT_POLICY_ID,
        "runtime_pins": runner.protocol_v2_runtime_pins(config),
        "canary_name": "RPA_REAL_PREFLIGHT_CANARY",
    }


def _real_preflight_final_ok(arm, record):
    if arm in {"candidate", "ablation"}:
        return (record.get("status") == "completed"
                and record.get("artifact_gate") == "passed"
                and record.get("failure_kind") is None)
    return (
        (record.get("status") == "completed"
         and record.get("artifact_gate") == "passed"
         and record.get("failure_kind") is None)
        or (record.get("status") == "workflow_failure"
            and record.get("artifact_gate") == "failed"
            and record.get("failure_kind") == "artifact_contract")
    )


def _verified_real_preflight_records(root, dev_config, task, arms=None):
    expected_config_digest = runner.config_digest(dev_config)
    expected_task_digest = file_digest(task)
    records = {}
    selected_arms = (set(REGISTERED_INSTALL_SHA256) if arms is None
                     else set(arms))
    if not selected_arms or not selected_arms <= set(
            REGISTERED_INSTALL_SHA256):
        raise runner.InfraFailure(
            "real-backend preflight requested an invalid arm set")
    for arm in sorted(selected_arms):
        arm_root = Path(root) / arm
        paths = sorted(arm_root.glob("run-*.json"))
        if not paths or any(not _ordinary_file(path) for path in paths):
            raise runner.InfraFailure(
                "real-backend preflight has missing or unsafe run records")
        parsed = []
        terminal = []
        for path in paths:
            record = runner.load_json_object(
                path, "real-backend preflight run record")
            if (record.get("arm") != arm
                    or record.get("config_digest") != expected_config_digest
                    or record.get("task_sha256") != expected_task_digest
                    or record.get("protocol_version")
                    != REGISTERED_PROTOCOL_VERSION
                    or record.get("environment_policy_id")
                    != REGISTERED_ENVIRONMENT_POLICY_ID
                    or record.get("runtime_pins")
                    != runner.protocol_v2_runtime_pins(dev_config)):
                raise runner.InfraFailure(
                    "real-backend preflight record binding mismatch")
            if record.get("status") in {"completed", "workflow_failure"}:
                terminal.append(record)
            elif record.get("status") != "infra_failure":
                raise runner.InfraFailure(
                    "real-backend preflight has an invalid run status")
            parsed.append((path, record))
        attempts = [record.get("attempt") for _path, record in parsed]
        if (any(isinstance(attempt, bool) or not isinstance(attempt, int)
                for attempt in attempts)
                or sorted(attempts) != list(range(1, len(attempts) + 1))
                or len(attempts) > REGISTERED_MAX_INFRA_RETRIES + 1):
            raise runner.InfraFailure(
                "real-backend preflight attempts are not contiguous and "
                "bounded")
        if len(terminal) != 1 or not _real_preflight_final_ok(
                arm, terminal[0]):
            raise runner.InfraFailure(
                "real-backend preflight arm did not reach its registered "
                "acceptable outcome")
        final = terminal[0]
        if final.get("attempt") != max(attempts):
            raise runner.InfraFailure(
                "real-backend preflight terminal outcome is not the last "
                "attempt")
        expected_arm = dev_config["arms"][arm]
        nodes = final.get("nodes")
        accounting = final.get("accounting")
        try:
            recomputed_accounting = runner.account(nodes)
            runner.validate_models(nodes, REGISTERED_MODEL)
            recomputed_effort_capture = runner.validate_efforts(
                nodes, REGISTERED_EFFORT)
        except (TypeError, runner.InfraFailure) as exc:
            raise runner.InfraFailure(
                "real-backend preflight final accounting is invalid") from exc
        tree = (accounting.get("tree", {})
                if isinstance(accounting, dict) else {})
        tree_input = tree.get("input_tokens")
        tree_output = tree.get("output_tokens")
        if (final.get("backend_version") != REGISTERED_BACKEND_VERSION
                or final.get("installation_sha256")
                != REGISTERED_INSTALL_SHA256[arm]
                or final.get("registered_model") != REGISTERED_MODEL
                or final.get("effort") != REGISTERED_EFFORT
                or final.get("entrypoint") != REGISTERED_ENTRYPOINT
                or final.get("target_sha") != FROZEN_CANDIDATE_SHA
                or final.get("task") != str(Path(task).resolve())
                or expected_arm.get("model") != REGISTERED_MODEL
                or expected_arm.get("effort") != REGISTERED_EFFORT
                or expected_arm.get("entrypoint") != REGISTERED_ENTRYPOINT
                or final.get("telemetry_eligible") is not True
                or final.get("telemetry_exclusion_reason") is not None
                or final.get("runtime_pins")
                != runner.protocol_v2_runtime_pins(dev_config)
                or accounting != recomputed_accounting
                or any(isinstance(value, bool)
                       or not isinstance(value, int) or value < 0
                       for value in (tree_input, tree_output))
                or tree_input + tree_output <= 0
                or isinstance(final.get("wall_seconds"), bool)
                or not isinstance(final.get("wall_seconds"), (int, float))
                or final["wall_seconds"] <= 0
                or final.get("effort_capture")
                != recomputed_effort_capture):
            raise runner.InfraFailure(
                "real-backend preflight final record lacks registered "
                "runtime, installation, or accounting proof")
        entries = [
            {"path": str(path.resolve()), "sha256": file_digest(path),
             "attempt": record["attempt"], "status": record["status"]}
            for path, record in sorted(
                parsed, key=lambda item: item[1]["attempt"])
        ]
        records[arm] = {
            "files": entries,
            "final_run_id": final.get("run_id"),
            "status": final.get("status"),
            "failure_kind": final.get("failure_kind"),
            "artifact_gate": final.get("artifact_gate"),
        }
    return records


def real_preflight_receipt_problem(out, config, task):
    """Validate real observations, not a self-asserted PASS marker."""
    if not task:
        return ("--real-preflight-task is required before schedule, runs, "
                "or next")
    receipt_path = real_preflight_receipt_path(out)
    if not _ordinary_file(receipt_path):
        return ("no real-backend preflight receipt; run the "
                "`real-preflight` phase first")
    try:
        identity = real_preflight_identity(config, task)
        receipt = runner.load_json_object(
            receipt_path, "real-backend preflight receipt")
        if receipt.get("identity") != identity:
            return ("real-backend preflight receipt belongs to a different "
                    "host, config, wrapper, or throwaway task")
        dev_config_path = Path(str(receipt.get("dev_config")))
        if not _ordinary_file(dev_config_path):
            return "real-backend preflight dev config is unavailable"
        dev_config = runner.load_config(dev_config_path)
        expected_dev = json.loads(json.dumps(config))
        expected_dev["nonstandard_config"] = True
        if dev_config != expected_dev:
            return "real-backend preflight dev config differs from its source"
        observed = _verified_real_preflight_records(
            real_preflight_root(out), dev_config, Path(task).resolve())
        if receipt.get("records") != observed:
            return "real-backend preflight receipt does not match run records"
    except (OSError, runner.InfraFailure, TypeError, ValueError):
        return "real-backend preflight receipt or records are invalid"
    return None


def validate_config(config):
    """Compare an operator config against the registered configuration.

    Returns (problems, warnings) — problems are fail-closed."""
    problems = []
    warnings = []
    if config.get("protocol_version") != REGISTERED_PROTOCOL_VERSION:
        problems.append(
            f"protocol_version {config.get('protocol_version')!r} != "
            f"registered {REGISTERED_PROTOCOL_VERSION}"
        )
    if (REGISTERED_SEAL_PACKAGE_SHA256
            == PENDING_SEAL_PACKAGE_SHA256):
        problems.append(
            "the fresh protocol-v2 seal digest is still the temporary "
            "all-zero placeholder; register the digest returned by the "
            "uncontaminated sealing session before any operator phase"
        )
    semantic_pins = (
        (runner.PILOT_V2_PROTOCOL_VERSION,
         REGISTERED_PROTOCOL_VERSION, "protocol version"),
        (runner.PILOT_V2_MAX_JUDGE_ATTEMPTS,
         REGISTERED_MAX_JUDGE_ATTEMPTS, "judge attempt bound"),
        (runner.PILOT_V2_ENVIRONMENT_POLICY_ID,
         REGISTERED_ENVIRONMENT_POLICY_ID, "environment policy"),
        (runner.PILOT_V2_JUDGE_RETRY_POLICY,
         REGISTERED_JUDGE_RETRY_POLICY, "judge retry policy"),
        (runner.PILOT_V2_AGGREGATION_POLICY,
         REGISTERED_AGGREGATION_POLICY, "aggregation policy"),
    )
    for actual, expected, label in semantic_pins:
        if actual != expected:
            problems.append(
                f"public harness {label} differs from the registered "
                "protocol-v2 operator contract"
            )
    registered_runtime_pins = {
        "operator_image_sha256": REGISTERED_OPERATOR_IMAGE_SHA256,
        "artifact_parser": REGISTERED_ARTIFACT_PARSER,
        "artifact_parser_version": REGISTERED_ARTIFACT_PARSER_VERSION,
    }
    for field, expected in registered_runtime_pins.items():
        if config.get(field) != expected:
            problems.append(
                f"{field} {config.get(field)!r} != registered {expected!r}")
    if config.get("nonstandard_config"):
        problems.append(
            "`nonstandard_config` is true — holdout runs require the "
            "registered three-arm topology")
    arms = config.get("arms") or {}
    if set(arms) != set(REGISTERED_INSTALL_SHA256):
        problems.append(
            f"arms {sorted(arms)} do not match the registered three "
            f"({sorted(REGISTERED_INSTALL_SHA256)})")
    for name, spec in sorted(arms.items()):
        if not isinstance(spec, dict):
            problems.append(f"arm `{name}` is not an object")
            continue
        if spec.get("model") != REGISTERED_MODEL:
            problems.append(
                f"arm `{name}` model {spec.get('model')!r} != registered "
                f"{REGISTERED_MODEL!r}")
        if spec.get("effort") != REGISTERED_EFFORT:
            problems.append(
                f"arm `{name}` effort {spec.get('effort')!r} != registered "
                f"{REGISTERED_EFFORT!r}")
        if spec.get("entrypoint") != REGISTERED_ENTRYPOINT:
            problems.append(
                f"arm `{name}` entrypoint {spec.get('entrypoint')!r} != "
                f"registered {REGISTERED_ENTRYPOINT!r}")
        expected = REGISTERED_INSTALL_SHA256.get(name)
        if expected and spec.get("sha256") != expected:
            problems.append(
                f"arm `{name}` registers installation sha256 "
                f"{str(spec.get('sha256'))[:16]}… but the frozen record "
                f"is {expected[:16]}…")
    ablation = arms.get("ablation") or {}
    if not ablation.get("forbid_subagents"):
        problems.append(
            "the ablation arm must register `forbid_subagents: true` "
            "(pre-registered no-subagent policy)")
    if (ablation.get("schedule_tasks") or []) != list(
            REGISTERED_ABLATION_TASKS):
        problems.append(
            "the ablation arm must register `schedule_tasks` as exactly "
            f"{list(REGISTERED_ABLATION_TASKS)}")
    if config.get("backend_version") != REGISTERED_BACKEND_VERSION:
        problems.append(
            f"backend_version {config.get('backend_version')!r} != pinned "
            f"{REGISTERED_BACKEND_VERSION!r}")
    if config.get("timeout_seconds") != REGISTERED_TIMEOUT_SECONDS:
        problems.append(
            f"timeout_seconds {config.get('timeout_seconds')!r} != "
            f"registered {REGISTERED_TIMEOUT_SECONDS}")
    if config.get("max_infra_retries") != REGISTERED_MAX_INFRA_RETRIES:
        problems.append(
            f"max_infra_retries {config.get('max_infra_retries')!r} != "
            f"registered {REGISTERED_MAX_INFRA_RETRIES}")
    if config.get("max_judge_attempts") != REGISTERED_MAX_JUDGE_ATTEMPTS:
        problems.append(
            f"max_judge_attempts {config.get('max_judge_attempts')!r} != "
            f"registered {REGISTERED_MAX_JUDGE_ATTEMPTS}")
    if config.get("seal_package_sha256") != REGISTERED_SEAL_PACKAGE_SHA256:
        problems.append(
            "seal_package_sha256 does not match the registered seal")
    # Execution fields are part of the registered configuration: the
    # runner binds whatever it is given into a fresh config digest, so
    # drifted CLI flags or abort-code classification would otherwise
    # pass unnoticed into the holdout.
    if [str(a) for a in (config.get("backend_cmd") or [])] != \
            REGISTERED_BACKEND_CMD:
        problems.append(
            f"backend_cmd differs from the registered command "
            f"{REGISTERED_BACKEND_CMD}")
    if [str(a) for a in (config.get("backend_version_cmd") or [])] != \
            REGISTERED_BACKEND_VERSION_CMD:
        problems.append(
            f"backend_version_cmd differs from the registered "
            f"{REGISTERED_BACKEND_VERSION_CMD}")
    if list(config.get("workflow_abort_exit_codes") or []) != \
            REGISTERED_ABORT_EXIT_CODES:
        problems.append(
            "workflow_abort_exit_codes differs from the registered "
            "empty list — abort classification is part of the freeze")
    if [str(a) for a in (config.get("judge_backend_cmd") or [])] != \
            REGISTERED_JUDGE_BACKEND_CMD:
        problems.append(
            f"judge_backend_cmd differs from the registered mount-free "
            f"command {REGISTERED_JUDGE_BACKEND_CMD}")
    if config.get("judge_model") != REGISTERED_JUDGE_MODEL:
        problems.append(
            f"judge_model {config.get('judge_model')!r} != registered "
            f"{REGISTERED_JUDGE_MODEL!r}")
    if config.get("judge_effort") != REGISTERED_JUDGE_EFFORT:
        problems.append(
            f"judge_effort {config.get('judge_effort')!r} != registered "
            f"{REGISTERED_JUDGE_EFFORT!r}")
    if [str(a) for a in (config.get("drift_fetch_cmd") or [])] != \
            REGISTERED_DRIFT_FETCH_CMD:
        problems.append(
            f"drift_fetch_cmd differs from the registered source-drift "
            f"command {REGISTERED_DRIFT_FETCH_CMD}")
    if not config.get("sandbox_cmd"):
        problems.append(
            "`sandbox_cmd` is unset — scored sessions require the "
            "registered filesystem sandbox")
    else:
        sandbox_issue = sandbox_problem(config["sandbox_cmd"])
        if sandbox_issue:
            problems.append(sandbox_issue)
    return problems, warnings


def phase_gates(args, config):
    gate_artifacts = {}
    runtime_observed = operator_runtime_observation()
    runtime_issue = operator_runtime_problem(config, runtime_observed)
    if runtime_issue:
        fail(runtime_issue + " — no backend observation is permitted")
    ok("operator image and artifact parser pinned "
       f"({runtime_observed['operator_image_sha256']}; "
       f"{runtime_observed['artifact_parser']} "
       f"{runtime_observed['artifact_parser_version']})")
    version = subprocess.run(config.get("backend_version_cmd")
                             or ["claude", "--version"],
                             capture_output=True, text=True)
    if version.returncode != 0:
        fail(f"backend version probe failed: {version.stderr.strip()}")
    actual = version.stdout.strip()
    if actual != REGISTERED_BACKEND_VERSION:
        fail(f"backend CLI is {actual!r}, pinned is "
             f"{REGISTERED_BACKEND_VERSION!r} — install the pinned "
             f"version or register an amendment before running")
    ok(f"backend CLI pinned version ({actual})")

    # The wrapper's identity (shape + content + platform) is already
    # enforced by validate_config before any phase runs.
    if sys.platform == "darwin":
        if not args.newer:
            fail("--newer is required on macOS: the mandatory sandbox "
                 "check needs a commit newer than the frozen candidate")
        check = subprocess.run(
            [sys.executable, str(HERE / "macos_sandbox_check.py"),
             "--repo", args.rpa_clone, "--pin", FROZEN_CANDIDATE_SHA,
             "--newer", args.newer],
            capture_output=True, text=True)
        print(check.stdout, end="")
        # The registered plan requires the check's full PASS output to
        # be recorded WITH the results: a terminal-only transcript
        # leaves the holdout with no auditable proof that the
        # mandatory sandbox gate passed on this host.
        transcript = Path(args.out) / "macos-sandbox-check.txt"
        runner.atomic_write_text(transcript, check.stdout + check.stderr)
        if check.returncode != 0:
            print(check.stderr, end="", file=sys.stderr)
            fail(f"macos_sandbox_check FAILED — scored runs are not "
                 f"permitted on this host until every probe passes "
                 f"(transcript: {transcript})")
        gate_artifacts["macos_sandbox_check"] = {
            "path": str(transcript),
            "sha256": file_digest(transcript),
        }
        ok(f"macOS sandbox validated (transcript recorded: {transcript})")
    else:
        ok(f"registered sandbox wrapper verified ({platform.system()})")

    pre = subprocess.run([sys.executable, str(HERE / "preflight.py")],
                         capture_output=True, text=True)
    tail = pre.stdout.strip().splitlines()[-1] if pre.stdout.strip() else ""
    if pre.returncode != 0:
        print(pre.stdout[-2000:], file=sys.stderr)
        fail(f"synthetic harness preflight FAILED ({tail}) — the "
             f"preflight is host-agnostic by design, so a check "
             f"failing for host-specific reasons is a defect to "
             f"report, not to bypass")
    preflight_transcript = Path(args.out) / "preflight.txt"
    runner.atomic_write_text(preflight_transcript, pre.stdout)
    gate_artifacts["preflight"] = {
        "path": str(preflight_transcript),
        "sha256": file_digest(preflight_transcript),
        "summary": tail,
    }
    ok(f"synthetic harness preflight ({tail}; transcript recorded: "
       f"{preflight_transcript})")

    # Durable receipt: the scored phases refuse to proceed without one
    # matching this host, config and wrapper — a later invocation with
    # `--phases schedule,runs` cannot bypass the mandatory gates. The
    # receipt points at the persisted gate transcripts, so the results
    # carry auditable proof of every mandatory gate.
    receipt = {
        "identity": gate_identity(config),
        "gates": list(REQUIRED_GATES),
        "operator_runtime_observed": runtime_observed,
        "backend_version_observed": actual,
        "artifacts": gate_artifacts,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    runner.atomic_write_text(
        gate_receipt_path(args.out), json.dumps(receipt, indent=2) + "\n")
    ok(f"gate receipt recorded ({gate_receipt_path(args.out)})")


def phase_real_preflight(args, config):
    gate_issue = gate_receipt_problem(args.out, config)
    if gate_issue:
        fail(gate_issue)
    receipt_path = real_preflight_receipt_path(args.out)
    if _ordinary_file(receipt_path):
        receipt_issue = real_preflight_receipt_problem(
            args.out, config, args.real_preflight_task)
        if receipt_issue:
            fail(receipt_issue)
        ok("real-backend preflight receipt and all three arm records "
           "revalidated")
        return
    if os.path.lexists(receipt_path):
        fail("real-backend preflight receipt path is unsafe or non-regular; "
             "no backend observation is permitted")
    root = real_preflight_root(args.out)
    if os.path.lexists(root):
        fail("real-backend preflight output exists without a valid receipt; "
             "backend observation state is ambiguous — use a fresh operator "
             "output root")
    try:
        identity = real_preflight_identity(
            config, args.real_preflight_task)
        repos = runner.parse_repo_mapping(args.repos, "--repos")
        repository = runner.resolve_repo_mapping("rpa", repos, "--repos")
        target_probe = subprocess.run(
            ["git", "-C", repository, "rev-parse", "--verify",
             f"{FROZEN_CANDIDATE_SHA}^{{commit}}"],
            capture_output=True, text=True)
        if (target_probe.returncode != 0
                or target_probe.stdout.strip() != FROZEN_CANDIDATE_SHA):
            raise runner.InfraFailure(
                "the real-backend preflight rpa clone does not contain the "
                "exact frozen candidate commit")
    except (OSError, runner.InfraFailure) as exc:
        fail(str(exc))
    root.mkdir(parents=True)
    dev_config = json.loads(json.dumps(config))
    dev_config["nonstandard_config"] = True
    dev_config_path = root / "dev-config.json"
    runner.atomic_write_text(
        dev_config_path,
        json.dumps(dev_config, indent=2, sort_keys=True) + "\n")
    allowed_exit_codes = {
        "baseline": {0, 1}, "candidate": {0}, "ablation": {0},
    }
    preflight_env = os.environ.copy()
    preflight_env["RPA_REAL_PREFLIGHT_CANARY"] = hashlib.sha256(
        os.urandom(32)).hexdigest()
    for arm in sorted(REGISTERED_INSTALL_SHA256):
        arm_output = root / arm
        result = subprocess.run([
            sys.executable, str(HERE / "runner.py"),
            "--config", str(dev_config_path),
            "--arm", arm,
            "--task", str(Path(args.real_preflight_task).resolve()),
            "--repo", repository,
            "--output", str(arm_output),
        ], capture_output=True, text=True, env=preflight_env)
        if result.returncode not in allowed_exit_codes[arm]:
            fail("real-backend preflight stopped before an acceptable "
                 f"terminal outcome for arm `{arm}`; its immutable records "
                 "remain for investigation and this output root is blocked")
        try:
            _verified_real_preflight_records(
                root, dev_config, Path(args.real_preflight_task).resolve(),
                arms=(arm,))
        except runner.InfraFailure as exc:
            fail(f"real-backend preflight arm `{arm}` produced invalid "
                 f"state before the next arm could launch: {exc}")
    try:
        records = _verified_real_preflight_records(
            root, dev_config, Path(args.real_preflight_task).resolve())
    except runner.InfraFailure as exc:
        fail(str(exc))
    receipt = {
        "identity": identity,
        "dev_config": str(dev_config_path.resolve()),
        "records": records,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    runner.atomic_write_text(
        receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt_issue = real_preflight_receipt_problem(
        args.out, config, args.real_preflight_task)
    if receipt_issue:
        fail(receipt_issue)
    ok("real-backend preflight passed for baseline, candidate, and ablation; "
       f"digest-bound receipt recorded ({receipt_path})")


def phase_installs(args, config):
    out = Path(args.out) / "installs"
    build = subprocess.run(
        [sys.executable, str(HERE / "build_installs.py"),
         "--repo", args.rpa_clone, "--out", str(out)],
        capture_output=True, text=True)
    if build.returncode != 0:
        print(build.stderr, file=sys.stderr)
        fail("build_installs.py failed")
    built = {}
    for line in build.stdout.strip().splitlines():
        arm, _, digest = line.partition(": ")
        built[arm.strip()] = digest.strip()
    for arm, expected in sorted(REGISTERED_INSTALL_SHA256.items()):
        if built.get(arm) != expected:
            fail(f"rebuilt {arm} installation hashes "
                 f"{str(built.get(arm))[:16]}…, registered is "
                 f"{expected[:16]}… — the frozen trees or the build "
                 f"overlay changed")
    ok("three arm installations rebuilt to the registered hashes")
    for arm, spec in sorted((config.get("arms") or {}).items()):
        path = spec.get("installation_dir")
        if not path or not Path(path).is_dir():
            fail(f"arm `{arm}` installation_dir does not exist: {path}")
        actual = runner.hash_tree(path)
        if actual != REGISTERED_INSTALL_SHA256.get(arm):
            fail(f"arm `{arm}` installation_dir {path} hashes "
                 f"{actual[:16]}…, registered is "
                 f"{REGISTERED_INSTALL_SHA256[arm][:16]}… — point the "
                 f"config at the freshly built tree under {out}")
    ok("config installation_dirs match the registered hashes")


def phase_seal(args, config):
    try:
        _seal_path, _seal_doc, seal_files = verified_seal(config)
    except runner.InfraFailure as exc:
        fail(str(exc))
    for task in args.tasks:
        task_path = Path(task)
        task_name = task_path.name
        if (not _ordinary_file(task_path)
                or file_digest(task_path) != seal_files.get(task_name)):
            fail("a supplied holdout task is missing, unsafe, or differs "
                 "from its atomic-seal digest")
    ok("complete protocol-v2 seal, policies, judge pins, and six task "
       "digests match the registered fresh round")


def verify_registered_schedule(path, config, tasks):
    """Return the one schedule fixed by config, tasks, and prospective seed."""
    schedule_path = Path(path).resolve()
    if not _ordinary_file(schedule_path):
        raise runner.InfraFailure(
            "the prospectively registered schedule is unavailable")
    schedule = runner.load_json_object(schedule_path, "schedule")
    expected = runner.make_schedule(
        config, tasks, REGISTERED_REPLICATES, REGISTERED_SCHEDULE_SEED,
        allow_nonstandard=False)
    if schedule != expected:
        raise runner.InfraFailure(
            "the existing schedule does not match the registered config, "
            f"task set, and seed {REGISTERED_SCHEDULE_SEED}")
    return schedule


def phase_schedule(args, config):
    problem = gate_receipt_problem(args.out, config)
    if problem:
        fail(problem)
    problem = real_preflight_receipt_problem(
        args.out, config, args.real_preflight_task)
    if problem:
        fail(problem)
    sched_path = Path(args.out) / "schedule.json"
    if sched_path.exists():
        try:
            verify_registered_schedule(sched_path, config, args.tasks)
        except runner.InfraFailure as exc:
            fail(str(exc))
        ok(f"registered schedule already written ({sched_path}) — "
           "reusing its verified immutable seed/order")
        return
    result = subprocess.run(
        [sys.executable, str(HERE / "runner.py"), "--config", args.config,
         "--make-schedule", "--tasks", *args.tasks,
         "--replicates", str(REGISTERED_REPLICATES),
         "--seed", str(REGISTERED_SCHEDULE_SEED),
         "--schedule-out", str(sched_path)],
        capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        fail("schedule creation refused (see the classified failure above)")
    try:
        verify_registered_schedule(sched_path, config, args.tasks)
    except runner.InfraFailure as exc:
        fail(str(exc))
    ok(f"pre-registered schedule written ({sched_path}, seed "
       f"{REGISTERED_SCHEDULE_SEED})")


def phase_runs(args, config):
    problem = gate_receipt_problem(args.out, config)
    if problem:
        fail(problem)
    problem = real_preflight_receipt_problem(
        args.out, config, args.real_preflight_task)
    if problem:
        fail(problem)
    sched_path = Path(args.out) / "schedule.json"
    try:
        verify_registered_schedule(sched_path, config, args.tasks)
    except runner.InfraFailure as exc:
        fail(str(exc))
    runs_out = Path(args.out) / "runs"
    print("step5: executing the schedule (resumable — re-run this "
          "driver to continue after an interruption)")
    result = subprocess.run(
        [sys.executable, str(HERE / "runner.py"), "--config", args.config,
         "--run-schedule", str(sched_path), "--repos", *args.repos,
         "--tasks", *args.tasks, "--output", str(runs_out)],
        text=True)
    if result.returncode != 0:
        fail("schedule execution stopped — the classified failure above "
             "explains why; progress is persisted, re-run to resume")
    ok(f"schedule complete ({runs_out}/schedule-manifest.json)")


def _completed_manifest(args, config):
    """Reconstruct and verify the exact immutable v2 run population."""
    runs_out = (Path(args.out) / "runs").resolve()
    manifest_path = runs_out / "schedule-manifest.json"
    if not _ordinary_file(manifest_path):
        raise runner.InfraFailure(
            "the complete schedule manifest is unavailable")
    manifest = runner.load_json_object(manifest_path, "schedule manifest")
    if manifest.get("complete") is not True:
        raise runner.InfraFailure(
            "the schedule is incomplete; judges require the whole round")
    if (manifest.get("protocol_version") != REGISTERED_PROTOCOL_VERSION
            or manifest.get("environment_policy_id")
            != REGISTERED_ENVIRONMENT_POLICY_ID
            or manifest.get("runtime_pins")
            != runner.protocol_v2_runtime_pins(config)
            or manifest.get("config_digest") != runner.config_digest(config)
            or manifest.get("replicates") != REGISTERED_REPLICATES
            or manifest.get("nonstandard") is not False):
        raise runner.InfraFailure(
            "the completion manifest differs from the registered v2 "
            "configuration or population")
    schedule_path = (Path(args.out) / "schedule.json").resolve()
    try:
        recorded_schedule = Path(str(manifest.get("schedule"))).resolve()
    except (OSError, TypeError) as exc:
        raise runner.InfraFailure(
            "the completion manifest has no safe schedule reference") from exc
    if recorded_schedule != schedule_path.resolve() or not _ordinary_file(
            schedule_path):
        raise runner.InfraFailure(
            "the completion manifest is not bound to the operator schedule")
    schedule = verify_registered_schedule(
        schedule_path, config, args.tasks)
    if (manifest.get("schedule_digest") != runner.schedule_digest(schedule)
            or schedule.get("protocol_version")
            != REGISTERED_PROTOCOL_VERSION
            or schedule.get("environment_policy_id")
            != REGISTERED_ENVIRONMENT_POLICY_ID
            or schedule.get("runtime_pins")
            != runner.protocol_v2_runtime_pins(config)):
        raise runner.InfraFailure(
            "the completion manifest or schedule has a v2 binding mismatch")
    results = manifest.get("results")
    entries = schedule.get("entries")
    if not isinstance(results, list) or not isinstance(entries, list):
        raise runner.InfraFailure(
            "the v2 schedule or completion result population is malformed")
    runner.verify_results_against_records(
        results, entries, runs_out, require_all=True)
    # Use the same whole-namespace audit that score mode and final
    # aggregation apply.  Matching the final records alone is insufficient:
    # foreign/superseded attempts, orphan artifacts, or any surviving claim
    # must stop the handoff before an exact judge command is emitted.
    runner.audit_completed_v2_run_material(
        config, manifest_path, schedule, results, entries)
    docs = all_docs_population(results, runs_out)
    return manifest_path, docs


def _next_commands(args, manifest_path, docs, seal_path, seal_doc):
    """Build two exact all-doc judge commands and one aggregate command."""
    package_root = seal_path.parent
    judge_out = (Path(args.out) / "judging").resolve()
    drift_report = Path(args.drift_report).resolve()
    if not _ordinary_file(drift_report):
        raise runner.InfraFailure(
            "the registered pre-score source-drift report is unavailable")
    drift = runner.load_json_object(drift_report, "source-drift report")
    external_task = REGISTERED_HOLDOUT_TASKS[4]
    drift_entry = drift.get(external_task)
    if (set(drift) != {external_task}
            or not isinstance(drift_entry, dict)
            or set(drift_entry) != {"changed"}
            or not isinstance(drift_entry.get("changed"), dict)):
        raise runner.InfraFailure(
            "the source-drift report has no canonical v2 external-task "
            "adjudication map")
    snapshot_sources = seal_doc.get("snapshot_sources")
    seal_files = seal_doc.get("files")
    if (not isinstance(snapshot_sources, dict)
            or not isinstance(seal_files, dict)
            or not set(drift_entry["changed"]).issubset(snapshot_sources)):
        raise runner.InfraFailure(
            "the source-drift report names an unsealed snapshot")
    for key, adjudication in drift_entry["changed"].items():
        if (not isinstance(adjudication, dict)
                or set(adjudication)
                != {"observed_sha256", "material", "rationale"}
                or re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(adjudication.get("observed_sha256", ""))) is None
                or not isinstance(adjudication.get("material"), bool)
                or not isinstance(adjudication.get("rationale"), str)
                or not adjudication["rationale"].strip()
                or adjudication.get("observed_sha256")
                == seal_files.get(key)):
            raise runner.InfraFailure(
                "the source-drift report contains a malformed changed-file "
                "adjudication")
    contexts = seal_doc.get("task_contexts")
    prompts = seal_doc.get("judge_prompts")
    if (not isinstance(contexts, dict) or set(contexts)
            != set(REGISTERED_HOLDOUT_TASKS)
            or not isinstance(prompts, dict)
            or set(prompts) != {"scorer", "verifier"}):
        raise runner.InfraFailure(
            "the verified seal has incomplete judge associations")
    context_args = [
        f"{name}={package_root / contexts[name]}"
        for name in REGISTERED_HOLDOUT_TASKS
    ]
    snapshot_root = package_root / "snapshots"
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise runner.InfraFailure(
            "the verified external-context snapshot directory is unavailable")
    common = [
        sys.executable, str((HERE / "runner.py").resolve()),
        "--config", str(Path(args.config).resolve()), "--score",
        "--docs", *docs,
        "--manifest", str(manifest_path),
        "--tasks", *[str(Path(task).resolve()) for task in args.tasks],
        "--task-contexts", *context_args,
        "--seal-manifest", str(seal_path),
        "--task-snapshots", f"{external_task}={snapshot_root}",
        "--drift-report", str(drift_report),
    ]

    def judge_command(role, seed, evidence=False):
        command = [
            *common,
            "--judge-prompt", str(package_root / prompts[role]),
            "--scoring-seed", str(seed),
        ]
        if evidence:
            command.extend(["--evidence-repos", *args.repos])
        command.extend(["--output", str(judge_out)])
        return command

    judge_commands = [
        judge_command("scorer", REGISTERED_SCORER_SEED),
        judge_command("verifier", REGISTERED_VERIFIER_SEED, evidence=True),
    ]
    aggregate_command = [
        sys.executable, str((HERE / "aggregate_results.py").resolve()),
        "--config", str(Path(args.config).resolve()),
        "--manifest", str(manifest_path),
        "--scorer-manifest",
        str(judge_out / "scoring-scorer-all-docs-manifest.json"),
        "--verifier-manifest",
        str(judge_out / "scoring-verifier-all-docs-manifest.json"),
        "--seal-manifest", str(seal_path),
        "--output", str(
            (Path(args.out) / "protocol-v2-aggregate.json").resolve()),
    ]
    return judge_commands, aggregate_command


def persist_exact_handoff(path, text):
    """Create a handoff file once, or prove its existing bytes are exact.

    The listing is evidence for clean judge sessions, so silently replacing
    edited or unsafe state would make a resumed handoff ambiguous.  Creation
    uses the runner's durable O_EXCL writer; the persistent operator lock
    serializes ordinary resumptions, while the fallback read handles a
    pathname won by a concurrent creator without overwriting it.
    """
    path = Path(path)
    if not os.path.lexists(path):
        try:
            runner.exclusive_write_text(path, text)
            return
        except FileExistsError:
            pass
        except OSError as exc:
            raise runner.InfraFailure(
                f"cannot durably create judge handoff {path}: {exc}"
            ) from exc
    existing = runner.read_input_text(path, "judge handoff")
    if existing != text:
        raise runner.InfraFailure(
            "existing judge handoff differs from the exact manifest-derived "
            "document population")


def phase_next(args, config):
    problem = gate_receipt_problem(args.out, config)
    if problem:
        fail(problem)
    problem = real_preflight_receipt_problem(
        args.out, config, args.real_preflight_task)
    if problem:
        fail(problem)
    try:
        seal_path, seal_doc, _seal_files = verified_seal(config)
        manifest_path, docs = _completed_manifest(args, config)
        judge_commands, aggregate_command = _next_commands(
            args, manifest_path, docs, seal_path, seal_doc)
    except runner.InfraFailure as exc:
        fail(str(exc))
    docs_listing = Path(args.out) / "docs-all-docs.txt"
    try:
        persist_exact_handoff(
            docs_listing, "" if not docs else "\n".join(docs) + "\n")
    except runner.InfraFailure as exc:
        fail(str(exc))
    print(f"step5: all-docs population: {len(docs)} documents "
          f"(immutable listing: {docs_listing})")
    print("step5: sealed judge session 1/2 (scorer, all-docs):")
    print(shlex.join(judge_commands[0]))
    print("step5: only after session 1 completes and validates, sealed judge "
          "session 2/2 (verifier, all-docs):")
    print(shlex.join(judge_commands[1]))
    print("step5: deterministic protocol-v2 aggregation after both batches:")
    print(shlex.join(aggregate_command))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse
                                     .RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--rpa-clone", required=True,
                        help="clone of this repository holding both "
                             "pinned trees (installation build + sandbox "
                             "validation)")
    parser.add_argument("--repos", nargs="+", required=True,
                        help="NAME=PATH clone mapping for the target repos")
    parser.add_argument("--tasks", nargs="+", required=True,
                        help="the six sealed holdout task files")
    parser.add_argument("--out", required=True,
                        help="output root (installs/, schedule.json, "
                             "runs/, judging/)")
    parser.add_argument("--seed", type=int,
                        help=f"fixed schedule seed "
                             f"{REGISTERED_SCHEDULE_SEED} (required for "
                             "the schedule phase)")
    parser.add_argument("--scorer-seed", type=int,
                        help=f"fixed all-doc scorer presentation seed "
                             f"{REGISTERED_SCORER_SEED} (required for the "
                             "next phase)")
    parser.add_argument("--verifier-seed", type=int,
                        help=f"fixed all-doc verifier presentation seed "
                             f"{REGISTERED_VERIFIER_SEED} (required for the "
                             "next phase)")
    parser.add_argument("--drift-report",
                        help="pre-score source-drift adjudication JSON "
                             "(required for the next phase)")
    parser.add_argument("--real-preflight-task",
                        help="non-holdout throwaway task pinned to rpa at "
                             "the frozen candidate SHA; required for "
                             "real-preflight and every scored phase")
    parser.add_argument("--newer",
                        help="macOS only: a commit newer than the frozen "
                             "candidate, for the mandatory sandbox check")
    parser.add_argument(
        "--phases", default=",".join(DEFAULT_PHASES),
        help=("comma-separated operator phases; default stops after runs. "
              "Use next for the sequential scorer/verifier handoff; every "
              "produced anon/diag document is included and no-document "
              "outcomes are omitted"))
    args = parser.parse_args()
    args.config = str(Path(args.config).resolve())
    args.rpa_clone = str(Path(args.rpa_clone).resolve())
    args.out = str(Path(args.out).resolve())
    if args.real_preflight_task:
        args.real_preflight_task = str(
            Path(args.real_preflight_task).resolve())

    try:
        config = runner.load_config(args.config)
    except runner.InfraFailure as exc:
        fail(f"config refused: {exc}")
    problems, warnings = validate_config(config)
    for w in warnings:
        warn(w)
    if problems:
        for problem in problems:
            print(f"step5: STOP — {problem}", file=sys.stderr)
        sys.exit(1)
    ok("config matches the registered runtime configuration")

    canonical, problem = canonical_tasks(args.tasks)
    if problem:
        fail(problem)
    args.tasks = canonical
    scope_issue = ablation_scope_problem(config, args.tasks)
    if scope_issue:
        fail(scope_issue)
    normalized_repos, repo_problem = canonical_repos(args.repos)
    if repo_problem:
        fail(repo_problem)
    args.repos = normalized_repos
    pin_issue = task_repo_pin_problem(args.tasks, args.repos)
    if pin_issue:
        fail(pin_issue)

    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = [p for p in phases if p not in PHASES]
    if unknown:
        fail(f"unknown phase(s): {unknown} — valid: {list(PHASES)}")

    seed_issue = phase_seed_problem(phases, args)
    if seed_issue:
        fail(seed_issue)
    if (set(phases).intersection(
            {"real-preflight", "schedule", "runs", "next"})
            and not args.real_preflight_task):
        fail("--real-preflight-task is required for real-preflight, "
             "schedule, runs, and next")
    try:
        out_root, out_identity = runner.bind_output_directory(args.out)
        args.out = str(out_root)
        operator_lock = runner.acquire_advisory_lock(
            out_root / ".step5-operator.lock", "step-5 operator output")
    except (OSError, runner.InfraFailure) as exc:
        fail(str(exc))
    try:
        for name in PHASES:
            if name not in phases:
                continue
            try:
                runner.verify_output_directory(
                    out_root, out_identity,
                    "step-5 operator output directory")
            except runner.InfraFailure as exc:
                fail(str(exc))
            print(f"\n=== phase: {name} ===")
            globals()[f"phase_{name.replace('-', '_')}"](args, config)
    finally:
        runner.release_advisory_lock(operator_lock)
    print("\nstep5: phases complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
