#!/usr/bin/env python3
"""Operator driver for Sequence step 5 (holdout runs) of the pilot.

Runs on the operator host that holds the sealed package and the target
clones. Every phase is FAIL-CLOSED: a drifted configuration, a rebuilt
installation, a wrong CLI version, a failing sandbox, or an unexpected
task set stops the experiment before any scored run, instead of
producing results that cannot be trusted.

The registered values below come from the pilot plan's freeze record
(`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`)
and are compared against the operator's config — this driver is the
mechanical restatement of that record, not a new decision.

PROTOCOL NOTE: this driver never reads or prints holdout task CONTENT.
It checks task-file basenames and digests only, so running it does not
expose sealed prompts or ground truth to the operator's context.

Phases (default: all except `score`):

  gates     platform, backend CLI version pin, sandbox validation
            (macOS: the mandatory `macos_sandbox_check.py`), synthetic
            harness preflight
  installs  rebuild the three arm installations from the pinned trees
            and verify their hashes against the registered ones AND
            against the config's arm registrations
  seal      verify the seal manifest against the registered package
            SHA-256 and the six registered holdout task basenames
  schedule  write the pre-registered randomized schedule (3 replicates
            per arm/task cell, recorded seed)
  runs      execute the schedule (resumable: re-run to continue)
  next      print the exact scoring commands for the judge passes

Usage:

  step5_operator.py --config CONFIG.json --rpa-clone /path/to/rpa \\
      --repos rpa=/path/to/rpa livekit-voice-agent=/path/... \\
      --tasks /sealed/holdout-1.md ... /sealed/holdout-6.md \\
      --seed 20260728 --out /private-eval-workspace/holdout-runs \\
      [--newer <sha newer than the frozen candidate>] \\
      [--phases gates,installs,seal,schedule,runs,next]
"""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402 — colocated harness module

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
REGISTERED_SEAL_PACKAGE_SHA256 = (
    "e611ada9427954e34b597e093d7da35acb278d534dbdf54dffef72700a5da95c")
REGISTERED_HOLDOUT_TASKS = tuple(f"holdout-{i}.md" for i in range(1, 7))
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
# The seal's judge_config is authoritative at scoring time; the plan
# recorded these, so a difference is surfaced as a WARNING, not a stop.
RECORDED_JUDGE_MODEL = "opus"
RECORDED_JUDGE_EFFORT = "high"

PHASES = ("gates", "installs", "seal", "schedule", "runs", "next")


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
    }


def gate_receipt_path(out):
    return Path(out) / "step5-gates-receipt.json"


def gate_receipt_problem(out, config):
    """Scored phases require a durable receipt proving the mandatory
    gates — on macOS including the host-side sandbox check, which the
    runner never repeats — passed for THIS host and config."""
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
    return None


def validate_config(config):
    """Compare an operator config against the registered configuration.

    Returns (problems, warnings) — problems are fail-closed."""
    problems = []
    warnings = []
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
    if len(ablation.get("schedule_tasks") or []) != 2:
        problems.append(
            "the ablation arm must register exactly its two designated "
            "holdout tasks in `schedule_tasks`")
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
    if not config.get("sandbox_cmd"):
        problems.append(
            "`sandbox_cmd` is unset — scored sessions require the "
            "registered filesystem sandbox")
    else:
        sandbox_issue = sandbox_problem(config["sandbox_cmd"])
        if sandbox_issue:
            problems.append(sandbox_issue)
    if config.get("judge_model") != RECORDED_JUDGE_MODEL:
        warnings.append(
            f"judge_model {config.get('judge_model')!r} differs from the "
            f"plan's record {RECORDED_JUDGE_MODEL!r} — the sealed "
            f"judge_config is authoritative and is enforced at scoring")
    if config.get("judge_effort") != RECORDED_JUDGE_EFFORT:
        warnings.append(
            f"judge_effort {config.get('judge_effort')!r} differs from the "
            f"plan's record {RECORDED_JUDGE_EFFORT!r} — the sealed "
            f"judge_config is authoritative and is enforced at scoring")
    return problems, warnings


def phase_gates(args, config):
    gate_artifacts = {}
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
        transcript.write_text(check.stdout + check.stderr,
                              encoding="utf-8")
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
    preflight_transcript.write_text(pre.stdout, encoding="utf-8")
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
        "gates": ["backend-version-pin", "sandbox", "preflight"],
        "backend_version_observed": actual,
        "artifacts": gate_artifacts,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    gate_receipt_path(args.out).write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    ok(f"gate receipt recorded ({gate_receipt_path(args.out)})")


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
    seal_path = config.get("seal_manifest")
    if not seal_path or not Path(seal_path).is_file():
        fail(f"seal_manifest not found: {seal_path}")
    digest = hashlib.sha256(Path(seal_path).read_bytes()).hexdigest()
    if digest != REGISTERED_SEAL_PACKAGE_SHA256:
        fail("seal manifest does not match the registered "
             "seal_package_sha256 — a recomputed or altered seal is "
             "refused")
    ok("seal manifest matches the registered package SHA-256")
    supplied = sorted(Path(t).name for t in args.tasks)
    if supplied != sorted(REGISTERED_HOLDOUT_TASKS):
        fail(f"--tasks basenames {supplied} do not match the registered "
             f"holdout set {sorted(REGISTERED_HOLDOUT_TASKS)}")
    for task in args.tasks:
        if not Path(task).is_file():
            fail(f"task file not found: {task}")
    ok(f"six registered holdout task files present "
       f"({', '.join(sorted(REGISTERED_HOLDOUT_TASKS))})")


def phase_schedule(args, config):
    problem = gate_receipt_problem(args.out, config)
    if problem:
        fail(problem)
    sched_path = Path(args.out) / "schedule.json"
    if sched_path.exists():
        ok(f"schedule already written ({sched_path}) — reusing it; "
           f"delete it to re-randomize")
        return
    result = subprocess.run(
        [sys.executable, str(HERE / "runner.py"), "--config", args.config,
         "--make-schedule", "--tasks", *args.tasks,
         "--replicates", str(REGISTERED_REPLICATES),
         "--seed", str(args.seed), "--schedule-out", str(sched_path)],
        capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        fail("schedule creation refused (see the classified failure above)")
    ok(f"pre-registered schedule written ({sched_path}, seed {args.seed})")


def phase_runs(args, config):
    problem = gate_receipt_problem(args.out, config)
    if problem:
        fail(problem)
    sched_path = Path(args.out) / "schedule.json"
    if not sched_path.is_file():
        fail(f"no schedule at {sched_path} — run the `schedule` phase")
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


def phase_next(args, config):
    runs_out = Path(args.out) / "runs"
    manifest = runs_out / "schedule-manifest.json"
    judge_out = Path(args.out) / "judging"
    print("\nstep5: scoring — run these in the judge session "
          "(paths from the sealed package):\n")
    print("# 1. blind scorer (primary axis)")
    print(f"python3 {HERE / 'runner.py'} --config {args.config} --score \\")
    print(f"    --docs {runs_out}/run-*-anon.md \\")
    print("    --judge-prompt <sealed>/judge-scorer.md \\")
    print(f"    --manifest {manifest} --tasks {' '.join(args.tasks)} \\")
    print("    --task-contexts holdout-1.md=<sealed>/ctx-1.md ... \\")
    print("    --seal-manifest <sealed>/seal-manifest.json \\")
    print(f"    --scoring-seed <recorded> --output {judge_out}\n")
    print("# 2. verifier (evidence-bound; adds --evidence-repos)")
    print(f"python3 {HERE / 'runner.py'} --config {args.config} --score \\")
    print(f"    --docs {runs_out}/run-*-anon.md \\")
    print("    --judge-prompt <sealed>/judge-verifier.md \\")
    print(f"    --manifest {manifest} --tasks {' '.join(args.tasks)} \\")
    print("    --task-contexts ... --seal-manifest <sealed>/seal-manifest.json \\")
    print(f"    --evidence-repos {' '.join(args.repos)} \\")
    print(f"    --scoring-seed <recorded> --output {judge_out}\n")
    print("# 3. diagnostic content axis (registered amendment): the same")
    print("#    scorer batch PLUS gate-failed replicates' -diag.md copies")
    print(f"python3 {HERE / 'runner.py'} --config {args.config} --score \\")
    print(f"    --docs {runs_out}/run-*-anon.md {runs_out}/run-*-diag.md \\")
    print("    --judge-prompt <sealed>/judge-scorer.md \\")
    print(f"    --manifest {manifest} --tasks {' '.join(args.tasks)} \\")
    print("    --task-contexts ... --seal-manifest <sealed>/seal-manifest.json \\")
    print(f"    --diagnostic-axis --scoring-seed <recorded> "
          f"--output {judge_out}\n")
    print("External-context tasks additionally need --task-snapshots and")
    print("a --drift-report from the harness's own re-fetch.")


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
                        help="recorded schedule randomization seed "
                             "(required for the schedule phase)")
    parser.add_argument("--newer",
                        help="macOS only: a commit newer than the frozen "
                             "candidate, for the mandatory sandbox check")
    parser.add_argument("--phases", default=",".join(
        p for p in PHASES if p != "score"))
    args = parser.parse_args()

    phases = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = [p for p in phases if p not in PHASES]
    if unknown:
        fail(f"unknown phase(s): {unknown} — valid: {list(PHASES)}")

    try:
        config = runner.load_config(args.config)
    except runner.InfraFailure as exc:
        fail(f"config refused: {exc}")
    problems, warnings = validate_config(config)
    for w in warnings:
        warn(w)
    if problems:
        for p in problems:
            print(f"step5: STOP — {p}", file=sys.stderr)
        sys.exit(1)
    ok("config matches the registered runtime configuration")

    Path(args.out).mkdir(parents=True, exist_ok=True)
    if "schedule" in phases and args.seed is None:
        fail("--seed is required for the schedule phase (it is recorded "
             "in the schedule and reproduces it)")
    for name in PHASES:
        if name not in phases:
            continue
        print(f"\n=== phase: {name} ===")
        globals()[f"phase_{name}"](args, config)
    print("\nstep5: phases complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
