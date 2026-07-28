#!/usr/bin/env python3
"""Eval-runner harness for the /research_codebase modernization pilot.

Implements prerequisite 5 of
`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`.
Capability map (each proven by `--preflight` before any scored run):

  1. installation-hash verification  — every run hashes EVERY arm's
     installation tree against its registered SHA-256 (drift in any arm
     halts the experiment), mounts a copy of the selected arm into the
     run's profile, and passes its path to the backend via the
     `{installation}` placeholder in `backend_cmd` (a command without the
     placeholder is refused — a bare backend would never exercise the arm).
  2. per-node model/effort capture   — every transcript node records its
     model; effort is pinned on the backend command line via the `{effort}`
     placeholder (its absence is refused). Nodes that report effort must
     match the registered value (`per_node` capture); the real Claude
     stream schema carries no per-node effort field, so an all-absent
     transcript is accepted on the strength of the mandatory pin and
     recorded as `command_pin` capture — partial reporting is broken
     capture and invalidates the run. One shared model/effort/entrypoint
     is enforced across ALL arms (`validate_arm_parity`): installation
     content is the only permitted arm difference. Both the synthetic mock
     schema and the real Claude headless stream (`assistant` events with
     nested usage, `tool_use` blocks, `parent_tool_use_id` sidechains) are
     parsed, and ALL input-token categories — including cache creation and
     cache reads — count toward tree-wide cost.
  3. clean profile                   — each run uses a runner-created
     CLAUDE_CONFIG_DIR containing only `settings.json` and the mounted
     installation; ambient personal skills/config are never on the load
     path.
  4. worktree isolation              — each run executes in a disposable
     detached git worktree at the task's pinned `target-sha` (verified),
     removed afterwards; a dirty/wrong checkout can never be researched.
  5. prompt extraction               — only the `## Task prompt` section of
     a task file reaches the evaluated session; the marker is required
     unconditionally, so a malformed task fails the run instead of
     silently sending the whole file.
  6. infra vs workflow failure       — backend crashes / unparseable output
     / wrong SHA are `infra_failure` (run invalid, automatically
     re-executed up to `max_infra_retries` times); timeouts, registered
     abort exits, and missing-artifact completions are `workflow_failure`
     (counted per the failed-run rule, never replaced), and their records
     preserve tree-wide accounting — including nodes harvested from the
     partial transcript of a timed-out or aborted session, validated for
     model/effort parity first. A failure whose run produced NO accounting
     nodes in any session carries no effective-runtime parity evidence and
     is invalidated (infra) instead of counted. An arm with
     `forbid_subagents` (the fleet-ablation third arm) fails as a counted
     workflow failure if its run spawned any subagent.
  7. tree-wide accounting            — tokens and tool calls are summed over
     every transcript node, main-context and subagent subtotals, plus a
     `subagents_spawned` count of DISTINCT subagent identities (several
     messages from one subagent are not several subagents). One run-level
     deadline (`timeout_seconds`) is shared by the initial session and all
     continuations, so stop-prone arms cannot draw extra compute.
  8. artifact freshness              — only documents created or modified
     during the run count; pre-existing research docs are ignored.
  9. anonymization                   — scored copies carry a random run id
     and masked fingerprint frontmatter; score mode refuses raw
     (fingerprint-bearing) documents at its own boundary, so a CLI mistake
     cannot leak identity to the blind judge.
 10. fresh pinned judge sessions     — `--score` spawns each judge call as
     a new backend session in its own fresh profile rooted OUTSIDE the
     experiment tree. Blind SCORERS get an empty working directory with
     filesystem/exec/web tools denied (JUDGE_SETTINGS) so they cannot
     unblind themselves; evidence VERIFIERS (`--evidence-repo` +
     `--evidence-sha`) get a disposable read-only worktree of the frozen
     evidence at the pinned sha (VERIFIER_SETTINGS) so file-and-line
     citations can actually be checked. Every full response is preserved
     on disk under a unique per-invocation id
     (`judge-<scoring_id>-<n>.json`), so separate scorer/verifier passes
     never overwrite each other.
 11. pre-registered run schedule    — `--make-schedule` emits a balanced,
     seed-recorded, randomized interleaving of every arm x task x
     replicate; a standard (holdout) schedule requires the registered
     three-arm topology (baseline, candidate, exactly one no-subagent
     ablation arm) and REGISTERED_REPLICATES per cell — anything else must
     be explicitly marked nonstandard (dev-set tuning only) — and the
     ablation arm must be explicitly scoped to exactly its two designated
     tasks. `--run-schedule` RECONSTRUCTS the expected schedule from the
     registered config, the operator-supplied task set, and the recorded
     seed — the file's own arms/tasks/entries are never trusted — executes
     in recorded order, persists progress to the manifest after every
     entry, and resumes an interrupted schedule at the first unfinished
     entry; the resume identity is a digest of the ENTIRE schedule.
     Scoring is bound to the completion manifest: every completed
     scheduled replicate is scored exactly once (ad-hoc scoring must be
     explicitly marked unscheduled).
 12. pinned backend version         — the exact Claude Code version is
     registered (`backend_version` + `backend_version_cmd`) and probed
     before every run and judge pass; drift between interleaved entries
     blocks the run.
 13. filesystem sandbox             — production configs must register
     `sandbox_cmd`, a wrapper confining every evaluated and judge session
     to its own working directory + profile ({workdir}/{profile} expand
     per session); a clean CLAUDE_CONFIG_DIR alone is not filesystem
     isolation, and without the sandbox a session could traverse to
     sealed materials, prior artifacts, or manifests. Dev configs
     (`nonstandard_config: true`) may omit it.

The backend command is configurable (`backend_cmd`); production uses the
`claude` CLI in headless mode, while `--preflight` uses the bundled
deterministic `mock_claude.py`. A real-backend preflight on the throwaway
task is still required once before baseline runs (see the pilot plan).

Stdlib only.
"""

import argparse
import importlib.util
import hashlib
import json
import random
import re
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

_ARTIFACT_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "artifact_validator", Path(__file__).with_name("validate_artifact.py"))
artifact_validator = importlib.util.module_from_spec(_ARTIFACT_VALIDATOR_SPEC)
_ARTIFACT_VALIDATOR_SPEC.loader.exec_module(artifact_validator)

MAX_CONTINUATIONS = 3
DEFAULT_MAX_INFRA_RETRIES = 2
# The pilot protocol fixes the replicate count and the holdout size;
# schedules that deviate must be explicitly marked nonstandard (dev-set
# tuning only, never holdout).
REGISTERED_REPLICATES = 3
REGISTERED_HOLDOUT_TASKS = 6
# The plan fixes the fleet-ablation arm to these two archetypes; a standard
# schedule validates the scoped tasks' `archetype` frontmatter against them.
REGISTERED_ABLATION_ARCHETYPES = ("subsystem-explanation", "narrow where-is")
# Canonical coverage sets from the registered plan: the holdout covers
# all three named eval repositories (matched on the repo's final path
# component, case-insensitive) and exactly the six numbered archetypes —
# free-form labels are refused.
REGISTERED_HOLDOUT_REPOS = ("rpa", "livekit-voice-agent", "neomenu")
REGISTERED_HOLDOUT_ARCHETYPE_KEYWORDS = {
    1: "subsystem",        # subsystem end-to-end explanation (mid-size)
    2: "largest",          # same on the largest repo
    3: "narrow where-is",  # narrow "where is Y defined/configured"
    4: "thoughts",         # answer spans code + prior thoughts/ docs
    5: "external",         # requires external library/API context
    6: "premise",          # question with a known-wrong premise
}
CONTINUATION_MESSAGE = (
    "Proceed with the research as specified; no additional constraints."
)
FINGERPRINT_KEYS = (
    "researcher",
    "git_commit",
    "branch",
    "date",
    "last_updated",
    "last_updated_by",
)
TARGET_SHA_RE = re.compile(r"^target-sha:\s*([0-9a-f]{7,40})\s*$", re.MULTILINE)
TARGET_REPO_RE = re.compile(r"^target-repo:\s*(\S+)\s*$", re.MULTILINE)


class InfraFailure(Exception):
    """Harness/environment fault: the run is invalid and must be re-executed."""


class BlockingInfraFailure(InfraFailure):
    """A fault that can neither be counted nor auto-re-executed: a
    workflow-shaped failure (timeout/registered abort) that left no
    effective-runtime evidence. Counting it would violate runtime parity
    (nothing proves the session ran on the registered model/effort);
    silently re-executing it would violate the counted-never-replaced
    protocol for timeouts/aborts. The experiment stops here pending
    operator investigation — reported through the same structured
    infra_failure contract, but never consumed by the automatic retry
    loop."""


class WorkflowFailure(Exception):
    """The evaluated workflow failed (timeout, abort, no artifact): counted,
    never replaced. `stdout` carries any partial transcript emitted before
    the failure so the failed run's accounting is preserved."""

    def __init__(self, message, stdout=None):
        super().__init__(message)
        self.stdout = stdout


# Blind SCORERS receive the anonymized document inline; filesystem, exec,
# and web tools are denied in the scorer profile so an unsandboxed judge
# cannot read run artifacts (raw copies, run records) and unblind itself.
# Exact rule names are validated during the real-backend preflight.
JUDGE_SETTINGS = {
    "permissions": {
        "deny": ["Read", "Glob", "Grep", "Bash", "Write", "Edit",
                 "NotebookEdit", "WebFetch", "WebSearch", "Task"]
    }
}

# Evidence VERIFIERS must independently check file-and-line citations, so
# read-only inspection tools stay available; anything that could mutate the
# evidence or reach outside it (write/exec/web/subagents) is denied. The
# verifier's cwd is a disposable worktree of the frozen evidence repo at the
# pinned sha — never the experiment output tree — and the registered
# `sandbox_cmd` (mandatory for production configs) confines its filesystem
# to that worktree, so Read/Glob/Grep cannot follow absolute or parent
# paths to manifests, raw artifacts, or sealed materials.
VERIFIER_SETTINGS = {
    "permissions": {
        "deny": ["Bash", "Write", "Edit", "NotebookEdit",
                 "WebFetch", "WebSearch", "Task"]
    }
}


def apply_sandbox(config, cmd, workdir, profile):
    """Filesystem isolation for spawned sessions. A clean CLAUDE_CONFIG_DIR
    is NOT a filesystem sandbox: without one, an evaluated run or judge
    could traverse parent or absolute paths to sealed tasks, ground truth,
    rubric, judge prompts, prior artifacts, or manifests. Production
    configs must register `sandbox_cmd` — a wrapper (e.g. bwrap or
    sandbox-exec, validated during the real-backend preflight) that
    confines the session to its own working directory and profile;
    `{workdir}`/`{profile}` expand per session. Dev configs
    (`nonstandard_config: true`) may omit it."""
    sandbox = config.get("sandbox_cmd")
    if not sandbox:
        if not config.get("nonstandard_config"):
            raise InfraFailure(
                "production configs must register `sandbox_cmd` — evaluated "
                "and judge sessions require filesystem isolation beyond a "
                "clean profile"
            )
        return list(cmd)
    if not config.get("nonstandard_config"):
        # A wrapper that never receives the paths to confine provides no
        # isolation at all (e.g. `/usr/bin/env`): production sandboxes must
        # take both confinement placeholders.
        missing = [ph for ph in ("{workdir}", "{profile}")
                   if not any(ph in part for part in sandbox)]
        if missing:
            raise InfraFailure(
                f"production `sandbox_cmd` must confine the session via the "
                f"{', '.join(missing)} placeholder(s) — a wrapper without "
                f"them provides no filesystem isolation"
            )
    prefix = []
    for part in sandbox:
        part = part.replace("{workdir}", str(workdir))
        part = part.replace("{profile}", str(profile))
        prefix.append(part)
    return prefix + list(cmd)


def hash_tree(root):
    """Deterministic SHA-256 of a directory tree: sorted relative POSIX
    paths, each followed by NUL + entry type + permission bits + content +
    NUL. Metadata is part of the artifact: an executable-bit flip changes
    how an installation runs, so it must change the registered digest —
    content-only hashing would let a mode-drifted installation pass
    verification."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        if path.is_symlink():
            kind, mode = "symlink", 0
        elif path.is_dir():
            kind, mode = "dir", path.stat().st_mode & 0o7777
        else:
            kind, mode = "file", path.stat().st_mode & 0o7777
        digest.update(f"{kind}:{mode:o}".encode("utf-8") + b"\0")
        if kind == "file":
            digest.update(path.read_bytes())
        elif kind == "symlink":
            digest.update(os.readlink(path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path, text):
    """Crash-safe persistence for manifests and run records: the content is
    written to a temp file in the same directory, flushed to disk, and
    atomically swapped into place with os.replace — a crash mid-write can
    never leave partial JSON that would block resuming already-observed
    entries (and deleting a corrupt manifest to recover would rerun them,
    which the protocol forbids)."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_config(path):
    """User-input faults (missing/unreadable/malformed config, wrong shape)
    are classified infrastructure failures, never raw tracebacks: a
    syntactically valid but structurally wrong config (e.g. `{}`) must not
    surface later as a KeyError deep inside a mode."""
    try:
        with open(path, encoding="utf-8") as fh:
            config = json.load(fh)
    except OSError as exc:
        raise InfraFailure(f"cannot read config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InfraFailure(f"config {path} is not valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise InfraFailure(
            f"config {path} must be a JSON object, got "
            f"{type(config).__name__}"
        )
    arms = config.get("arms")
    if not isinstance(arms, dict) or not arms:
        raise InfraFailure(
            f"config {path}: `arms` must be a non-empty object"
        )
    def require_str(value, what, required=True):
        if value is None and not required:
            return
        if not isinstance(value, str) or not value.strip():
            raise InfraFailure(
                f"config {path}: {what} must be a non-empty string, "
                f"got {value!r}"
            )

    def require_cmd(value, what, required=False):
        if value is None and not required:
            return
        if (not isinstance(value, list) or not value
                or not all(isinstance(part, str) and part
                           for part in value)):
            raise InfraFailure(
                f"config {path}: {what} must be a non-empty list of "
                f"strings, got {value!r}"
            )

    for arm_name, arm in arms.items():
        if not isinstance(arm, dict):
            raise InfraFailure(
                f"config {path}: arm `{arm_name}` must be an object"
            )
        for required in ("installation_dir", "sha256", "model", "effort"):
            if not arm.get(required):
                raise InfraFailure(
                    f"config {path}: arm `{arm_name}` is missing required "
                    f"`{required}`"
                )
            # Presence is not shape: a truthy wrong-typed value (e.g.
            # `"model": ["opus"]`) must fail HERE, classified, not as a
            # TypeError deep inside parity validation.
            require_str(arm.get(required), f"arm `{arm_name}` `{required}`")
        require_str(arm.get("entrypoint"),
                    f"arm `{arm_name}` `entrypoint`", required=False)
        if ("forbid_subagents" in arm
                and not isinstance(arm["forbid_subagents"], bool)):
            raise InfraFailure(
                f"config {path}: arm `{arm_name}` `forbid_subagents` must "
                f"be a boolean, got {arm['forbid_subagents']!r}"
            )
        if arm.get("schedule_tasks") is not None:
            require_cmd(arm.get("schedule_tasks"),
                        f"arm `{arm_name}` `schedule_tasks`")
    if ("nonstandard_config" in config
            and not isinstance(config["nonstandard_config"], bool)):
        raise InfraFailure(
            f"config {path}: `nonstandard_config` must be a boolean, got "
            f"{config['nonstandard_config']!r} — a truthy string like "
            f"\"false\" would silently select dev mode and bypass the "
            f"production safeguards"
        )
    require_cmd(config.get("backend_cmd"), "`backend_cmd`", required=True)
    require_cmd(config.get("judge_backend_cmd"), "`judge_backend_cmd`")
    require_cmd(config.get("backend_version_cmd"), "`backend_version_cmd`")
    require_cmd(config.get("sandbox_cmd"), "`sandbox_cmd`")
    require_cmd(config.get("drift_fetch_cmd"), "`drift_fetch_cmd`")
    require_str(config.get("judge_model"), "`judge_model`", required=False)
    require_str(config.get("judge_effort"), "`judge_effort`",
                required=False)
    require_str(config.get("backend_version"), "`backend_version`",
                required=False)
    require_str(config.get("seal_manifest"), "`seal_manifest`",
                required=False)
    require_str(config.get("seal_package_sha256"),
                "`seal_package_sha256`", required=False)
    return config


def config_digest(config):
    """Digest of the registered runtime configuration a schedule binds to.
    A uniform change (model, effort, entrypoint, backend command/version,
    installation hashes, judge pins, retry/timeout policy) would slip past
    arm parity — which only compares arms with each other — so the digest
    pins the WHOLE configuration for the schedule's lifetime. Installation
    directories are identified by their registered sha256, not their path."""
    material = {
        "arms": {
            name: {key: arm.get(key)
                   for key in ("model", "effort", "entrypoint", "sha256",
                               "forbid_subagents", "schedule_tasks")}
            for name, arm in config.get("arms", {}).items()
        },
        "backend_cmd": config.get("backend_cmd"),
        "backend_version": config.get("backend_version"),
        "backend_version_cmd": config.get("backend_version_cmd"),
        "judge_backend_cmd": config.get("judge_backend_cmd"),
        "judge_model": config.get("judge_model"),
        "judge_effort": config.get("judge_effort"),
        "workflow_abort_exit_codes": config.get("workflow_abort_exit_codes"),
        "max_infra_retries": config.get("max_infra_retries"),
        "timeout_seconds": config.get("timeout_seconds"),
        "nonstandard_config": config.get("nonstandard_config", False),
        "sandbox_cmd": config.get("sandbox_cmd"),
        "drift_fetch_cmd": config.get("drift_fetch_cmd"),
        "seal_package_sha256": config.get("seal_package_sha256"),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_json_object(path, what):
    """User-supplied JSON artifacts (schedules, manifests, seal manifests,
    drift reports) fail as classified infrastructure errors, never as
    OSError/JSONDecodeError/AttributeError tracebacks."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InfraFailure(f"{what} {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InfraFailure(f"{what} {path} must be a JSON object")
    return data


def verify_backend_version(config):
    """The pinned-runtime protocol includes the exact backend (Claude Code)
    version: it is registered in the config and probed before EVERY run and
    every judge pass, so a backend upgrade between interleaved schedule
    entries cannot mix runtime versions inside one comparison."""
    expected = config.get("backend_version")
    probe = config.get("backend_version_cmd")
    if not expected or not probe:
        raise InfraFailure(
            "config must register `backend_version` and `backend_version_cmd` "
            "— the pinned-runtime protocol requires a per-run version check"
        )
    try:
        proc = subprocess.run(probe, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfraFailure(f"backend version probe failed: {exc}") from exc
    if proc.returncode != 0:
        raise InfraFailure(
            f"backend version probe exited {proc.returncode}: "
            f"{proc.stderr.strip()[:200]}"
        )
    actual = proc.stdout.strip()
    if actual != expected:
        raise InfraFailure(
            f"backend version `{actual}` differs from registered "
            f"`{expected}` — run blocked"
        )
    return actual


def verify_installation(arm_name, arm_cfg):
    actual = hash_tree(arm_cfg["installation_dir"])
    expected = arm_cfg["sha256"]
    if actual != expected:
        raise InfraFailure(
            f"arm `{arm_name}`: installation hash mismatch "
            f"(expected {expected}, got {actual}) — run blocked"
        )
    return actual


def make_profile(workspace, label, installation_dir=None, settings=None):
    """Create a fresh profile directory used as CLAUDE_CONFIG_DIR so ambient
    personal skills/commands/settings are never on the load path. When an
    installation is given, mount a verified copy inside the profile."""
    profile = Path(workspace) / "profiles" / f"{label}-{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=False)
    (profile / "settings.json").write_text(
        json.dumps(settings or {}) + "\n", encoding="utf-8"
    )
    mount = None
    expected_entries = ["settings.json"]
    if installation_dir is not None:
        # Neutral mount path for EVERY arm: the backend sees the same
        # `plugins/installation` label regardless of arm, so command and
        # profile paths cannot reveal which arm a session belongs to.
        mount = profile / "plugins" / "installation"
        shutil.copytree(installation_dir, mount)
        expected_entries = ["plugins", "settings.json"]
    entries = sorted(p.name for p in profile.iterdir())
    if entries != expected_entries:
        raise InfraFailure(f"profile {profile} not clean: {entries}")
    return profile, mount


def backend_env(profile):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(profile)
    return env


def expand_backend_cmd(backend_cmd, mount, effort=None):
    expanded = []
    for part in backend_cmd:
        if "{installation}" in part:
            if mount is None:
                raise InfraFailure(
                    "backend_cmd expects {installation} but no installation mounted"
                )
            part = part.replace("{installation}", str(mount))
        if "{effort}" in part:
            if not effort:
                raise InfraFailure("backend_cmd expects {effort} but none configured")
            part = part.replace("{effort}", str(effort))
        expanded.append(part)
    return expanded


def read_input_text(path, what):
    """Operator-supplied files (task files, scoring documents, judge
    prompts, seal manifests, drift copies) are CLI input: a missing,
    unreadable, or non-UTF-8 file is an infrastructure fault reported
    through the structured infra_failure contract, never a raw traceback."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc


def read_input_bytes(path, what):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc


def validate_sealed_judge_config(config, seal_doc):
    """The atomic seal registers the judge session configuration; the
    runtime config must match it exactly. config_digest alone binds
    whatever judge settings existed at schedule creation — without this
    check, a config changed after sealing but before scheduling would pass
    every later digest comparison while scoring under unregistered judge
    settings."""
    sealed = seal_doc.get("judge_config")
    if not isinstance(sealed, dict):
        raise InfraFailure(
            "the sealed package records no `judge_config` — the atomic "
            "seal must bind the judge session configuration "
            "(judge_backend_cmd, judge_model, judge_effort)"
        )
    for key in ("judge_backend_cmd", "judge_model", "judge_effort"):
        if sealed.get(key) != config.get(key):
            raise InfraFailure(
                f"registered `{key}` differs from the sealed judge "
                f"configuration — scoring would run under unregistered "
                f"judge settings; fix the config or re-seal"
            )


def parse_seal_manifest(seal_bytes, path):
    """The registered seal manifest is operator-supplied input: decode and
    parse through the classified boundary, and require `files` to be an
    object before any dereference."""
    try:
        seal_doc = json.loads(seal_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InfraFailure(
            f"seal manifest {path} is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(seal_doc, dict):
        raise InfraFailure(f"seal manifest {path} must be a JSON object")
    files = seal_doc.get("files")
    if not isinstance(files, dict):
        raise InfraFailure(
            f"seal manifest {path}: `files` must be an object mapping "
            f"package-relative paths to sha256 digests"
        )
    return seal_doc, files


def read_task_text(task_path):
    return read_input_text(task_path, "task file")


def read_task_bytes(task_path):
    return read_input_bytes(task_path, "task file")


def extract_task_prompt(task_path):
    """Only the `## Task prompt` section may reach an evaluated session.
    The marker is required unconditionally: a malformed task must fail the
    run, never silently alter the experiment by sending the whole file."""
    text = read_task_text(task_path)
    match = re.search(
        r"^## Task prompt\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not match or not match.group(1).strip():
        raise InfraFailure(
            f"{task_path}: no `## Task prompt` marker — refusing to send "
            f"the file to an evaluated run"
        )
    return match.group(1).strip(), text


def task_target_sha(task_text, task_path):
    match = TARGET_SHA_RE.search(task_text)
    if not match:
        raise InfraFailure(f"{task_path}: no pinned `target-sha` in frontmatter")
    return match.group(1)


def task_target_repo(task_text, task_path):
    match = TARGET_REPO_RE.search(task_text)
    if not match:
        raise InfraFailure(
            f"{task_path}: no `target-repo` in frontmatter — every task "
            f"must name its pinned repository"
        )
    return match.group(1).strip()


def canonical_repo_name(name):
    """`target-repo` frontmatter may be qualified (dsmolchanov/rpa) or bare
    (rpa); coverage validation, routing, and evidence mapping share ONE
    canonical form — the final path component, lowercased — so a
    valid-looking schedule can never stall on a spelling mismatch between
    the task files and the operator's NAME=PATH mapping. The canonical
    name is also used as a worktree directory name, so it must be a
    single ORDINARY path component: `..`, `.`, or anything with
    separators/odd characters is refused before it can be joined into a
    filesystem path."""
    canon = str(name).strip().rstrip("/").rsplit("/", 1)[-1].lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", canon)             or canon in (".", ".."):
        raise InfraFailure(
            f"target-repo name `{name}` does not canonicalize to a single "
            f"ordinary path component — refusing to use it for routing or "
            f"worktree naming"
        )
    return canon


def resolve_repo_mapping(name, repos, what):
    canon = {}
    for key, path in repos.items():
        ckey = canonical_repo_name(key)
        if ckey in canon and canon[ckey] != path:
            raise InfraFailure(
                f"{what}: two different clones registered for repository "
                f"`{ckey}` — mapping keys must be unambiguous"
            )
        canon[ckey] = path
    cname = canonical_repo_name(name)
    if cname not in canon:
        raise InfraFailure(
            f"target-repo `{name}` has no registered clone in {what} — "
            f"supply it as {cname}=/path/to/clone"
        )
    return canon[cname]


def resolve_repo(task_path, repos):
    """The registered holdout spans several repositories: each task names
    its `target-repo` and the operator supplies a NAME=PATH clone mapping;
    one clone can never serve a multi-repo schedule."""
    text = read_task_text(task_path)
    name = task_target_repo(text, task_path)
    return resolve_repo_mapping(name, repos, "--repos")


def parse_repo_mapping(pairs, what):
    repos = {}
    for pair in pairs or []:
        name, sep, path = pair.partition("=")
        if not sep or not name.strip() or not path.strip():
            raise InfraFailure(f"{what} entries must be NAME=PATH, got {pair!r}")
        repos[name.strip()] = path.strip()
    return repos


def _standard_topology(config):
    """The registered topology names its roles: arms `baseline` and
    `candidate` (neither may forbid subagents) plus exactly one no-subagent
    ablation arm. Counting arms alone would accept a typo like `canddate`
    and leave the plan's comparisons without a guaranteed pair."""
    arms = config.get("arms", {})
    ablation_arms = [name for name, arm in arms.items()
                     if arm.get("forbid_subagents")]
    return (len(arms) == 3
            and "baseline" in arms
            and "candidate" in arms
            and len(ablation_arms) == 1
            and "baseline" not in ablation_arms
            and "candidate" not in ablation_arms)


def validate_arm_topology(config):
    """Production (holdout) configs carry the registered three-arm topology
    — verified before EVERY run, so a config that lost or misnamed an arm
    cannot quietly produce valid-looking runs. Dev configs must declare
    themselves with `nonstandard_config: true`. Returns True when the
    topology is the registered standard one."""
    standard = _standard_topology(config)
    if not standard and not config.get("nonstandard_config"):
        raise InfraFailure(
            "registered three-arm topology required — arms `baseline` and "
            "`candidate` (by those exact names) plus exactly one "
            "no-subagent ablation arm; dev configs must set "
            "`nonstandard_config: true`"
        )
    return standard


def _git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise InfraFailure(
            f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()[:300]}"
        )
    return proc.stdout.strip()


def make_worktree(repo_dir, sha, workspace, name=None):
    """Disposable detached worktree at the pinned SHA, verified. The
    destination is resolved to an absolute path BEFORE reaching git:
    `git -C <repo>` resolves relative destinations under the repo while the
    caller would resolve them under its own cwd — two different places."""
    slot = Path(workspace) / "worktrees" / uuid.uuid4().hex[:12]
    # When the caller names the checkout, the worktree directory carries
    # the CANONICAL target-repo name: the prescribed metadata script
    # derives `repository` from the toplevel basename, so a uuid-named
    # checkout would make every conforming workflow record a uuid and
    # fail the run binding. The uuid stays in the parent for disposal
    # uniqueness; the name is task identity, identical across arms.
    dest = (slot / name).resolve() if name else slot.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "worktree", "add", "--detach", str(dest), sha)
    head = _git(dest, "rev-parse", "HEAD")
    if not head.startswith(sha):
        _git(repo_dir, "worktree", "remove", "--force", str(dest))
        raise InfraFailure(f"worktree HEAD {head} != pinned target-sha {sha}")
    if _git(dest, "status", "--porcelain"):
        _git(repo_dir, "worktree", "remove", "--force", str(dest))
        raise InfraFailure("worktree is not clean after checkout")
    return dest


def remove_worktree(repo_dir, worktree):
    try:
        _git(repo_dir, "worktree", "remove", "--force", str(worktree))
    except InfraFailure:
        shutil.rmtree(worktree, ignore_errors=True)
    parent = Path(worktree).parent
    try:
        if parent.name != "worktrees" and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def spawn_session(cmd, prompt, cwd, env, timeout, resume=None,
                  workflow_abort_exits=()):
    """`workflow_abort_exits` lists backend exit codes that represent an
    evaluated-workflow abort: those are WorkflowFailure (counted, never
    replaced), while any other nonzero exit is an infra crash (rerun). The
    real-backend preflight establishes the pinned CLI's abort codes."""
    full = list(cmd)
    if resume:
        full += ["--resume", resume]
    full += ["-p", prompt, "--output-format", "stream-json"]
    try:
        proc = subprocess.Popen(
            full, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True
        )
    except OSError as exc:
        raise InfraFailure(f"backend could not be spawned: {exc}") from exc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # The session runs in its OWN process group (start_new_session):
        # on timeout the WHOLE tree is killed, so spawned tool
        # subprocesses cannot keep consuming the budget or touching the
        # disposable worktree after the timeout is recorded.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        stdout, stderr = proc.communicate()
        raise WorkflowFailure(
            f"session timed out after {timeout}s", stdout=stdout
        ) from exc
    if proc.returncode != 0:
        detail = (stderr or "").strip()[:500]
        if proc.returncode in workflow_abort_exits:
            # Counted experimental outcome: keep the partial transcript so
            # the failed run's tree-wide accounting survives.
            raise WorkflowFailure(
                f"workflow aborted (exit {proc.returncode}): {detail}",
                stdout=stdout,
            )
        raise InfraFailure(f"backend exited {proc.returncode}: {detail}")
    return stdout


def _node_from_event(event):
    """Derive one accounting node from a stream event, or None.

    Two schemas are understood:
      * synthetic `type: "node"` records (the mock backend's declared
        accounting), and
      * the real Claude Code headless stream, where each `type: "assistant"`
        event nests `model`/`usage` inside `message`, tool calls appear as
        `tool_use` content blocks, and a non-null `parent_tool_use_id` marks
        a subagent (sidechain) node. The real schema carries no per-node
        effort field — see `validate_efforts` for how the pin is enforced.
    """
    if event.get("type") == "node":
        usage = event.get("usage", {})
        return {
            "model": event.get("model"),
            "effort": event.get("effort"),
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "tool_calls": int(event.get("tool_calls", 0)),
            "subagent": bool(event.get("subagent", False)),
            "subagent_id": event.get("subagent_id"),
            "subagent_launches": int(event.get("subagent_launches", 0)),
        }
    if event.get("type") == "assistant" and isinstance(event.get("message"), dict):
        message = event["message"]
        # The real CLI also emits CLIENT-GENERATED assistant notices (e.g.
        # "Unknown command: ...") marked `model: "<synthetic>"`. They are
        # not API turns: no runtime ran and no usage was consumed, so they
        # are excluded from parity validation and accounting. A session
        # consisting only of synthetic notices therefore yields no nodes —
        # exactly the no-parity-evidence case, which blocks instead of
        # counting (real-backend shakedown finding, 2026-07-27).
        if message.get("model") == "<synthetic>":
            return None
        usage = message.get("usage") or {}
        content = message.get("content") or []
        tool_calls = sum(
            1 for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        )
        # A subagent LAUNCH is evidenced by the Task tool_use itself: a
        # child that dies before emitting any assistant event must still
        # count as delegation (the no-subagent policy hinges on this).
        subagent_launches = sum(
            1 for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
            and block.get("name") == "Task"
        )
        # The real CLI reports cached prompt tokens SEPARATELY from
        # `input_tokens`; all input categories must count toward tree-wide
        # cost, or cached runs undercount (differently per arm) and can
        # fake the token-savings pass bar.
        input_total = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
        )
        return {
            "model": message.get("model"),
            "effort": event.get("effort"),
            "input_tokens": input_total,
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "tool_calls": tool_calls,
            "subagent": event.get("parent_tool_use_id") is not None,
            # Identity, not just a boolean: several messages from one
            # subagent must stay distinguishable from one message each
            # from several subagents, or "subagents spawned" is unmeasurable.
            "subagent_id": event.get("parent_tool_use_id"),
            "subagent_launches": subagent_launches,
        }
    return None


def parse_transcript(stdout):
    """Parse stream-json lines into accounting nodes plus the final response
    text. Understands both the synthetic mock schema and the real Claude
    headless stream (see `_node_from_event`); `session_id` comes from any
    event carrying one, response text from the `result` event."""
    nodes, session_id, result_parts = [], None, []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InfraFailure(f"unparseable backend output line: {line[:200]}") from exc
        if "session_id" in event:
            session_id = event["session_id"]
        if event.get("type") == "result" and event.get("result"):
            result_parts.append(str(event["result"]))
        node = _node_from_event(event)
        if node is not None:
            nodes.append(node)
    if session_id is None:
        raise InfraFailure("backend output contained no session_id")
    if not nodes:
        raise InfraFailure("backend output contained no accounting nodes")
    return session_id, nodes, "\n".join(result_parts)


def parse_nodes_tolerant(stdout):
    """Best-effort node extraction from a partial transcript (timeout or
    workflow abort): unparseable lines are skipped, nothing is required.
    Used only to preserve accounting on already-failed runs."""
    nodes = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        node = _node_from_event(event)
        if node is not None:
            nodes.append(node)
    return nodes


def account(nodes):
    totals = {"main": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
              "subagents": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0}}
    for node in nodes:
        bucket = totals["subagents"] if node["subagent"] else totals["main"]
        bucket["input_tokens"] += node["input_tokens"]
        bucket["output_tokens"] += node["output_tokens"]
        bucket["tool_calls"] += node["tool_calls"]
    totals["tree"] = {
        key: totals["main"][key] + totals["subagents"][key]
        for key in totals["main"]
    }
    distinct = {n.get("subagent_id") for n in nodes
                if n["subagent"] and n.get("subagent_id")}
    anonymous = sum(1 for n in nodes
                    if n["subagent"] and not n.get("subagent_id"))
    # Two independent signals: child-output evidence AND launch (Task
    # tool_use) evidence — a child that died before emitting anything
    # still counts as a spawn.
    launches = sum(int(n.get("subagent_launches", 0) or 0) for n in nodes)
    totals["subagent_children"] = len(distinct) + anonymous
    totals["subagent_launches"] = launches
    totals["subagents_spawned"] = max(len(distinct) + anonymous, launches)
    return totals


def validate_models(nodes, registered_model):
    bad = sorted({n["model"] for n in nodes if n["model"] != registered_model})
    if bad:
        raise InfraFailure(
            f"effective model(s) {bad} differ from registered "
            f"`{registered_model}` — run invalidated"
        )


def validate_efforts(nodes, registered_effort):
    """Effort parity with two capture modes. Nodes that report an effective
    effort must all match the registered value (`per_node` capture). The
    real Claude headless schema exposes no per-node effort field, so a
    transcript where NO node reports effort is accepted solely on the
    strength of the mandatory command-line pin (`{effort}`, enforced by
    `require_effort_pin` before any session is spawned) and recorded as
    `command_pin` capture. A transcript where only SOME nodes report effort
    is broken capture and invalidates the run. Returns the capture mode."""
    reported = [n for n in nodes if n.get("effort") not in (None, "")]
    if not reported:
        return "command_pin"
    if len(reported) != len(nodes):
        raise InfraFailure(
            f"{len(nodes) - len(reported)} of {len(nodes)} node(s) missing "
            f"effective effort while others report it — broken effort "
            f"capture; run invalidated"
        )
    bad = sorted({
        str(n["effort"]) for n in reported if n["effort"] != registered_effort
    })
    if bad:
        raise InfraFailure(
            f"effective effort(s) {bad} differ from registered "
            f"`{registered_effort}` — run invalidated"
        )
    return "per_node"


def require_effort_pin(cmd, what):
    """Effort must be pinned on the command line, never inherited from
    ambient defaults: refuse a command without the `{effort}` placeholder."""
    if not any("{effort}" in part for part in cmd):
        raise InfraFailure(
            f"{what} must pin effort via the {{effort}} placeholder — "
            f"ambient/default effort is not an accepted pin"
        )


def require_installation_mount(cmd):
    """An arm run must actually load its installation: refuse a backend
    command without the `{installation}` placeholder, or every arm would
    silently run the same bare backend and the comparison would never
    exercise the evaluated plugin content."""
    if not any("{installation}" in part for part in cmd):
        raise InfraFailure(
            "backend_cmd must mount the arm installation via the "
            "{installation} placeholder"
        )


def validate_abort_exits(config):
    """String codes would never match integer return codes (silently
    reclassifying genuine aborts as infra), and a scalar would crash
    tuple(): the field must be a list of non-boolean integers."""
    raw = config.get("workflow_abort_exit_codes", [])
    if (not isinstance(raw, list)
            or any(isinstance(code, bool) or not isinstance(code, int)
                   for code in raw)):
        raise InfraFailure(
            f"`workflow_abort_exit_codes` must be a list of integers, "
            f"got {raw!r}"
        )
    return tuple(raw)


def validate_timeout(config):
    """A nonpositive or non-numeric timeout would make _spawn record a
    counted workflow failure without ever launching the backend — a
    config fault, classified as infrastructure."""
    raw = config.get("timeout_seconds")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        raise InfraFailure(
            f"`timeout_seconds` must be a positive number, got {raw!r}"
        )
    return raw


def validate_arm_parity(config):
    """The registered protocol pins ONE runtime configuration: every arm
    must share the same model, effort, and workflow entrypoint, so
    plugin/installation content is the only difference between arms.
    Refuse mixed configs before any run."""
    arms = config["arms"]
    models = {arm.get("model") for arm in arms.values()}
    efforts = {arm.get("effort", "default") for arm in arms.values()}
    if len(models) > 1 or len(efforts) > 1:
        raise InfraFailure(
            f"arms differ in runtime configuration (models={sorted(map(str, models))}, "
            f"efforts={sorted(map(str, efforts))}) — only installation "
            f"content may differ between arms"
        )
    entrypoints = {arm.get("entrypoint") for arm in arms.values()}
    if len(entrypoints) > 1 or not next(iter(entrypoints), None):
        raise InfraFailure(
            "arms must share one non-empty workflow `entrypoint` — a bare "
            "or divergent entrypoint would compare different workflows, "
            "not the arms' installation content"
        )


def classify_stop(response, answered=True):
    """A pre-artifact stop is preserved verbatim and mechanically tagged so
    the analysis stage can count ritual stops (question-shaped pauses)
    against the zero-ritual-stop pass bar. Final semantic classification
    belongs to the sealed analysis, not the harness — this tag only keeps
    stops distinguishable and reviewable. `answered=False` marks the final
    stop of an exhausted run, which received no further continuation."""
    text = (response or "").strip()
    if not text:
        kind = "empty"
    elif "?" in text:
        kind = "question"
    else:
        kind = "statement"
    return {"response": text, "classification": kind, "answered": answered}


def snapshot_research(worktree):
    research = Path(worktree) / "thoughts" / "shared" / "research"
    if not research.is_dir():
        return {}
    return {p: p.stat().st_mtime for p in research.glob("*.md")}


def find_new_artifact(worktree, before):
    """Only documents created or modified during the run count."""
    research = Path(worktree) / "thoughts" / "shared" / "research"
    if not research.is_dir():
        return None
    fresh = [
        p for p in research.glob("*.md")
        if p not in before or p.stat().st_mtime > before[p]
    ]
    return max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None


def anonymize(text, run_id):
    # Fingerprint keys are masked across the WHOLE document with the
    # same pattern `assert_blind_scorable` enforces at the score
    # boundary \u2014 never only inside a well-formed frontmatter block. A
    # document whose metadata structure is malformed (unclosed or
    # missing delimiters \u2014 exactly the gate failures the diagnostic
    # axis scores) must still come out fully masked, or one broken
    # replicate would abort its whole blind-scoring batch.
    # Over-masking a look-alike prose line is the safe direction.
    text = text.lstrip("\ufeff")
    key_re = re.compile(
        "^\\ufeff?\\s*(" + "|".join(FINGERPRINT_KEYS) + ")\\s*:",
        re.IGNORECASE)
    lines = text.splitlines()
    for j, line in enumerate(lines):
        match = key_re.match(line)
        if match:
            lines[j] = (f"{match.group(1).lower()}: "
                        f"'[anonymized:{run_id}]'")
    body = "\n".join(lines)
    body = re.sub(
        r"^\*\*(Date|Researcher|Git Commit|Branch)\*\*:.*$",
        lambda m: f"**{m.group(1)}**: [anonymized:{run_id}]",
        body,
        flags=re.MULTILINE,
    )
    return body + ("\n" if not body.endswith("\n") else "")


def run_task(config, arm_name, task_path, repo_dir, output_dir, attempt=1,
             scheduled=False):
    arms = config.get("arms", {})
    if arm_name not in arms:
        # No record can be attributed to an unknown arm; fail with a
        # classified, actionable error instead of a KeyError traceback.
        raise InfraFailure(
            f"unknown arm `{arm_name}` — configured arms: {sorted(arms)}"
        )
    arm = arms[arm_name]
    # Absolute from the start: relative paths would resolve differently for
    # git (under the repo) and for this process (under the caller's cwd).
    output_dir = Path(output_dir).resolve()
    repo_dir = Path(repo_dir).resolve()
    run_id = uuid.uuid4().hex[:12]
    record = {
        "run_id": run_id,
        "arm": arm_name,
        "task": str(task_path),
        "repo_dir": str(repo_dir),
        "registered_model": arm["model"],
        "effort": arm.get("effort", "default"),
        "status": None,
        "interventions": 0,
        "interventions_log": [],
        "attempt": attempt,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    worktree = None
    all_nodes = []
    effort_modes = set()
    started = None
    try:
        # Immutable bindings recorded in the run record itself: orphan
        # adoption after a crash trusts a record only when these match the
        # current schedule's registered digests — a record produced under
        # an earlier task revision or runtime configuration is stale, not
        # adoptable.
        record["config_digest"] = config_digest(config)
        record["task_sha256"] = hashlib.sha256(
            read_task_bytes(task_path)).hexdigest()
        validate_arm_parity(config)
        record["standard_topology"] = validate_arm_topology(config)
        if record["standard_topology"] and not scheduled \
                and not config.get("nonstandard_config"):
            # Holdout runs exist ONLY inside the pre-registered schedule:
            # a direct --arm/--task run on a production config could add
            # observed runs or hit undesignated ablation tasks.
            raise InfraFailure(
                "production (holdout) configs execute only through "
                "--run-schedule — direct runs are limited to dev configs "
                "(`nonstandard_config: true`)"
            )
        validate_timeout(config)
        record["backend_version"] = verify_backend_version(config)
        # Every registered installation is verified before EVERY run, so
        # drift in any arm halts the experiment before more data is
        # collected — not only when that arm happens to be selected.
        for other_name, other_arm in sorted(config["arms"].items()):
            digest = verify_installation(other_name, other_arm)
            if other_name == arm_name:
                record["installation_sha256"] = digest
        prompt, task_text = extract_task_prompt(task_path)
        entrypoint = arm.get("entrypoint")
        if entrypoint:
            # The evaluated workflow must actually be invoked: a bare
            # question would measure generic backend behavior, not the arm.
            prompt = f"{entrypoint} {prompt}".strip()
            record["entrypoint"] = entrypoint
        sha = task_target_sha(task_text, task_path)
        worktree = make_worktree(
            repo_dir, sha, output_dir,
            name=canonical_repo_name(task_target_repo(task_text, task_path)))
        record["target_sha"] = sha
        record["worktree"] = str(worktree)
        # Neutral profile label: an arm-named CLAUDE_CONFIG_DIR would
        # reveal the arm to the session just like an arm-named mount.
        profile, mount = make_profile(output_dir, "session",
                                      arm["installation_dir"])
        mount_hash = hash_tree(mount)
        if mount_hash != arm["sha256"]:
            raise InfraFailure("mounted installation copy hash mismatch")
        require_effort_pin(config["backend_cmd"], "backend_cmd")
        require_installation_mount(config["backend_cmd"])
        cmd = expand_backend_cmd(config["backend_cmd"], mount,
                                 arm.get("effort", "default"))
        cmd = apply_sandbox(config, cmd, worktree, profile)
        env = backend_env(profile)
        abort_exits = validate_abort_exits(config)
        before = snapshot_research(worktree)
        started = time.time()
        # ONE run-level deadline shared by the initial session and every
        # continuation: a per-session reset would grant stop-prone arms up
        # to (1 + MAX_CONTINUATIONS)x the registered compute ceiling.
        deadline = started + config["timeout_seconds"]

        def _spawn(prompt_text, resume=None):
            remaining = deadline - time.time()
            if remaining <= 0:
                raise WorkflowFailure(
                    f"run-level deadline of {config['timeout_seconds']}s "
                    f"exhausted before the next session could start"
                )
            # A timeout/abort WorkflowFailure carries the partial transcript:
            # harvest its nodes before propagating so the counted failure
            # keeps the cost it already incurred. Runtime drift outranks the
            # workflow verdict — partial nodes on the wrong model/effort mean
            # the run is invalid (infra, re-executed), not a counted outcome.
            try:
                return spawn_session(cmd, prompt_text, worktree, env,
                                     remaining, resume=resume,
                                     workflow_abort_exits=abort_exits)
            except WorkflowFailure as wf:
                partial = parse_nodes_tolerant(wf.stdout)
                if not partial:
                    # A counted failure needs effective-runtime evidence
                    # from THE SESSION THAT FAILED — nodes from earlier
                    # sessions cannot vouch for a continuation that emitted
                    # nothing. But a timeout/abort is also a counted-never-
                    # replaced outcome, so it must not be silently re-
                    # executed either: the run BLOCKS pending operator
                    # investigation instead of biasing the cell one way or
                    # the other.
                    raise BlockingInfraFailure(
                        f"workflow-shaped failure with no accounting nodes "
                        f"from the failed session — no effective-runtime "
                        f"parity evidence to count it, and timeouts/aborts "
                        f"are never auto-replaced; run blocked pending "
                        f"investigation ({wf})"
                    ) from wf
                validate_models(partial, arm["model"])
                effort_modes.add(
                    validate_efforts(partial, arm.get("effort", "default")))
                all_nodes.extend(partial)
                raise

        # Durable journal BEFORE the backend launches: if the harness dies
        # after the session completes but before the terminal record is
        # written, the schedule finds this in-progress marker (with its
        # digest bindings) and blocks instead of silently executing an
        # extra observed replicate.
        record["status"] = "in_progress"
        atomic_write_text(out / f"run-{run_id}.json",
                          json.dumps(record, indent=2) + "\n")
        stdout = _spawn(prompt)
        session_id, nodes, response = parse_transcript(stdout)
        validate_models(nodes, arm["model"])
        effort_modes.add(validate_efforts(nodes, arm.get("effort", "default")))
        all_nodes.extend(nodes)
        artifact = find_new_artifact(worktree, before)
        while artifact is None and record["interventions"] < MAX_CONTINUATIONS:
            record["interventions"] += 1
            # The pre-artifact response IS the ritual-stop evidence: keep it
            # verbatim and tagged, or stops are uncountable afterwards.
            record["interventions_log"].append(classify_stop(response))
            stdout = _spawn(CONTINUATION_MESSAGE, resume=session_id)
            session_id, nodes, response = parse_transcript(stdout)
            validate_models(nodes, arm["model"])
            effort_modes.add(
                validate_efforts(nodes, arm.get("effort", "default")))
            all_nodes.extend(nodes)
            artifact = find_new_artifact(worktree, before)
        if len(effort_modes) > 1:
            raise InfraFailure(
                "inconsistent effort capture across sessions — run invalidated"
            )
        record["effort_capture"] = effort_modes.pop()
        record["wall_seconds"] = round(time.time() - started, 3)
        record["accounting"] = account(all_nodes)
        record["nodes"] = all_nodes
        if artifact is None:
            # The exhausted run's final response is itself a pre-artifact
            # stop — unanswered, but it must still be counted or the
            # intervention/ritual-stop metrics underreport by one.
            record["interventions_log"].append(
                classify_stop(response, answered=False))
        if arm.get("forbid_subagents") and record["accounting"]["subagents_spawned"]:
            # Pre-registered third-arm policy: the fleet-ablation arm may
            # not delegate at all, or its differences stop being
            # attributable to fleet removal. Counted, never replaced.
            raise WorkflowFailure(
                f"arm `{arm_name}` spawned "
                f"{record['accounting']['subagents_spawned']} subagent(s) — "
                f"forbidden by the pre-registered no-subagent policy"
            )
        if (record["accounting"]["subagent_launches"]
                > record["accounting"]["subagent_children"]):
            # Every node in the agent tree owes model/effort evidence. A
            # Task launch whose child emitted nothing leaves a subagent
            # with NO model-bearing nodes: the tree cannot be validated
            # for runtime parity, so the run is invalid — never accepted
            # as completed on main-context evidence alone.
            raise InfraFailure(
                f"subagent launch evidence exceeds model-bearing child "
                f"identities (launches="
                f"{record['accounting']['subagent_launches']}, children="
                f"{record['accounting']['subagent_children']}) — a spawned "
                f"subagent's effective model cannot be validated; run "
                f"invalidated"
            )
        if artifact is None:
            raise WorkflowFailure(
                f"no fresh research artifact after {MAX_CONTINUATIONS} continuations"
            )
        raw = artifact.read_text(encoding="utf-8")
        (out / f"run-{run_id}-raw.md").write_text(raw, encoding="utf-8")
        # The artifact contract is enforced by the harness itself, not by
        # trusting the session to have followed its instructions: a fresh
        # document that violates the contract is a COUNTED workflow
        # failure — the workflow produced the wrong artifact — never a
        # completed, scoreable replicate. The raw copy above is preserved
        # as evidence.
        contract_defects = artifact_validator.validate(
            artifact,
            expected_git_commit=_git(worktree, "rev-parse", "HEAD"),
            expected_repository=task_target_repo(task_text, task_path),
            enforce_filename=True,
        )
        if contract_defects:
            record["artifact_defects"] = contract_defects
            # Registered amendment (owner decision, 2026-07-28, recorded
            # before unsealing): the gate rejection stays a counted
            # workflow failure for the primary end-to-end outcome — no
            # repair, no re-run — but the document's CONTENT is still
            # blind-scored on a separate diagnostic axis, so the
            # anonymized diagnostic copy and its digest are preserved
            # alongside the raw evidence.
            diag_text = anonymize(raw, run_id)
            (out / f"run-{run_id}-diag.md").write_text(diag_text,
                                                       encoding="utf-8")
            record["diagnostic_sha256"] = hashlib.sha256(
                diag_text.encode("utf-8")
            ).hexdigest()
            shown = "; ".join(contract_defects[:5])
            more = " …" if len(contract_defects) > 5 else ""
            raise WorkflowFailure(
                f"artifact violates the research artifact contract: "
                f"{shown}{more}"
            )
        anon_text = anonymize(raw, run_id)
        (out / f"run-{run_id}-anon.md").write_text(anon_text, encoding="utf-8")
        # The digest recorded here is what scoring later verifies: a scored
        # document must be the exact artifact this run produced.
        record["artifact_sha256"] = hashlib.sha256(
            anon_text.encode("utf-8")
        ).hexdigest()
        record["status"] = "completed"
    except WorkflowFailure as exc:
        record["status"] = "workflow_failure"
        record["failure"] = str(exc)
    except BlockingInfraFailure as exc:
        record["status"] = "infra_failure"
        record["blocking"] = True
        record["failure"] = str(exc)
    except InfraFailure as exc:
        record["status"] = "infra_failure"
        record["failure"] = str(exc)
    finally:
        # Failed runs still owe their full cost: tree-wide accounting for
        # every completed session is preserved even when the workflow fails
        # mid-flight (timeout, abort, no artifact).
        if all_nodes and "accounting" not in record:
            record["accounting"] = account(all_nodes)
            record["nodes"] = all_nodes
        # Counted failures must also record which effort evidence accepted
        # them (per_node vs command_pin) — the capture mode is part of the
        # audit trail, not only of completed runs.
        if "effort_capture" not in record and len(effort_modes) == 1:
            record["effort_capture"] = effort_modes.pop()
        if started is not None and "wall_seconds" not in record:
            record["wall_seconds"] = round(time.time() - started, 3)
        if worktree is not None:
            remove_worktree(repo_dir, worktree)
    atomic_write_text(out / f"run-{run_id}.json",
                      json.dumps(record, indent=2) + "\n")
    return record


def run_task_with_retries(config, arm_name, task_path, repo_dir, output_dir,
                          scheduled=False):
    """Registered protocol: an infrastructure failure invalidates the run and
    the run is re-executed, automatically and bounded — workflow failures are
    counted, never replaced. Every attempt's record is written to disk."""
    raw_retries = config.get("max_infra_retries", DEFAULT_MAX_INFRA_RETRIES)
    # A real integer, not a coercible value: int() would turn 0.5 into 0
    # (silently deleting all retries) and True into 1.
    if (isinstance(raw_retries, bool)
            or not isinstance(raw_retries, int)
            or raw_retries < 0):
        raise InfraFailure(
            f"`max_infra_retries` must be a nonnegative integer, "
            f"got {raw_retries!r}"
        )
    max_retries = raw_retries
    attempts = []
    for attempt in range(1, max_retries + 2):
        record = run_task(config, arm_name, task_path, repo_dir, output_dir,
                          attempt=attempt, scheduled=scheduled)
        attempts.append(record)
        if record["status"] != "infra_failure":
            break
        if record.get("blocking"):
            # A workflow-shaped failure without runtime evidence can
            # neither be counted nor auto-replaced: stop retrying and
            # surface the block for operator investigation.
            break
    return attempts


def make_schedule(config, task_paths, replicates, seed, allow_nonstandard=False):
    """Pre-registered run schedule: every arm x its task list x `replicates`,
    randomized and interleaved with a RECORDED seed, so the execution order
    is fixed before any run and reproducible afterwards. The protocol fixes
    REGISTERED_REPLICATES per cell — any other count must be explicitly
    marked nonstandard (dev-set tuning only) and the schedule carries that
    mark. A no-subagent (ablation) arm must be EXPLICITLY scoped to its two
    designated tasks via `schedule_tasks` — defaulting it to the full task
    list would silently widen the pre-registered third-arm comparison."""
    if (isinstance(replicates, bool) or not isinstance(replicates, int)
            or replicates < 1):
        raise InfraFailure(
            f"`replicates` must be a positive integer, got {replicates!r} — "
            f"zero entries would let an empty schedule complete"
        )
    tasks = [str(Path(t)) for t in task_paths]
    if len(set(tasks)) != len(tasks):
        raise InfraFailure("duplicate task paths in the schedule task list")
    # The schedule binds task CONTENTS, not just paths: an edited prompt or
    # re-pinned target-sha after registration must break reconstruction,
    # never silently mix revisions inside one experimental cell.
    task_digests = {}
    for task in tasks:
        task_digests[task] = hashlib.sha256(read_task_bytes(task)).hexdigest()
    standard_topology = _standard_topology(config)
    if not allow_nonstandard:
        if config.get("nonstandard_config"):
            raise InfraFailure(
                "a standard (holdout) schedule cannot be generated from a "
                "dev config (`nonstandard_config: true`) — production "
                "configs must register the full topology and sandbox"
            )
        if replicates != REGISTERED_REPLICATES:
            raise InfraFailure(
                f"the registered protocol fixes {REGISTERED_REPLICATES} "
                f"replicates per arm/task cell (got {replicates}); "
                f"nonstandard counts are for dev-set tuning only and must "
                f"be explicitly allowed"
            )
        if not standard_topology:
            raise InfraFailure(
                "a standard (holdout) schedule requires the registered "
                "three-arm topology — arms `baseline` and `candidate` (by "
                "those exact names) plus exactly one no-subagent ablation "
                "arm; dev-set tuning schedules must be explicitly marked "
                "nonstandard"
            )
        if len(tasks) != REGISTERED_HOLDOUT_TASKS:
            raise InfraFailure(
                f"a standard (holdout) schedule requires exactly "
                f"{REGISTERED_HOLDOUT_TASKS} distinct holdout tasks, got "
                f"{len(tasks)}; dev-set tuning schedules must be explicitly "
                f"marked nonstandard"
            )
        # Full coverage matrix against the CANONICAL registered sets, not
        # cardinality: exactly one task per numbered plan archetype and
        # coverage of every registered eval repository — six free-form
        # labels across arbitrary repos must never pass as standard.
        seen_numbers = {}
        seen_repos = set()
        for task in tasks:
            cov_text = read_task_text(task)
            cov_match = re.search(
                r"^archetype:\s*\"?([^\"\n]+?)\"?\s*$",
                cov_text, re.MULTILINE)
            if not cov_match:
                raise InfraFailure(
                    f"{task}: no `archetype` frontmatter — a standard "
                    f"schedule validates the full coverage matrix"
                )
            label = cov_match.group(1)
            num_match = re.match(r"\s*(\d+)", label)
            number = int(num_match.group(1)) if num_match else None
            keyword = REGISTERED_HOLDOUT_ARCHETYPE_KEYWORDS.get(number)
            if keyword is None or keyword not in label.lower():
                raise InfraFailure(
                    f"{task}: archetype `{label}` is not one of the six "
                    f"registered archetypes — the coverage matrix is "
                    f"canonical, not free-form"
                )
            if number in seen_numbers:
                raise InfraFailure(
                    f"a standard schedule requires exactly one task per "
                    f"archetype — archetype {number} appears in both "
                    f"{seen_numbers[number]} and {task}"
                )
            seen_numbers[number] = task
            full_repo = task_target_repo(cov_text, task)
            repo_name = canonical_repo_name(full_repo)
            if repo_name not in REGISTERED_HOLDOUT_REPOS:
                raise InfraFailure(
                    f"{task}: target-repo `{full_repo}` is not a registered "
                    f"eval repository {REGISTERED_HOLDOUT_REPOS}"
                )
            seen_repos.add(repo_name)
        if set(seen_numbers) != set(REGISTERED_HOLDOUT_ARCHETYPE_KEYWORDS):
            raise InfraFailure(
                f"a standard schedule requires exactly one task per "
                f"archetype 1-6, got archetypes {sorted(seen_numbers)}"
            )
        if seen_repos != set(REGISTERED_HOLDOUT_REPOS):
            raise InfraFailure(
                f"a standard schedule must cover the registered "
                f"repositories {REGISTERED_HOLDOUT_REPOS}, got "
                f"{sorted(seen_repos)}"
            )
        # Holdout tasks are the SEALED prompts: every production task must
        # appear in the registered atomic-seal manifest with a matching
        # content digest — arbitrary files with plausible frontmatter can
        # never run as protocol-valid holdout tasks.
        seal_path = config.get("seal_manifest")
        registered_seal = config.get("seal_package_sha256")
        if not seal_path or not registered_seal:
            raise InfraFailure(
                "a standard (holdout) schedule requires the registered "
                "atomic seal (`seal_manifest` + `seal_package_sha256` in "
                "the config)"
            )
        try:
            seal_bytes = Path(seal_path).read_bytes()
        except OSError as exc:
            raise InfraFailure(
                f"cannot read seal manifest {seal_path}: {exc}"
            ) from exc
        if hashlib.sha256(seal_bytes).hexdigest() != registered_seal:
            raise InfraFailure(
                "seal manifest does not match the registered "
                "`seal_package_sha256` — a recomputed or altered seal is "
                "refused"
            )
        seal_doc_sched, sealed_files = parse_seal_manifest(seal_bytes,
                                                           seal_path)
        validate_sealed_judge_config(config, seal_doc_sched)
        for task in tasks:
            if sealed_files.get(Path(task).name) != task_digests[task]:
                raise InfraFailure(
                    f"{task}: not sealed in the registered package — "
                    f"holdout tasks must be the exact sealed prompts"
                )
    validate_arm_parity(config)
    entries = []
    for arm_name in sorted(config["arms"]):
        arm = config["arms"][arm_name]
        if arm.get("schedule_tasks") is not None and not arm.get("forbid_subagents"):
            raise InfraFailure(
                f"arm `{arm_name}`: `schedule_tasks` scoping is reserved for "
                f"the no-subagent ablation arm — baseline/candidate must run "
                f"the complete task list"
            )
        if arm.get("forbid_subagents"):
            if "schedule_tasks" not in arm:
                raise InfraFailure(
                    f"arm `{arm_name}` (no-subagent ablation) requires "
                    f"explicit `schedule_tasks` — the plan scopes the third "
                    f"arm to its two designated tasks"
                )
            if (len(arm["schedule_tasks"]) != 2
                    or len(set(arm["schedule_tasks"])) != 2):
                raise InfraFailure(
                    f"arm `{arm_name}` (no-subagent ablation) must be scoped "
                    f"to exactly 2 DISTINCT designated tasks, got "
                    f"{arm['schedule_tasks']!r}"
                )
            if not allow_nonstandard:
                # The designation is not free: the plan fixes the third arm
                # to specific archetypes, validated from the tasks' own
                # `archetype` frontmatter.
                found = []
                for scoped in arm["schedule_tasks"]:
                    scoped_text = read_task_text(scoped)
                    match = re.search(
                        r"^archetype:\s*\"?([^\"\n]+?)\"?\s*$",
                        scoped_text, re.MULTILINE)
                    if not match:
                        raise InfraFailure(
                            f"{scoped}: no `archetype` frontmatter — the "
                            f"ablation scope is bound to registered "
                            f"archetypes"
                        )
                    found.append(match.group(1))
                for registered in REGISTERED_ABLATION_ARCHETYPES:
                    if not any(registered in f for f in found):
                        raise InfraFailure(
                            f"ablation arm must be scoped to the registered "
                            f"archetypes {REGISTERED_ABLATION_ARCHETYPES}, "
                            f"got {found!r}"
                        )
        arm_tasks = [str(Path(t)) for t in arm.get("schedule_tasks", tasks)]
        unknown = [t for t in arm_tasks if t not in tasks]
        if unknown:
            raise InfraFailure(
                f"arm `{arm_name}` schedule_tasks not in the task list: {unknown}"
            )
        for task in arm_tasks:
            entries.extend(
                {"arm": arm_name, "task": task} for _ in range(replicates)
            )
    rng = random.Random(seed)
    rng.shuffle(entries)
    for index, entry in enumerate(entries):
        entry["index"] = index
    return {
        "seed": seed,
        "replicates": replicates,
        "task_digests": task_digests,
        # The explicit override is itself part of the marker: an
        # allow-nonstandard schedule that happens to be standard-shaped
        # must not masquerade as holdout (and must reconstruct with the
        # same override on --run-schedule).
        "nonstandard": (bool(allow_nonstandard)
                        or replicates != REGISTERED_REPLICATES
                        or not standard_topology
                        or len(tasks) != REGISTERED_HOLDOUT_TASKS
                        or bool(config.get("nonstandard_config"))),
        "tasks": tasks,
        "arms": sorted(config["arms"]),
        "config_digest": config_digest(config),
        "entries": entries,
    }


def schedule_digest(schedule):
    """Digest of the ENTIRE schedule object (entries, tasks, seed, config
    digest). This is the resume identity: seed + config alone cannot
    distinguish schedules over different task sets whose randomized entries
    happen to share a prefix."""
    return hashlib.sha256(
        json.dumps(schedule, sort_keys=True).encode("utf-8")
    ).hexdigest()


def verify_results_against_records(results, entries, out_dir, require_all):
    """The manifest is a convenience view; immutable per-run records are the
    source of truth. Every manifest result must align with its schedule
    entry and match its `run-<id>.json` record — a fabricated or trimmed
    manifest (invented run_ids, flipped statuses, forged digests, deleted
    results) is refused. `require_all` additionally demands one result per
    schedule entry (complete-experiment coverage for scoring)."""
    if require_all and len(results) != len(entries):
        raise InfraFailure(
            "manifest results do not cover every schedule entry — a "
            "post-hoc subset cannot pass as the complete experiment"
        )
    if len(results) > len(entries):
        raise InfraFailure("manifest holds more results than the schedule")
    for done, entry in zip(results, entries):
        if (done.get("index"), done.get("arm"), done.get("task")) != (
                entry["index"], entry["arm"], entry["task"]):
            raise InfraFailure(
                "manifest results misaligned with the schedule entries"
            )
        record_path = Path(out_dir) / f"run-{done.get('run_id')}.json"
        if not record_path.exists():
            raise InfraFailure(
                f"manifest result {done.get('index')} has no run record "
                f"on disk — fabricated or foreign manifest refused"
            )
        run_record = load_json_object(record_path, "run record")
        if (run_record.get("arm") != done.get("arm")
                or run_record.get("task") != done.get("task")
                or run_record.get("status") != done.get("status")
                or run_record.get("artifact_sha256")
                != done.get("artifact_sha256")
                or run_record.get("diagnostic_sha256")
                != done.get("diagnostic_sha256")):
            raise InfraFailure(
                f"manifest result {done.get('index')} does not match its "
                f"immutable run record — edited manifest refused"
            )


def run_schedule(config, schedule_path, repos, output_dir, task_paths):
    """Execute a pre-registered schedule in its recorded order. The expected
    schedule is RECONSTRUCTED from the registered config, the operator-
    supplied task set, and the recorded seed/replicates — the schedule
    file's own arms/tasks/entries are never trusted, so an edited file
    (dropped arm or task, truncated entries, reordering) is refused before
    any run. Progress is persisted to the manifest after every entry, and
    an interrupted schedule resumes at the first unfinished entry — never
    from index 0, so no extra runs are created after outcomes were
    observed."""
    schedule = load_json_object(schedule_path, "schedule")
    if schedule.get("config_digest") != config_digest(config):
        raise InfraFailure(
            "registered runtime configuration changed since this schedule "
            "was created (config digest mismatch) — a schedule binds ONE "
            "pre-registered configuration for the whole experiment; "
            "regenerate the schedule if the change was intentional"
        )
    rebuilt = make_schedule(
        config, task_paths, schedule.get("replicates"), schedule.get("seed"),
        allow_nonstandard=schedule.get("nonstandard", False),
    )
    if rebuilt != schedule:
        raise InfraFailure(
            "schedule does not match the one reconstructed from the "
            "registered configuration, task set, replicates, and seed — "
            "edited/tampered schedules are refused; regenerate with "
            "--make-schedule"
        )
    entries = schedule["entries"]
    sched_digest = schedule_digest(schedule)
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "schedule-manifest.json"
    results = []
    if manifest_path.exists():
        prior = load_json_object(manifest_path, "schedule manifest")
        if prior.get("schedule_digest") != sched_digest:
            # The FULL schedule digest is the resume identity: seed +
            # config alone cannot distinguish schedules over different
            # task sets whose randomized entries share a prefix.
            raise InfraFailure(
                "existing manifest in the output directory belongs to a "
                "different schedule (schedule digest mismatch) — results "
                "from different schedules or configurations must not be "
                "mixed"
            )
        results = list(prior.get("results", []))
        verify_results_against_records(results, entries, out,
                                       require_all=False)

    def write_manifest(complete):
        manifest = {
            "schedule": str(schedule_path),
            "seed": schedule["seed"],
            "schedule_digest": sched_digest,
            "config_digest": schedule["config_digest"],
            "replicates": schedule["replicates"],
            "nonstandard": schedule.get("nonstandard", False),
            "results": results,
            "complete": complete,
        }
        atomic_write_text(manifest_path,
                          json.dumps(manifest, indent=2) + "\n")
        return manifest

    referenced_runs = {r.get("run_id") for r in results}
    for entry in entries[len(results):]:
        # The registered holdout spans several repositories: each task is
        # routed to the clone registered for its own `target-repo`.
        entry_repo = resolve_repo(entry["task"], repos)
        # Crash window: run_task_with_retries atomically wrote a terminal
        # run record, but the process died before the manifest update. The
        # backend already ran for this entry — re-executing it would add an
        # unaccounted observed replicate to the cell. A uniquely matching
        # orphan record (terminal status, this entry's arm+task, not yet
        # referenced by the manifest) is adopted instead of launched again.
        orphans = []
        inflight = []
        for record_path in sorted(out.glob("run-*.json")):
            if record_path.name.count("-") != 1:
                continue
            orphan = load_json_object(record_path, "run record")
            if (orphan.get("run_id") in referenced_runs
                    or orphan.get("arm") != entry["arm"]
                    or orphan.get("task") != entry["task"]
                    # Stale records are not orphans: adoption requires the
                    # record's own immutable bindings to match the current
                    # schedule — same task contents (digest covers the
                    # pinned target-sha in frontmatter) and same registered
                    # runtime configuration.
                    or orphan.get("task_sha256")
                    != schedule["task_digests"][entry["task"]]
                    or orphan.get("config_digest")
                    != schedule["config_digest"]):
                continue
            if orphan.get("status") in ("completed", "workflow_failure"):
                orphans.append(orphan)
            elif orphan.get("status") == "in_progress":
                # The pre-spawn journal: the backend may have executed
                # without leaving a terminal outcome. Neither adoptable nor
                # safely re-runnable — the schedule blocks for
                # investigation.
                inflight.append(record_path.name)
        if inflight:
            write_manifest(False)
            raise InfraFailure(
                f"schedule entry {entry['index']} ({entry['arm']} / "
                f"{entry['task']}) has in-progress run journal(s) without "
                f"a terminal outcome ({', '.join(sorted(inflight))}) — the "
                f"backend may have executed; investigate, then delete the "
                f"journal record(s) to explicitly authorize re-running "
                f"this entry"
            )
        if len(orphans) > 1:
            raise InfraFailure(
                f"schedule entry {entry['index']} ({entry['arm']} / "
                f"{entry['task']}) has {len(orphans)} unreferenced terminal "
                f"run records — ambiguous orphan adoption; the output "
                f"directory holds runs the schedule cannot attribute"
            )
        if orphans:
            final = orphans[0]
        else:
            final = run_task_with_retries(
                config, entry["arm"], entry["task"], entry_repo, output_dir,
                scheduled=True
            )[-1]
        if final["status"] == "infra_failure":
            # Entry unfinished: persist progress so a re-run resumes HERE.
            write_manifest(False)
            reason = ("run blocked pending operator investigation — "
                      "workflow-shaped failure without runtime evidence"
                      if final.get("blocking")
                      else "infra retries exhausted")
            raise InfraFailure(
                f"schedule interrupted at entry {entry['index']} "
                f"({entry['arm']} / {entry['task']}): {reason}; progress "
                f"persisted — re-run --run-schedule to resume at this entry"
            )
        results.append({
            "index": entry["index"],
            "arm": entry["arm"],
            "task": entry["task"],
            "run_id": final["run_id"],
            "status": final["status"],
            "attempts": final.get("attempt", 1),
            "artifact_sha256": final.get("artifact_sha256"),
            # Registered diagnostic axis (2026-07-28): the digest of a
            # gate-failed replicate's anonymized diagnostic copy — the
            # scoring side derives the diagnostic batch from this.
            "diagnostic_sha256": final.get("diagnostic_sha256"),
            "task_sha256": schedule["task_digests"][entry["task"]],
        })
        referenced_runs.add(final["run_id"])
        write_manifest(False)
    return write_manifest(True)


def _fetch_live_source(fetch_cmd, url, timeout):
    """Source drift is verified against the LIVE authoritative source: the
    harness itself fetches each sealed URL through the registered
    `drift_fetch_cmd`. An operator-supplied local copy is never drift
    evidence — it could be the sealed snapshot itself."""
    dest_dir = Path(tempfile.mkdtemp(prefix="rpa-refetch-"))
    dest = dest_dir / "fetched"
    cmd = [part.replace("{url}", url).replace("{dest}", str(dest))
           for part in fetch_cmd]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise InfraFailure(f"live-source fetch timed out for {url}") from exc
    except OSError as exc:
        raise InfraFailure(
            f"cannot execute drift_fetch_cmd for {url}: {exc}") from exc
    if proc.returncode != 0:
        raise InfraFailure(
            f"live-source fetch failed for {url} (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[:200]}"
        )
    try:
        return dest.read_bytes()
    except OSError as exc:
        raise InfraFailure(
            f"drift_fetch_cmd produced no file for {url}: {exc}") from exc


def _sealed_bytes(path, seal_files, key=None):
    """Judge inputs (judge prompt, task contexts, external snapshots) are
    bound to the atomic seal: the bytes actually read must match the digest
    recorded in the sealed package's manifest, and each file is read exactly
    once before any session launches — an edit after sealing or between
    judge calls is refused, never silently mixed into the batch. Manifest
    keys are PACKAGE-RELATIVE paths (`key`), not basenames — two
    `index.html` files in different snapshot subdirectories are distinct
    sealed artifacts."""
    data = read_input_bytes(path, "sealed judge input")
    if hashlib.sha256(data).hexdigest() != seal_files.get(key or Path(path).name):
        raise InfraFailure(
            f"{path}: contents differ from the atomic-seal manifest — "
            f"judge inputs must be the sealed artifacts"
        )
    return data


def _read_sealed(path, seal_files):
    return _sealed_bytes(path, seal_files).decode("utf-8")


def _sealed_snapshot_items(snap_root, seal_files):
    """Enumerate a sealed snapshot FROM THE SEAL, not from what happens to
    remain on disk: a sealed file deleted from the supplied copy must be
    detected, and an extra unsealed file must never ride along. Returns
    (path, relative_path, seal_key) triples in sealed order."""
    snap_root = Path(snap_root)
    if snap_root.is_file():
        key = snap_root.name
        if key not in seal_files:
            raise InfraFailure(
                f"{snap_root}: snapshot not in the atomic-seal manifest"
            )
        return [(snap_root, Path(snap_root.name), key)]
    prefix = snap_root.name + "/"
    sealed_keys = sorted(k for k in seal_files if k.startswith(prefix))
    if not sealed_keys:
        raise InfraFailure(
            f"{snap_root}: no sealed snapshot entries under `{prefix}` in "
            f"the atomic-seal manifest"
        )
    local = {}
    for item in snap_root.rglob("*"):
        if item.is_file():
            rel = item.relative_to(snap_root)
            local[(Path(snap_root.name) / rel).as_posix()] = (item, rel)
    missing = [k for k in sealed_keys if k not in local]
    extra = [k for k in sorted(local) if k not in sealed_keys]
    if missing or extra:
        raise InfraFailure(
            f"{snap_root}: snapshot file set differs from the seal "
            f"(missing {missing}, extra {extra}) — the complete frozen "
            f"evidence is required"
        )
    return [(local[k][0], local[k][1], k) for k in sealed_keys]


def assert_blind_scorable(doc_path):
    """Blinding is enforced at the score boundary itself: a raw runner
    artifact or any document whose fingerprint fields are not masked is
    refused, so a CLI input mistake cannot leak identity to the judge."""
    path = Path(doc_path)
    if path.name.endswith("-raw.md"):
        raise InfraFailure(
            f"{doc_path}: raw runner artifact — blind scoring requires the "
            f"anonymized copy (`run-<id>-anon.md`)"
        )
    text = read_input_text(path, "scoring document")
    # Fingerprint keys are scanned across the WHOLE document, not only a
    # frontmatter block assumed at line 0: a BOM or blank line before the
    # opening `---` must not smuggle researcher/commit/branch identity
    # past the blind judge. Overmatching refuses a scorable document
    # (operator re-anonymizes); undermatching unblinds the judge.
    key_re = re.compile(
        "^\\ufeff?\\s*(" + "|".join(FINGERPRINT_KEYS) + ")\\s*:",
        re.IGNORECASE)
    for line in text.splitlines():
        match = key_re.match(line)
        if match and "[anonymized:" not in line:
            raise InfraFailure(
                f"{doc_path}: fingerprint key `{match.group(1).lower()}` "
                f"is not anonymized — blind scoring refused"
            )
    for match in re.finditer(
        r"^\*\*(Date|Researcher|Git Commit|Branch)\*\*:(.*)$", text, re.MULTILINE
    ):
        if "[anonymized:" not in match.group(2):
            raise InfraFailure(
                f"{doc_path}: fingerprint line `**{match.group(1)}**` is not "
                f"anonymized — blind scoring refused"
            )
    return text


def score(config, doc_paths, judge_prompt_path, output_dir,
          evidence_repo=None, evidence_sha=None, scoring_seed=None,
          manifest_path=None, allow_unscheduled=False, evidence_repos=None,
          task_contexts=None, seal_manifest_path=None, task_snapshots=None,
          drift_report_path=None, score_task_paths=None,
          diagnostic_axis=False):
    """One fresh pinned backend session per document. The judge's full
    response text is preserved on disk — it IS the scoring artifact. Judge
    prompts live in the sealed package and are passed in at runtime.
    Documents are presented in a RANDOMIZED order derived from the recorded
    `scoring_seed`, so time-dependent judge/service drift cannot stay
    correlated with an arm, and the sequence stays reproducible.

    Two roles: without `evidence_repo` the judge is a blind SCORER (empty
    cwd outside the experiment tree, all inspection tools denied). With
    `evidence_repo` + `evidence_sha` the judge is an evidence VERIFIER: its
    cwd is a disposable worktree of the frozen evidence repo at the pinned
    sha, read-only tools allowed, so file-and-line citations can actually
    be checked. The two evidence arguments are all-or-nothing: one without
    the other is an operator mistake, never a silent role choice."""
    if bool(evidence_repo) != bool(evidence_sha):
        raise InfraFailure(
            "evidence_repo and evidence_sha must be supplied together "
            "(all-or-nothing) — one without the other silently changes the "
            "judge role"
        )
    if scoring_seed is None:
        raise InfraFailure(
            "`scoring_seed` is required — the presentation order must be "
            "randomized from a recorded seed"
        )
    if manifest_path is None and not allow_unscheduled:
        raise InfraFailure(
            "score mode requires the schedule manifest so every scheduled "
            "replicate is scored exactly once — ad-hoc/dev scoring must be "
            "explicitly marked unscheduled"
        )
    if diagnostic_axis and manifest_path is None:
        raise InfraFailure(
            "`diagnostic_axis` is defined only for manifest-bound scoring "
            "— the diagnostic batch is derived from the manifest's "
            "gate-failed replicates"
        )
    doc_evidence = None
    role = "verifier" if (evidence_repo or evidence_repos is not None) else "scorer"
    if manifest_path is not None:
        # No post-hoc selection: the supplied documents must cover every
        # completed scheduled replicate exactly once — no subsets, no
        # duplicates, no extras.
        manifest = load_json_object(manifest_path, "schedule manifest")
        if not manifest.get("complete"):
            raise InfraFailure(
                "schedule manifest is incomplete — score only after the "
                "whole schedule has run"
            )
        # The manifest's own flags and result list are not trusted: it must
        # match its schedule (digest + one result per entry) and every
        # result must match its immutable run record, or a trimmed/edited
        # manifest could pass a post-hoc subset off as the experiment.
        sched_ref = manifest.get("schedule")
        if not sched_ref or not Path(sched_ref).exists():
            raise InfraFailure(
                "manifest's schedule file not found — scoring cannot verify "
                "the manifest against its schedule"
            )
        sched_obj = load_json_object(sched_ref, "schedule")
        if manifest.get("schedule_digest") != schedule_digest(sched_obj):
            raise InfraFailure(
                "manifest does not match its schedule (schedule digest "
                "mismatch)"
            )
        verify_results_against_records(
            manifest.get("results", []), sched_obj.get("entries", []),
            Path(manifest_path).parent, require_all=True
        )
        # Judges run under the SAME sealed configuration the schedule
        # bound: judge command/model/effort, backend version, and policy
        # fields are all in the digest.
        if manifest.get("config_digest") != config_digest(config):
            raise InfraFailure(
                "registered runtime configuration changed since the "
                "scheduled runs (config digest mismatch) — judges must run "
                "under the same sealed configuration"
            )
        completed = [r for r in manifest.get("results", [])
                     if r.get("status") == "completed"]
        # The scoreable set: completed replicates' anonymized artifacts.
        # Registered amendment (owner decision, 2026-07-28, recorded
        # before unsealing): with `diagnostic_axis`, gate-failed
        # replicates' diagnostic copies join the batch — their gate
        # rejection stays a counted workflow failure for the PRIMARY
        # end-to-end outcome, but every produced document's CONTENT is
        # blind-scored on this separate diagnostic axis, so format
        # discipline and content quality are measured independently.
        scoreable = [(r, f"run-{r['run_id']}-anon.md",
                      r.get("artifact_sha256")) for r in completed]
        if diagnostic_axis:
            scoreable += [
                (r, f"run-{r['run_id']}-diag.md",
                 r.get("diagnostic_sha256"))
                for r in manifest.get("results", [])
                if r.get("status") == "workflow_failure"
                and r.get("diagnostic_sha256")
            ]
        for r, _, _ in scoreable:
            recorded_task = r.get("task_sha256")
            if recorded_task is not None:
                actual_task = hashlib.sha256(
                    read_task_bytes(r["task"])
                ).hexdigest()
                if actual_task != recorded_task:
                    raise InfraFailure(
                        f"{r['task']}: task file changed since the "
                        f"scheduled run — evidence selection and protocol "
                        f"binding would use a different task"
                    )
        # The schedule file is mutable: trimming it TOGETHER with the
        # manifest and recomputing the digest would otherwise pass. The
        # expected schedule is therefore reconstructed from the registered
        # config and the operator-supplied registered task set.
        if score_task_paths is None:
            raise InfraFailure(
                "manifest-bound scoring requires the registered task set "
                "(--tasks) to reconstruct and verify the schedule"
            )
        rebuilt_sched = make_schedule(
            config, score_task_paths, sched_obj.get("replicates"),
            sched_obj.get("seed"),
            allow_nonstandard=sched_obj.get("nonstandard", False),
        )
        if rebuilt_sched != sched_obj:
            raise InfraFailure(
                "schedule does not match the one reconstructed from the "
                "registered configuration and task set — trimmed or edited "
                "schedules are refused at scoring time"
            )
        expected_names = sorted(name for _, name, _ in scoreable)
        supplied_names = sorted(Path(d).name for d in doc_paths)
        if supplied_names != expected_names:
            raise InfraFailure(
                f"scoring inputs must cover every scoreable scheduled "
                f"replicate exactly once — expected {expected_names}, "
                f"got {supplied_names}"
            )
        # Identity by name is not enough: the contents must be the exact
        # artifact the run produced, or an edited/substituted file with the
        # right name would be scored as that replicate.
        digest_by_name = {name: digest for _, name, digest in scoreable}
        for doc in doc_paths:
            actual = hashlib.sha256(
                read_input_bytes(doc, "scoring document")).hexdigest()
            if actual != digest_by_name.get(Path(doc).name):
                raise InfraFailure(
                    f"{doc}: contents differ from the artifact digest "
                    f"recorded at run time — scored documents must be the "
                    f"exact run artifacts"
                )
        # An artifact is not required to restate its question: each judge
        # gets ITS document's task-specific sealed context (task prompt +
        # ground-truth note), routed via the manifest's run→task mapping.
        if task_contexts is None:
            raise InfraFailure(
                "manifest-bound scoring requires per-task sealed contexts "
                "(task_contexts: TASKFILE=CONTEXT) so each judge scores "
                "against its own task's prompt and ground truth"
            )
        context_by_doc = {}
        task_by_doc = {}
        for r, doc_name, _ in scoreable:
            task_name = Path(r["task"]).name
            if task_name not in task_contexts:
                raise InfraFailure(
                    f"no sealed scoring context supplied for task "
                    f"{task_name} — every scored task needs one"
                )
            context_by_doc[doc_name] = task_contexts[task_name]
            task_by_doc[doc_name] = r["task"]
        if evidence_repo or evidence_sha:
            raise InfraFailure(
                "manifest-bound verification checks each document against "
                "ITS OWN task's pinned repo@sha — pass `evidence_repos` "
                "(NAME=PATH mapping), not a single evidence repo/sha"
            )
        snapshot_by_doc = {}
        snap_task_by_doc = {}
        inconclusive_docs = set()
        drift_notes = {}
        drift_report = None
        if drift_report_path is not None:
            drift_report = load_json_object(drift_report_path,
                                            "drift report")
        doc_evidence = {} if evidence_repos is not None else None
        for r, doc_name, _ in scoreable:
            task_text = read_task_text(r["task"])
            if evidence_repos is not None:
                # A holdout batch spans several target repositories: every
                # document is verified against the worktree of its own
                # task's pinned repo@sha, never one shared checkout.
                repo_name = task_target_repo(task_text, r["task"])
                evidence_clone = resolve_repo_mapping(
                    repo_name, evidence_repos, "--evidence-repos")
                doc_evidence[doc_name] = (
                    evidence_clone,
                    task_target_sha(task_text, r["task"]),
                )
            # External-context tasks apply to BOTH judge roles: the
            # verifier checks claims against the frozen snapshots, and the
            # source-drift gate excludes drifted tasks from scorer and
            # verifier alike.
            if re.search(r"^external-snapshots:\s*true\s*$", task_text,
                         re.MULTILINE):
                task_name = Path(r["task"]).name
                if not task_snapshots or task_name not in task_snapshots:
                    raise InfraFailure(
                        f"{r['task']}: task requires sealed external "
                        f"snapshots — supply --task-snapshots "
                        f"{task_name}=<sealed snapshot file/dir>"
                    )
                snapshot_by_doc[doc_name] = task_snapshots[task_name]
                snap_task_by_doc[doc_name] = task_name
    else:
        context_by_doc = None
        task_by_doc = None
        snapshot_by_doc = {}
        inconclusive_docs = set()
        drift_notes = {}
        if evidence_repos is not None:
            raise InfraFailure(
                "`evidence_repos` requires manifest-bound scoring — for "
                "unscheduled verification use evidence_repo/evidence_sha"
            )
    if manifest_path is not None:
        if seal_manifest_path is None:
            raise InfraFailure(
                "manifest-bound scoring requires the atomic-seal manifest "
                "(file → sha256) binding the judge prompt and every task "
                "context to the sealed package"
            )
        # Per-file hashes inside an untrusted JSON preserve nothing: the
        # seal manifest itself is trusted only through the single package
        # SHA-256 registered in the config at sealing time (and therefore
        # digest-bound into the schedule before any outcome was known).
        registered_seal = config.get("seal_package_sha256")
        if not registered_seal:
            raise InfraFailure(
                "config must register `seal_package_sha256` — the atomic-"
                "seal manifest is trusted only through the package hash "
                "recorded at sealing"
            )
        seal_bytes = read_input_bytes(seal_manifest_path, "seal manifest")
        if hashlib.sha256(seal_bytes).hexdigest() != registered_seal:
            raise InfraFailure(
                "seal manifest does not match the registered "
                "`seal_package_sha256` — a recomputed or altered seal is "
                "refused"
            )
        seal_doc, seal_files = parse_seal_manifest(seal_bytes,
                                                   seal_manifest_path)
        validate_sealed_judge_config(config, seal_doc)
        # The seal binds each task to ITS scoring context: a per-file hash
        # proves a context is sealed, not that it belongs to this task —
        # swapped mappings would judge replicates against another task's
        # ground truth.
        seal_assoc = seal_doc.get("task_contexts", {})
        for assoc_doc, ctx_path in context_by_doc.items():
            assoc_task = Path(task_by_doc[assoc_doc]).name
            expected_ctx = seal_assoc.get(assoc_task)
            if not expected_ctx:
                raise InfraFailure(
                    f"{assoc_task}: the sealed package records no "
                    f"task→context association — the seal must bind each "
                    f"task to its scoring context"
                )
            if Path(ctx_path).name != expected_ctx:
                raise InfraFailure(
                    f"{assoc_task}: supplied context "
                    f"`{Path(ctx_path).name}` is not the sealed context "
                    f"`{expected_ctx}` for this task — swapped contexts "
                    f"refused"
                )
        seal_prompts = seal_doc.get("judge_prompts", {})
        expected_prompt = seal_prompts.get(role)
        if not expected_prompt:
            raise InfraFailure(
                f"the sealed package records no judge prompt for role "
                f"`{role}` — the seal must bind each role to its prompt"
            )
        if Path(judge_prompt_path).name != expected_prompt:
            raise InfraFailure(
                f"supplied judge prompt `{Path(judge_prompt_path).name}` is "
                f"not the sealed `{role}` prompt `{expected_prompt}` — "
                f"role/prompt mixups refused"
            )
        judge_prompt = _read_sealed(judge_prompt_path, seal_files)
        sealed_context_texts = {
            doc_name: _read_sealed(ctx_path, seal_files)
            for doc_name, ctx_path in context_by_doc.items()
        }
        # Registered source-drift gate, COMPUTED by the harness: a status
        # claim is not evidence. The operator's recorded re-fetch step
        # supplies the re-fetched copies; the harness diffs them against
        # the SEALED snapshot digests — any mismatch makes the task
        # inconclusive for scorer and verifier alike.
        if snapshot_by_doc:
            if drift_report is None:
                raise InfraFailure(
                    "external-context tasks require the pre-score source-"
                    "drift report (--drift-report) carrying materiality "
                    "adjudications for any changed source — the harness "
                    "re-fetches the sealed live sources itself"
                )
            fetch_cmd = config.get("drift_fetch_cmd")
            if (not isinstance(fetch_cmd, list) or not fetch_cmd
                    or not all(isinstance(p, str) for p in fetch_cmd)
                    or not any("{url}" in p for p in fetch_cmd)
                    or not any("{dest}" in p for p in fetch_cmd)):
                raise InfraFailure(
                    "external-context scoring requires a registered "
                    "`drift_fetch_cmd` (non-empty command with {url} and "
                    "{dest} placeholders) — the harness itself re-fetches "
                    "every sealed live source; local copies are not "
                    "accepted as drift evidence"
                )
            snapshot_sources = seal_doc.get("snapshot_sources")
            if not isinstance(snapshot_sources, dict):
                raise InfraFailure(
                    "the sealed package must bind every external snapshot "
                    "to its live source URL (`snapshot_sources`) — drift "
                    "cannot be verified against unprovenanced copies"
                )
            # Drift is computed ONCE PER TASK and the verdict applied to
            # every replicate document of that task: per-document fetching
            # could split a nondeterministic live source into judged and
            # excluded replicates of the same cell. Each sealed source is
            # also fetched exactly once per invocation (keyed cache).
            fetched_digests = {}
            task_docs = {}
            for doc_name, snap_path in snapshot_by_doc.items():
                task_name = snap_task_by_doc[doc_name]
                entry = task_docs.setdefault(task_name, (snap_path, []))
                if entry[0] != snap_path:
                    raise InfraFailure(
                        f"{task_name}: replicate documents reference "
                        f"different snapshot copies — one sealed snapshot "
                        f"per task"
                    )
                entry[1].append(doc_name)
            for task_name in sorted(task_docs):
                snap_path, doc_names = task_docs[task_name]
                drift_entry = drift_report.get(task_name)
                if not isinstance(drift_entry, dict):
                    raise InfraFailure(
                        f"{task_name}: drift report must carry an entry "
                        f"for this task (adjudications for any changed "
                        f"source) — the pre-score gate is explicit"
                    )
                if drift_entry.get("refetched"):
                    # The gate never trusts operator-supplied bytes: a
                    # local path could be the sealed snapshot itself.
                    raise InfraFailure(
                        f"{task_name}: drift report `refetched` paths are "
                        f"not accepted — the harness fetches the sealed "
                        f"source URLs itself"
                    )
                snap_root = Path(snap_path)
                snap_items = _sealed_snapshot_items(snap_root, seal_files)
                changed_keys = []
                for _snap, _rel, seal_key in snap_items:
                    url = snapshot_sources.get(seal_key)
                    if not url:
                        raise InfraFailure(
                            f"{task_name}: sealed snapshot `{seal_key}` "
                            f"has no source URL in the sealed package — "
                            f"drift cannot be verified"
                        )
                    if seal_key not in fetched_digests:
                        fetched = _fetch_live_source(
                            fetch_cmd, url, config["timeout_seconds"])
                        fetched_digests[seal_key] = hashlib.sha256(
                            fetched).hexdigest()
                    if fetched_digests[seal_key] != seal_files[seal_key]:
                        changed_keys.append(seal_key)
                if changed_keys:
                    # The registered gate is about MATERIAL drift in a
                    # relevant section, not cosmetic churn: every changed
                    # file needs a recorded materiality adjudication
                    # (verdict + rationale). Material change -> task
                    # inconclusive; adjudicated-cosmetic change -> still
                    # scoreable, adjudication kept in the record.
                    adjudications = drift_entry.get("changed", {})
                    material = False
                    for key in changed_keys:
                        adj = adjudications.get(key)
                        if (not isinstance(adj, dict)
                                or not isinstance(adj.get("material"), bool)
                                or not adj.get("rationale")):
                            raise InfraFailure(
                                f"{task_name}: re-fetched source `{key}` "
                                f"changed but carries no recorded "
                                f"materiality adjudication (material: "
                                f"true/false + rationale) — a byte change "
                                f"alone is not conclusive drift"
                            )
                        if adj["material"]:
                            material = True
                    # The full adjudication basis (changed keys, verdicts,
                    # rationales) is preserved for BOTH outcomes: it lands
                    # in the result record and, via the drift-notes digest,
                    # in the batch identity — a corrected material-drift
                    # report between interruption and resume is a different
                    # batch even when the same task stays inconclusive.
                    note = {
                        "changed": changed_keys,
                        "material": material,
                        "adjudications": {
                            key: adjudications[key]
                            for key in changed_keys
                        },
                    }
                    # One verdict for the whole task: every replicate
                    # document carries the same note and the same
                    # inconclusive outcome.
                    for doc_name in doc_names:
                        drift_notes[doc_name] = note
                        if material:
                            inconclusive_docs.add(doc_name)
    else:
        judge_prompt = read_input_text(judge_prompt_path, "judge prompt")
        sealed_context_texts = None
    judge_cmd = config.get("judge_backend_cmd", config["backend_cmd"])
    if any("{installation}" in part for part in judge_cmd):
        raise InfraFailure(
            "judge command must be mount-free — set `judge_backend_cmd` "
            "(judges run without any arm installation)"
        )
    judge_model = config.get("judge_model")
    if not judge_model:
        raise InfraFailure("`judge_model` must be configured for score mode")
    judge_effort = config.get("judge_effort", "default")
    validate_timeout(config)
    require_effort_pin(judge_cmd, "judge command")
    judge_cmd = expand_backend_cmd(judge_cmd, None, judge_effort)
    doc_texts = [assert_blind_scorable(doc) for doc in doc_paths]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    order = list(range(len(doc_paths)))
    random.Random(scoring_seed).shuffle(order)
    # Judge batches are resumable and atomic: progress persists after every
    # judged document under one scoring_id, an interrupted batch resumes at
    # the first unjudged document (never re-judging finished ones), and a
    # COMPLETED batch refuses a second pass — re-judging would create
    # duplicate nondeterministic scores with no authoritative batch.
    batch_identity = {
        "scoring_seed": scoring_seed,
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "config_digest": config_digest(config),
        "role": role,
        "axis": "diagnostic" if diagnostic_axis else "primary",
        # ORDERED as supplied: the seeded shuffle operates on the
        # caller's index order, so a reordered resume is a different
        # batch — sorting here would let it slip through.
        "docs": [Path(d).name for d in doc_paths],
        # Drift decisions are part of the batch identity: a corrected or
        # replaced drift report between interruption and resume would
        # otherwise mix old judged results with new inconclusive
        # exclusions inside one batch.
        "drift_decisions": {
            "inconclusive": sorted(inconclusive_docs),
            "notes_digest": hashlib.sha256(
                json.dumps(drift_notes, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
    }
    # Batch state is namespaced by role: the scorer pass and the
    # verifier pass over the same documents may share one output
    # directory without colliding.
    scoring_manifest_path = out / f"scoring-{role}-manifest.json"
    if scoring_manifest_path.exists():
        prior_batch = load_json_object(scoring_manifest_path,
                                       "scoring batch manifest")
        if prior_batch.get("complete"):
            raise InfraFailure(
                "the scoring batch in this output directory is already "
                "complete — a second pass would create duplicate "
                "nondeterministic scores"
            )
        if prior_batch.get("identity") != batch_identity:
            raise InfraFailure(
                "existing scoring batch has a different identity "
                "(seed/manifest/config/role/docs) — batches must not be "
                "mixed"
            )
        scoring_id = prior_batch["scoring_id"]
        results = list(prior_batch.get("results", []))
    else:
        scoring_id = uuid.uuid4().hex[:8]
        results = []

    def write_scoring_manifest(complete):
        atomic_write_text(scoring_manifest_path, json.dumps({
            "scoring_id": scoring_id,
            "identity": batch_identity,
            "results": results,
            "complete": complete,
        }, indent=2) + "\n")

    # The scoring id must survive a crash BEFORE the first judge record is
    # written: persist the (possibly empty) batch state up front, so a
    # restart resumes under the same id and can discover orphaned judge
    # records instead of re-judging a document under a fresh id.
    write_scoring_manifest(False)

    for i, doc_index in enumerate(order):
        if i < len(results):
            # Judged before the interruption — never re-judged; but the
            # manifest entry is only trusted after it matches its atomic
            # judge record exactly: a corrupted or edited scoring manifest
            # must not smuggle an invented score, session, or accounting
            # past the judge loop.
            record_path = out / f"judge-{scoring_id}-{i}.json"
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise InfraFailure(
                    f"resumed batch slot {i} has no readable judge record "
                    f"({record_path.name}) — batch state corrupted"
                ) from exc
            if record != results[i]:
                raise InfraFailure(
                    f"resumed batch slot {i} does not match its judge "
                    f"record — scoring manifest corrupted or edited"
                )
            if record.get("presentation_index") != i:
                raise InfraFailure(
                    f"judge record for slot {i} carries presentation index "
                    f"{record.get('presentation_index')} — batch state "
                    f"corrupted"
                )
            if Path(record.get("doc", "")).name != Path(doc_paths[doc_index]).name:
                raise InfraFailure(
                    "resumed batch presentation order mismatch — batch "
                    "state corrupted or documents reordered"
                )
            continue
        orphan_path = out / f"judge-{scoring_id}-{i}.json"
        if orphan_path.exists():
            # Crash window: the judge record was written but the batch
            # manifest was not. Adopt the existing record instead of
            # launching a second nondeterministic session for the same
            # replicate.
            orphan = load_json_object(orphan_path, "orphaned judge record")
            if (Path(orphan.get("doc", "")).name
                    != Path(doc_paths[doc_index]).name):
                raise InfraFailure(
                    "orphaned judge record does not match its presentation "
                    "slot — batch state corrupted"
                )
            results.append(orphan)
            write_scoring_manifest(False)
            (out / f"judge-{scoring_id}-{i}.pending").unlink(missing_ok=True)
            continue
        pending_path = out / f"judge-{scoring_id}-{i}.pending"
        if pending_path.exists():
            # The pre-launch journal survived without a judge record: a
            # judge session may have launched and its outcome was lost.
            # One score per document forbids silently launching another
            # nondeterministic session — the batch blocks for
            # investigation.
            raise InfraFailure(
                f"pending judge journal for slot {i} without a judge "
                f"record ({pending_path.name}) — a judge session may have "
                f"launched and its outcome was lost; investigate, then "
                f"delete the journal to explicitly authorize re-judging "
                f"this slot"
            )
        doc, doc_text = doc_paths[doc_index], doc_texts[doc_index]
        if Path(doc).name in inconclusive_docs:
            # Task inconclusive per the registered source-drift gate:
            # recorded, never judged.
            result = {
                "doc": str(doc),
                "inconclusive": True,
                "reason": ("external source drift — task inconclusive per "
                           "the registered protocol"),
                "source_drift": drift_notes.get(Path(doc).name),
                "task": (task_by_doc.get(Path(doc).name)
                         if task_by_doc is not None else None),
                "scoring_seed": scoring_seed,
                "presentation_index": i,
                "scheduled": manifest_path is not None,
                # Exclusions carry the batch axis too: downstream
                # aggregation must distinguish a primary exclusion from
                # a diagnostic one.
                "role": role,
                "axis": "diagnostic" if diagnostic_axis else "primary",
            }
            atomic_write_text(out / f"judge-{scoring_id}-{i}.json",
                              json.dumps(result, indent=2) + "\n")
            results.append(result)
            write_scoring_manifest(False)
            continue
        if doc_evidence is not None:
            ev_repo, ev_sha = doc_evidence[Path(doc).name]
        else:
            ev_repo, ev_sha = evidence_repo, evidence_sha
        # Every judge session is a pinned session: the backend version is
        # re-probed per document, so an installation change mid-batch
        # cannot slip later documents onto an unregistered version.
        backend_version = verify_backend_version(config)
        # Each judge runs in its own root OUTSIDE the experiment tree:
        # nothing above the cwd leads to run artifacts. A scorer gets an
        # empty cwd and no inspection tools (JUDGE_SETTINGS); a verifier
        # gets a disposable worktree of THIS document's frozen evidence at
        # its pinned sha with read-only tools (VERIFIER_SETTINGS).
        judge_root = Path(tempfile.mkdtemp(prefix="rpa-judge-"))
        if ev_repo:
            profile, _ = make_profile(judge_root, "judge",
                                      settings=VERIFIER_SETTINGS)
            workdir = make_worktree(ev_repo, ev_sha, judge_root)
            if Path(doc).name in snapshot_by_doc:
                # Seal-verified frozen snapshots are placed INSIDE the
                # confined workdir so the sandboxed verifier can read them.
                # Directory layout is preserved and seal keys are package-
                # relative, so same-named files in different subdirectories
                # stay distinct and never overwrite each other.
                snap_src = Path(snapshot_by_doc[Path(doc).name])
                snap_dest = workdir / "_sealed-snapshots"
                snap_dest.mkdir()
                for snap, rel, seal_key in _sealed_snapshot_items(
                        snap_src, seal_files):
                    dest = snap_dest / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(
                        _sealed_bytes(snap, seal_files, key=seal_key)
                    )
        else:
            profile, _ = make_profile(judge_root, "judge",
                                      settings=JUDGE_SETTINGS)
            workdir = judge_root / "workdir"
            workdir.mkdir()
        env = backend_env(profile)
        sandboxed_cmd = apply_sandbox(config, judge_cmd, workdir, profile)
        prompt_parts = [judge_prompt]
        if sealed_context_texts is not None:
            # Preloaded and seal-verified once, before any session: a file
            # swap between judge calls cannot change what judges see.
            prompt_parts.append(
                "## Task-specific sealed context\n\n"
                + sealed_context_texts[Path(doc).name]
            )
        prompt_parts.append("---\n\n" + doc_text)
        prompt = "\n\n".join(prompt_parts)
        # Durable journal BEFORE the judge launches: if the harness dies
        # after the session returns but before the judge record lands, the
        # resume finds this marker and blocks instead of silently running
        # a second nondeterministic session for the same document. An
        # in-process failure retires the journal on its way out — the
        # outcome is known (invalid session), so resume re-executes
        # cleanly.
        atomic_write_text(pending_path, json.dumps({
            "doc": str(doc),
            "presentation_index": i,
            "scoring_id": scoring_id,
            "role": role,
            "axis": "diagnostic" if diagnostic_axis else "primary",
        }, indent=2) + "\n")
        try:
            try:
                stdout = spawn_session(
                    sandboxed_cmd, prompt, str(workdir), env,
                    config["timeout_seconds"]
                )
            except WorkflowFailure as wf:
                # Judges have no workflow outcome: a timed-out judge
                # session is an invalid session (infrastructure) — resume
                # the batch and it re-executes only the unfinished
                # documents.
                raise InfraFailure(
                    f"judge session failed ({wf}) — invalid judge session; "
                    f"resume the scoring batch to re-execute it"
                ) from wf
            finally:
                if ev_repo:
                    remove_worktree(ev_repo, workdir)
        except InfraFailure:
            pending_path.unlink(missing_ok=True)
            raise
        try:
            session_id, nodes, response = parse_transcript(stdout)
            if not response.strip():
                raise InfraFailure(
                    f"judge session {session_id} returned no response text")
            validate_models(nodes, judge_model)
            effort_capture = validate_efforts(nodes, judge_effort)
        except InfraFailure:
            # Post-spawn validation failed in-process: the outcome is
            # known (invalid judge session), so the journal is retired and
            # resume re-executes this slot cleanly.
            pending_path.unlink(missing_ok=True)
            raise
        result = {
            "doc": str(doc),
            "session_id": session_id,
            "profile": str(profile),
            "cwd": str(workdir),
            "role": role,
            "axis": "diagnostic" if diagnostic_axis else "primary",
            "backend_version": backend_version,
            "scoring_seed": scoring_seed,
            "presentation_index": i,
            "scheduled": manifest_path is not None,
            "judge_model": judge_model,
            "task": (task_by_doc.get(Path(doc).name)
                     if task_by_doc is not None else None),
            "task_context": (str(context_by_doc[Path(doc).name])
                             if context_by_doc is not None else None),
            "seal_manifest": (str(seal_manifest_path)
                              if seal_manifest_path is not None else None),
            "snapshots": snapshot_by_doc.get(Path(doc).name),
            "source_drift": drift_notes.get(Path(doc).name),
            "effort_capture": effort_capture,
            "response": response,
            "accounting": account(nodes),
        }
        if ev_repo:
            result["evidence_sha"] = ev_sha
        atomic_write_text(out / f"judge-{scoring_id}-{i}.json",
                          json.dumps(result, indent=2) + "\n")
        results.append(result)
        write_scoring_manifest(False)
        pending_path.unlink(missing_ok=True)
    judged = [r for r in results if not r.get("inconclusive")]
    if len({r["session_id"] for r in judged}) != len(judged) or len(
        {r["profile"] for r in judged}
    ) != len(judged):
        raise InfraFailure("judge sessions were not fresh/isolated")
    write_scoring_manifest(True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="runner config JSON")
    parser.add_argument("--preflight", action="store_true",
                        help="prove all capabilities against the mock backend")
    parser.add_argument("--arm", help="arm name for run mode")
    parser.add_argument("--task", help="task file for run mode")
    parser.add_argument("--repo", help="target repo clone for run mode")
    parser.add_argument("--score", action="store_true",
                        help="judge mode: score documents in fresh sessions")
    parser.add_argument("--docs", nargs="+", help="documents to score")
    parser.add_argument("--judge-prompt", help="judge prompt file (from the sealed package)")
    parser.add_argument("--evidence-repo",
                        help="score mode, verifier role: frozen evidence repo; "
                             "the judge gets a read-only worktree at --evidence-sha")
    parser.add_argument("--evidence-sha",
                        help="pinned sha for --evidence-repo (the task's target-sha)")
    parser.add_argument("--scoring-seed", type=int,
                        help="score mode: recorded seed randomizing the "
                             "document presentation order")
    parser.add_argument("--evidence-repos", nargs="+",
                        help="score mode with --manifest, verifier role: "
                             "NAME=PATH frozen-clone mapping; each document "
                             "is verified against its own task's pinned "
                             "repo@sha")
    parser.add_argument("--repos", nargs="+",
                        help="--run-schedule: NAME=PATH clone mapping; each "
                             "task is routed to the clone registered for "
                             "its target-repo")
    parser.add_argument("--manifest",
                        help="score mode: schedule manifest binding --docs "
                             "to completed scheduled replicates (exactly "
                             "one anonymized artifact per replicate)")
    parser.add_argument("--unscheduled-docs", action="store_true",
                        help="score mode: explicitly allow ad-hoc/dev "
                             "scoring without a schedule manifest")
    parser.add_argument("--diagnostic-axis", action="store_true",
                        help="score mode with --manifest: the registered "
                             "diagnostic content axis — the batch covers "
                             "every produced document (completed "
                             "replicates' anonymized artifacts PLUS "
                             "gate-failed replicates' diagnostic copies); "
                             "gate failures stay counted workflow "
                             "failures for the primary outcome")
    parser.add_argument("--task-contexts", nargs="+",
                        help="score mode with --manifest: TASKFILE=CONTEXT "
                             "mapping from task file basename to its sealed "
                             "scoring context (task prompt + ground truth)")
    parser.add_argument("--seal-manifest",
                        help="score mode with --manifest: atomic-seal "
                             "manifest (file → sha256) binding the judge "
                             "prompt and task contexts to the sealed "
                             "package; the manifest file itself must match "
                             "the config's registered seal_package_sha256")
    parser.add_argument("--task-snapshots", nargs="+",
                        help="score mode, verifier role: TASKFILE=PATH "
                             "mapping to sealed frozen external-source "
                             "snapshots for external-context tasks")
    parser.add_argument("--drift-report",
                        help="score mode: JSON drift report from the "
                             "pre-score re-fetch of sealed external "
                             "sources ({taskfile: {status: "
                             "unchanged|drifted}}); drifted tasks are "
                             "recorded inconclusive, never judged")
    parser.add_argument("--output", default="runs", help="output directory")
    parser.add_argument("--make-schedule", action="store_true",
                        help="write a pre-registered randomized schedule "
                             "(requires --config, --tasks, --seed)")
    parser.add_argument("--tasks", nargs="+",
                        help="task files for --make-schedule")
    parser.add_argument("--replicates", type=int, default=3,
                        help="replicates per arm/task cell (the protocol "
                             "fixes 3; other values need "
                             "--allow-nonstandard)")
    parser.add_argument("--allow-nonstandard", action="store_true",
                        help="dev-set tuning only: permit a replicate count "
                             "other than 3 and/or a non-three-arm topology; "
                             "the schedule is marked nonstandard and cannot "
                             "pass as holdout")
    parser.add_argument("--seed", type=int,
                        help="recorded randomization seed for --make-schedule")
    parser.add_argument("--schedule-out", default="schedule.json",
                        help="where --make-schedule writes the schedule")
    parser.add_argument("--run-schedule",
                        help="execute a pre-registered schedule file "
                             "(requires --config, --repo)")
    args = parser.parse_args()

    if args.preflight:
        from preflight import run_preflight  # noqa: PLC0415 — colocated module

        sys.exit(run_preflight())

    if args.make_schedule:
        if not (args.config and args.tasks and args.seed is not None):
            parser.error("--make-schedule requires --config, --tasks, --seed")
        try:
            schedule = make_schedule(
                load_config(args.config), args.tasks, args.replicates,
                args.seed,
                allow_nonstandard=args.allow_nonstandard,
            )
        except InfraFailure as exc:
            print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
            sys.exit(1)
        Path(args.schedule_out).write_text(
            json.dumps(schedule, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"schedule": args.schedule_out,
                          "entries": len(schedule["entries"]),
                          "seed": args.seed}))
        sys.exit(0)

    if args.run_schedule:
        if not (args.config and args.repos and args.tasks):
            parser.error("--run-schedule requires --config, --repos "
                         "(NAME=PATH clone mapping), and --tasks (the "
                         "registered task set, compared against the "
                         "schedule)")
        try:
            config = load_config(args.config)
            repos = parse_repo_mapping(args.repos, "--repos")
            manifest = run_schedule(config, args.run_schedule, repos,
                                    args.output, args.tasks)
        except InfraFailure as exc:
            print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
            sys.exit(1)
        print(json.dumps({"complete": manifest["complete"],
                          "runs": len(manifest["results"])}))
        sys.exit(0)

    if args.score:
        if not (args.config and args.docs and args.judge_prompt):
            parser.error("score mode requires --config, --docs, --judge-prompt")
        if bool(args.evidence_repo) != bool(args.evidence_sha):
            parser.error("--evidence-repo and --evidence-sha must be "
                         "supplied together (all-or-nothing)")
        if args.scoring_seed is None:
            parser.error("score mode requires --scoring-seed (recorded "
                         "randomization of the presentation order)")
        if args.manifest and not args.tasks:
            parser.error("--manifest scoring requires --tasks (the "
                         "registered task set, used to reconstruct and "
                         "verify the schedule)")
        try:
            config = load_config(args.config)
            evidence_repos = (parse_repo_mapping(args.evidence_repos,
                                                 "--evidence-repos")
                              if args.evidence_repos else None)
            task_contexts = (parse_repo_mapping(args.task_contexts,
                                                "--task-contexts")
                             if args.task_contexts else None)
            task_snapshots = (parse_repo_mapping(args.task_snapshots,
                                                 "--task-snapshots")
                              if args.task_snapshots else None)
        except InfraFailure as exc:
            print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
            sys.exit(1)
        try:
            results = score(config, args.docs, args.judge_prompt, args.output,
                            evidence_repo=args.evidence_repo,
                            evidence_sha=args.evidence_sha,
                            scoring_seed=args.scoring_seed,
                            manifest_path=args.manifest,
                            allow_unscheduled=args.unscheduled_docs,
                            diagnostic_axis=args.diagnostic_axis,
                            evidence_repos=evidence_repos,
                            task_contexts=task_contexts,
                            seal_manifest_path=args.seal_manifest,
                            task_snapshots=task_snapshots,
                            drift_report_path=args.drift_report,
                            score_task_paths=args.tasks)
        except InfraFailure as exc:
            # Expected operator-input rejections are classified, structured
            # output — not a traceback indistinguishable from a crash.
            print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
            sys.exit(1)
        print(json.dumps([
            {"doc": r["doc"], "inconclusive": True}
            if r.get("inconclusive")
            else {"doc": r["doc"], "session_id": r["session_id"]}
            for r in results
        ]))
        sys.exit(0)

    if not (args.config and args.arm and args.task and args.repo):
        parser.error("run mode requires --config, --arm, --task, --repo")
    try:
        config = load_config(args.config)
        attempts = run_task_with_retries(
            config, args.arm, args.task, args.repo, args.output
        )
    except InfraFailure as exc:
        # Config-level fault (e.g. unknown arm): classified, no traceback.
        print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
        sys.exit(1)
    record = attempts[-1]
    summary = {k: record[k] for k in ("run_id", "status", "interventions")}
    summary["attempts"] = len(attempts)
    print(json.dumps(summary))
    sys.exit(0 if record["status"] == "completed" else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
