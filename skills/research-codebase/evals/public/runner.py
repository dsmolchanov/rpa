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
import codecs
import contextlib
import fcntl
import importlib.util
import hashlib
import json
import random
import re
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pilot_registration

_ARTIFACT_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "artifact_validator", Path(__file__).with_name("validate_artifact.py"))
artifact_validator = importlib.util.module_from_spec(_ARTIFACT_VALIDATOR_SPEC)
_ARTIFACT_VALIDATOR_SPEC.loader.exec_module(artifact_validator)

_JUDGE_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "judge_contract", Path(__file__).with_name("judge_contract.py"))
judge_contract = importlib.util.module_from_spec(_JUDGE_CONTRACT_SPEC)
_JUDGE_CONTRACT_SPEC.loader.exec_module(judge_contract)

_SEAL_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "seal_package", Path(__file__).with_name("seal_package.py"))
seal_package = importlib.util.module_from_spec(_SEAL_PACKAGE_SPEC)
_SEAL_PACKAGE_SPEC.loader.exec_module(seal_package)

MAX_CONTINUATIONS = 3
DEFAULT_MAX_INFRA_RETRIES = pilot_registration.MAX_INFRA_RETRIES
# The pilot protocol fixes the replicate count and the holdout size;
# schedules that deviate must be explicitly marked nonstandard (dev-set
# tuning only, never holdout).
REGISTERED_REPLICATES = 3
REGISTERED_HOLDOUT_TASKS = len(seal_package.HOLDOUT_TASKS)
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
PILOT_V2_PROTOCOL_VERSION = pilot_registration.PROTOCOL_VERSION
PILOT_V2_MAX_JUDGE_ATTEMPTS = pilot_registration.MAX_JUDGE_ATTEMPTS
PILOT_V2_SCHEDULE_SEED = pilot_registration.SCHEDULE_SEED
PILOT_V2_SCORER_SEED = pilot_registration.SCORER_SEED
PILOT_V2_VERIFIER_SEED = pilot_registration.VERIFIER_SEED
PILOT_V2_LIVE_PROBE_VERSION = pilot_registration.LIVE_PROBE_VERSION
# Judge responses are capped at 1 MiB by judge_contract; 4 MiB leaves room
# for stream-json envelopes and accounting nodes. An oversized stream is
# preserved verbatim in a sidecar and consumes one invalid attempt, so bounded
# attempt JSON never discards audit evidence or permits unbounded retries.
PILOT_V2_MAX_RAW_STREAM_BYTES = 4 * 1024 * 1024
# Progress is operator-only stderr telemetry, never protocol evidence.  Keep
# its vocabulary closed so a caller cannot accidentally copy a prompt, task,
# document, source URL, path, argv element, or identifier into a heartbeat.
PROGRESS_HEARTBEAT_SECONDS = 30.0
PROGRESS_HEARTBEAT_STAGES = frozenset({
    "judge-model-call",
    "real-preflight",
    "workflow-model-call",
})
# Protocol-v2 sessions receive only the environment needed by the pinned
# Claude CLI, its filesystem wrapper, locale/TLS, and network proxy.  In
# particular, arbitrary cloud, source-control, and developer-tool tokens from
# the operator process must never become model-visible ambient context.
PILOT_V2_ENVIRONMENT_POLICY_ID = pilot_registration.ENVIRONMENT_POLICY_ID
PILOT_V2_ENV_ALLOWLIST = frozenset({
    "ALL_PROXY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_SESSION_INGRESS_TOKEN",
    "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
    "COLORTERM",
    "CURL_CA_BUNDLE",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LC_COLLATE",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LC_MONETARY",
    "LC_NUMERIC",
    "LC_TIME",
    "LOGNAME",
    "MACOS_SANDBOX_CLI_ROOT",
    "NODE_EXTRA_CA_CERTS",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TZ",
    "USER",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
})

OPERATOR_IMAGE_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ARTIFACT_PARSER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ARTIFACT_PARSER_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PILOT_V2_AGGREGATION_POLICY = pilot_registration.AGGREGATION_POLICY
PILOT_V2_JUDGE_RETRY_POLICY = pilot_registration.JUDGE_RETRY_POLICY
PILOT_V2_JUDGE_OUTPUT_POLICY = pilot_registration.JUDGE_OUTPUT_POLICY
PILOT_V2_FAILURE_KINDS = {
    "artifact_contract",
    "timeout",
    "abort",
    "missing_document",
    "subagent_policy",
    "workflow_failure",
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
FINGERPRINT_KEY_RE = re.compile(
    r"(?:^|[,\{\[\-?])\s*(?:\?\s*)?(?:\[\s*)?"
    r"(?P<quote>['\"]?)(?P<key>"
    + "|".join(re.escape(key) for key in FINGERPRINT_KEYS)
    + r")(?P=quote)(?:\s*\])?\s*:",
    re.IGNORECASE,
)
FINGERPRINT_EXPLICIT_KEY_RE = re.compile(
    r"^\s*(?:-\s*)?\?\s*(?:\[\s*)?(?P<quote>['\"]?)(?P<key>"
    + "|".join(re.escape(key) for key in FINGERPRINT_KEYS)
    + r")(?P=quote)(?:\s*\])?\s*$",
    re.IGNORECASE,
)
YAML_EXPLICIT_VALUE_RE = re.compile(r"^\s*:\s*(?P<value>.*)$")
YAML_ALIAS_RE = re.compile(r"^\*(?P<name>[A-Za-z0-9_-]+)(?:\s|$)")
YAML_ANCHOR_RE = re.compile(r"&(?P<name>[A-Za-z0-9_-]+)(?:\s|$)")
FRONTMATTER_DELIMITER_RE = re.compile(r"^---[ \t]*$")
BOLD_FINGERPRINT_RE = re.compile(
    r"^\*\*(?P<label>date|researcher|branch|git[ _-]*commit|"
    r"last[ _-]*updated(?:[ _-]*by)?)\*\*\s*:.*$",
    re.IGNORECASE | re.MULTILINE,
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

    def __init__(self, message, failure_kind=None):
        super().__init__(message)
        self.failure_kind = failure_kind


class WorkflowFailure(Exception):
    """The evaluated workflow failed (timeout, abort, no artifact): counted,
    never replaced. `stdout` carries any partial transcript emitted before
    the failure so the failed run's accounting is preserved."""

    def __init__(self, message, stdout=None, failure_kind="workflow_failure"):
        super().__init__(message)
        self.stdout = stdout
        if failure_kind not in PILOT_V2_FAILURE_KINDS:
            raise ValueError(f"unknown workflow failure kind: {failure_kind}")
        self.failure_kind = failure_kind


def _progress_heartbeat_line(stage, elapsed_seconds, *, completed=None,
                             total=None, call=None, call_total=None):
    """Build one metadata-only progress line from a closed vocabulary.

    Arbitrary text is deliberately not accepted.  This keeps private model
    inputs and process details out of operator logs by construction while
    still exposing enough aggregate state to distinguish a healthy long call
    from a stalled driver.
    """
    if stage not in PROGRESS_HEARTBEAT_STAGES:
        raise ValueError("progress heartbeat stage is not registered")
    if (isinstance(elapsed_seconds, bool)
            or not isinstance(elapsed_seconds, (int, float))
            or elapsed_seconds < 0):
        raise ValueError("progress heartbeat elapsed time must be nonnegative")

    def checked_pair(first, second, first_name, second_name, minimum):
        if (first is None) != (second is None):
            raise ValueError(
                f"progress heartbeat {first_name}/{second_name} must be paired")
        if first is None:
            return None
        if (isinstance(first, bool) or isinstance(second, bool)
                or not isinstance(first, int) or not isinstance(second, int)
                or first < minimum or second < minimum or first > second):
            raise ValueError(
                f"progress heartbeat {first_name}/{second_name} is invalid")
        return first, second

    progress = checked_pair(completed, total, "completed", "total", 0)
    invocation = checked_pair(call, call_total, "call", "call_total", 1)
    fields = ["progress-heartbeat", f"stage={stage}"]
    if progress is not None:
        fields.extend((f"completed={progress[0]}", f"total={progress[1]}"))
    if invocation is not None:
        fields.extend((f"call={invocation[0]}",
                       f"call_total={invocation[1]}"))
    fields.append(f"elapsed_seconds={int(elapsed_seconds)}")
    return " ".join(fields)


def emit_progress_heartbeat(stage, elapsed_seconds, *, completed=None,
                            total=None, call=None, call_total=None,
                            stream=None):
    """Emit safe progress to stderr without affecting protocol state."""
    line = _progress_heartbeat_line(
        stage, elapsed_seconds, completed=completed, total=total,
        call=call, call_total=call_total)
    try:
        print(line, file=stream if stream is not None else sys.stderr,
              flush=True)
    except (OSError, ValueError):
        # Observability must never change an experimental outcome.
        pass


@contextlib.contextmanager
def progress_heartbeat(stage, *, completed=None, total=None, call=None,
                       call_total=None, interval_seconds=None, stream=None):
    """Emit periodic metadata-only stderr progress around a blocking call."""
    interval = (PROGRESS_HEARTBEAT_SECONDS if interval_seconds is None
                else interval_seconds)
    if (isinstance(interval, bool) or not isinstance(interval, (int, float))
            or interval <= 0):
        raise ValueError("progress heartbeat interval must be positive")
    # Validate synchronously.  The worker then receives only registered
    # literals and numeric counters, never any private call inputs.
    _progress_heartbeat_line(
        stage, 0, completed=completed, total=total,
        call=call, call_total=call_total)
    started = time.monotonic()
    stop = threading.Event()

    def report():
        while not stop.wait(interval):
            emit_progress_heartbeat(
                stage, time.monotonic() - started,
                completed=completed, total=total,
                call=call, call_total=call_total, stream=stream)

    worker = threading.Thread(
        target=report, name="rpa-progress-heartbeat", daemon=True)
    try:
        worker.start()
    except RuntimeError:
        worker = None
    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            # A broken logging sink must not delay or reclassify the call.
            worker.join(timeout=0.1)


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


def _open_parent_directory(path):
    """Open and bind the destination directory without following its final
    component.  All durable state mutations use the returned descriptor so a
    path swap cannot redirect an already-authorized write to another tree."""
    path = Path(path)
    flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_DIRECTORY", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    fd = os.open(path.parent, flags)
    opened = os.fstat(fd)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(fd)
        raise InfraFailure(
            f"destination parent is not an ordinary directory: {path.parent}"
        )
    return fd


def _fsync_directory(fd, label):
    """Make a directory-entry mutation durable before it authorizes work."""
    try:
        os.fsync(fd)
    except OSError as exc:
        raise InfraFailure(
            f"cannot durably persist {label} directory entry"
        ) from exc


def _target_stat(dir_fd, name):
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _validate_replace_target(target, path):
    if target is None:
        return
    if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
        raise InfraFailure(
            f"refusing unsafe output target {path}: expected a single-link "
            "ordinary file"
        )


def durable_unlink(path, missing_ok=False):
    """Unlink one state marker and fsync its parent directory.

    Claims and pending journals govern whether a nondeterministic backend may
    be called again.  Merely unlinking them is not enough: after a crash the
    deletion must not disappear while a later record survives.
    """
    path = Path(path)
    dir_fd = _open_parent_directory(path)
    try:
        try:
            os.unlink(path.name, dir_fd=dir_fd)
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        _fsync_directory(dir_fd, f"unlink of {path.name}")
        return True
    finally:
        os.close(dir_fd)


def atomic_write_bytes(path, data):
    """Crash-safe persistence for manifests and run records: the content is
    written to a temp file in the same directory, flushed to disk, and
    atomically swapped into place with os.replace — a crash mid-write can
    never leave partial JSON that would block resuming already-observed
    entries (and deleting a corrupt manifest to recover would rerun them,
    which the protocol forbids)."""
    path = Path(path)
    dir_fd = _open_parent_directory(path)
    try:
        target_before = _target_stat(dir_fd, path.name)
        _validate_replace_target(target_before, path)
        tmp_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        fd = -1
        created = False
        try:
            fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
            created = True
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            target_now = _target_stat(dir_fd, path.name)
            _validate_replace_target(target_now, path)
            if ((target_before is None) != (target_now is None)
                    or (target_before is not None
                        and (target_before.st_dev, target_before.st_ino,
                             target_before.st_nlink)
                        != (target_now.st_dev, target_now.st_ino,
                            target_now.st_nlink))):
                raise InfraFailure(
                    f"output target changed during atomic write: {path}")
            os.replace(
                tmp_name, path.name, src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd)
            created = False
            _fsync_directory(dir_fd, f"replacement of {path.name}")
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                if created:
                    os.unlink(tmp_name, dir_fd=dir_fd)
                    _fsync_directory(dir_fd, f"cleanup of {tmp_name}")
            except OSError:
                pass
            raise
    finally:
        os.close(dir_fd)


def atomic_write_text(path, text):
    return atomic_write_bytes(path, text.encode("utf-8"))


def _path_present(path):
    """Existence check that does not treat a dangling symlink as absent."""
    try:
        Path(path).lstat()
        return True
    except OSError:
        return False


def _safe_regular_file(path):
    """True only for a real regular file, never a symlink or directory."""
    try:
        return stat.S_ISREG(Path(path).lstat().st_mode)
    except OSError:
        return False


def _safe_single_link_regular_file(path):
    try:
        info = Path(path).lstat()
        return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    except OSError:
        return False


def bind_output_directory(path):
    """Resolve an output root once and bind its directory identity.

    The lock and every nested state-machine operation must name this exact
    directory. Re-resolving the caller's original path after the lock is held
    would let a symlink swap split the lock from the state it is meant to
    serialize.
    """
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        opened = root.lstat()
    except OSError as exc:
        raise InfraFailure(f"cannot bind output directory {root}") from exc
    if not stat.S_ISDIR(opened.st_mode):
        raise InfraFailure(f"output root is not a directory: {root}")
    return root, (opened.st_dev, opened.st_ino)


def verify_output_directory(root, identity, label="output directory"):
    """Fail if a canonical output root was renamed or replaced."""
    root = Path(root)
    try:
        current = root.lstat()
    except OSError as exc:
        raise InfraFailure(f"{label} disappeared after it was bound") from exc
    if (not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != identity):
        raise InfraFailure(
            f"{label} changed identity after its state-machine lock was "
            "acquired"
        )
    return root


def _evidence_descriptor(path):
    """Describe invalid material without following it or failing to seal.

    Terminal-invalid markers must survive directories, dangling symlinks,
    unreadable files, and type-changing races.  Hash bytes only through a
    no-follow descriptor whose identity still matches the initial lstat;
    otherwise retain type/error metadata as the durable evidence.
    """
    path = Path(path)
    evidence = {"file": path.name}
    try:
        before = path.lstat()
    except OSError as exc:
        evidence.update({
            "file_type": "unreadable_or_missing",
            "error_errno": exc.errno,
        })
        return evidence
    if stat.S_ISLNK(before.st_mode):
        evidence["file_type"] = "symlink"
        return evidence
    if stat.S_ISDIR(before.st_mode):
        evidence["file_type"] = "directory"
        return evidence
    if not stat.S_ISREG(before.st_mode):
        evidence["file_type"] = "other"
        evidence["mode"] = stat.S_IFMT(before.st_mode)
        return evidence
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        evidence.update({
            "file_type": "unreadable_regular",
            "error_errno": exc.errno,
        })
        return evidence
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (before.st_dev, before.st_ino)):
            evidence["file_type"] = "changed_during_audit"
            return evidence
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    except OSError as exc:
        evidence.update({
            "file_type": "unreadable_regular",
            "error_errno": exc.errno,
        })
        return evidence
    finally:
        os.close(fd)
    evidence.update({"file_type": "regular", "sha256": digest.hexdigest()})
    return evidence


def exclusive_write_text(path, text):
    """Create one durable claim without ever replacing an existing claim.

    ``atomic_write_text`` is correct for single-writer state, but its final
    ``os.replace`` lets two concurrent resumptions both believe they own the
    same experimental slot.  Claims use ``O_EXCL`` so exactly one process can
    cross the launch boundary; every loser stops before spawning a backend.
    """
    path = Path(path)
    dir_fd = _open_parent_directory(path)
    try:
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_CLOEXEC", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        fd = -1
        created = False
        try:
            fd = os.open(path.name, flags, 0o600, dir_fd=dir_fd)
            created = True
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(dir_fd, f"creation of {path.name}")
        except BaseException:
            if fd >= 0:
                os.close(fd)
            if created:
                try:
                    os.unlink(path.name, dir_fd=dir_fd)
                    _fsync_directory(dir_fd, f"cleanup of {path.name}")
                except OSError:
                    pass
            raise
    finally:
        os.close(dir_fd)


def process_is_alive(pid):
    """Best-effort liveness test used only to avoid concurrent relaunches.

    A false positive merely blocks until the reported process exits; it can
    never authorize an extra experimental observation.
    """
    if (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _verify_lock_identity(fd, path, label):
    """Prove an opened lock fd is the sole ordinary file at its pathname."""
    try:
        opened = os.fstat(fd)
        named = Path(path).lstat()
    except OSError as exc:
        raise InfraFailure(
            f"cannot verify {label} lock identity: {exc}") from exc
    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (named.st_dev, named.st_ino)):
        raise InfraFailure(
            f"{label} lock must be one ordinary, unlinked-to-elsewhere "
            f"regular file")


def acquire_advisory_lock(path, label):
    """Acquire one process-scoped, nonblocking exclusive advisory lock.

    The lock file is deliberately persistent: unlinking a live advisory-lock
    path creates a second inode that another process can lock independently.
    Crash recovery relies on the kernel releasing ``flock`` when the owning
    process exits, never on deleting a stale pathname or PID claim.
    """
    path = Path(path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise InfraFailure(f"cannot open {label} lock {path}: {exc}") from exc
    try:
        _verify_lock_identity(fd, path, label)
        parent_fd = _open_parent_directory(path)
        try:
            _fsync_directory(parent_fd, f"creation of {path.name} lock")
        finally:
            os.close(parent_fd)
    except BaseException:
        os.close(fd)
        raise
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise InfraFailure(
            f"{label} is owned by an active concurrent process; no backend "
            f"was launched"
        ) from exc
    except OSError as exc:
        handle.close()
        raise InfraFailure(f"cannot acquire {label} lock: {exc}") from exc
    try:
        # Recheck after flock and immediately before mutation.  This catches
        # a fallback-platform symlink swap, rename replacement, or hardlink
        # created across the open/lock window without ever truncating the
        # foreign target.
        _verify_lock_identity(handle.fileno(), path, label)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "label": label}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    except BaseException:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        raise
    return handle


def refuse_missing_persistent_lock_with_state(root, lock_path, patterns,
                                              label):
    """Never recreate a lock inode after its protected state exists.

    A held ``flock`` protects an inode, not a pathname.  If an operator or
    concurrent process unlinks the persistent lock while state remains,
    opening the pathname with ``O_CREAT`` would silently elect a second lock
    domain and permit duplicate nondeterministic observations.
    """
    root = Path(root)
    lock_path = Path(lock_path)
    if _path_present(lock_path):
        return
    material = {
        path.name
        for pattern in patterns
        for path in root.glob(pattern)
        if _path_present(path)
    }
    if material:
        shown = ", ".join(sorted(material)[:5])
        suffix = " ..." if len(material) > 5 else ""
        raise InfraFailure(
            f"{label} persistent lock is missing while protected state "
            f"exists ({shown}{suffix}); refusing to create a second lock "
            f"inode or launch a backend")


def release_advisory_lock(handle):
    """Release a handle returned by :func:`acquire_advisory_lock`."""
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def protocol_v2_runtime_pins(config):
    """Canonical operator-runtime evidence bound into every v2 artifact.

    The environment policy identifies the semantics while these values make
    the concrete image, artifact-parser implementation, judge output policy,
    and role-specific structural schemas directly auditable. Standard configs
    validate their shape in :func:`load_config`; nonstandard synthetic/dev
    configs retain explicit ``None`` values when they omit runtime pins.
    """
    return {
        "operator_image_sha256": config.get("operator_image_sha256"),
        "artifact_parser": config.get("artifact_parser"),
        "artifact_parser_version": config.get("artifact_parser_version"),
        "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
        "structured_output_schema_sha256": {
            role: judge_contract.structured_output_schema_sha256(role)
            for role in ("scorer", "verifier")
        },
        "final_response_contract_sha256": {
            role: judge_contract.final_response_contract_sha256(role)
            for role in ("scorer", "verifier")
        },
    }


def protocol_v2_live_probe_binding(config):
    """Canonical proof that the registered judge transport worked live.

    The two digests are config data while the version is public protocol
    policy.  Binding this object into both the seal and ``config_digest``
    prevents direct runner entry points from skipping the pre-seal probe.
    """
    return {
        "probe_version": PILOT_V2_LIVE_PROBE_VERSION,
        "receipt_sha256": config.get("judge_live_probe_receipt_sha256"),
        "execution_sha256": config.get("judge_live_probe_execution_sha256"),
    }


def require_standard_v2_registration(config, *, allow_pending_probe=False,
                                     allow_pending_seal=False):
    """Fail before mutation/launch when a standard-v2 config drifts.

    Dev protocol-v2 fixtures are permitted only through the explicit
    ``nonstandard_config: true`` marker; they can never reconstruct a standard
    schedule because that marker is digest-bound into every artifact.
    """
    if config.get("protocol_version") != PILOT_V2_PROTOCOL_VERSION:
        return
    problems = pilot_registration.standard_v2_registration_problems(
        config, allow_pending_probe=allow_pending_probe,
        allow_pending_seal=allow_pending_seal)
    if config.get("nonstandard_config") is False:
        actual_final_contracts = {
            role: judge_contract.final_response_contract_sha256(role)
            for role in ("scorer", "verifier")
        }
        if (actual_final_contracts
                != pilot_registration.FINAL_RESPONSE_CONTRACT_SHA256):
            problems.append(
                "public final-response contracts differ from the "
                "standard-v2 registration")
        if PILOT_V2_JUDGE_OUTPUT_POLICY.get(
                "final_response_contract_sha256") != actual_final_contracts:
            problems.append(
                "judge output policy does not bind the exact public "
                "final-response contracts")
    if problems:
        raise InfraFailure(
            "standard protocol-v2 runtime differs from its public "
            f"registration: {'; '.join(problems)}")


def load_config(path):
    """User-input faults (missing/unreadable/malformed config, wrong shape)
    are classified infrastructure failures, never raw tracebacks: a
    syntactically valid but structurally wrong config (e.g. `{}`) must not
    surface later as a KeyError deep inside a mode."""
    try:
        config = _json_without_duplicate_keys(
            Path(path).read_bytes(), f"config {path}")
    except OSError as exc:
        raise InfraFailure(f"cannot read config {path}: {exc}") from exc
    except (json.JSONDecodeError, InfraFailure) as exc:
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
    protocol_version = config.get("protocol_version", 1)
    if (isinstance(protocol_version, bool)
            or not isinstance(protocol_version, int)
            or protocol_version not in (1, PILOT_V2_PROTOCOL_VERSION)):
        raise InfraFailure(
            f"config {path}: `protocol_version` must be integer 1 or 2, "
            f"got {protocol_version!r}"
        )
    if protocol_version == PILOT_V2_PROTOCOL_VERSION:
        max_judge_attempts = config.get("max_judge_attempts")
        if (isinstance(max_judge_attempts, bool)
                or not isinstance(max_judge_attempts, int)
                or max_judge_attempts <= 0
                or max_judge_attempts != PILOT_V2_MAX_JUDGE_ATTEMPTS):
            raise InfraFailure(
                f"config {path}: protocol v2 requires "
                f"`max_judge_attempts` exactly "
                f"{PILOT_V2_MAX_JUDGE_ATTEMPTS}, got "
                f"{max_judge_attempts!r}"
            )
        if not config.get("nonstandard_config"):
            operator_image = config.get("operator_image_sha256")
            parser_name = config.get("artifact_parser")
            parser_version = config.get("artifact_parser_version")
            probe_receipt = config.get("judge_live_probe_receipt_sha256")
            probe_execution = config.get("judge_live_probe_execution_sha256")
            if (not isinstance(operator_image, str)
                    or OPERATOR_IMAGE_SHA256_RE.fullmatch(
                        operator_image) is None):
                raise InfraFailure(
                    f"config {path}: standard protocol v2 requires "
                    "`operator_image_sha256` as lowercase "
                    "`sha256:<64 hex>`")
            if (not isinstance(parser_name, str)
                    or ARTIFACT_PARSER_RE.fullmatch(parser_name) is None):
                raise InfraFailure(
                    f"config {path}: standard protocol v2 requires "
                    "`artifact_parser` as a lowercase parser identifier")
            if (not isinstance(parser_version, str)
                    or ARTIFACT_PARSER_VERSION_RE.fullmatch(
                        parser_version) is None):
                raise InfraFailure(
                    f"config {path}: standard protocol v2 requires "
                    "`artifact_parser_version` as numeric MAJOR.MINOR.PATCH")
            for field, digest in (
                    ("judge_live_probe_receipt_sha256", probe_receipt),
                    ("judge_live_probe_execution_sha256", probe_execution)):
                if not isinstance(digest, str) or SHA256_RE.fullmatch(
                        digest) is None:
                    raise InfraFailure(
                        f"config {path}: standard protocol v2 requires "
                        f"`{field}` as 64 lowercase hex characters")
            max_infra_retries = config.get("max_infra_retries")
            if (isinstance(max_infra_retries, bool)
                    or max_infra_retries != DEFAULT_MAX_INFRA_RETRIES):
                raise InfraFailure(
                    f"config {path}: standard protocol v2 requires "
                    f"`max_infra_retries` exactly "
                    f"{DEFAULT_MAX_INFRA_RETRIES}, got "
                    f"{max_infra_retries!r}"
                )
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
    # Keep legacy schedules byte-compatible when neither v2 field exists;
    # an explicitly versioned config binds both values into its identity.
    if ("protocol_version" in config or "max_judge_attempts" in config):
        material["protocol_version"] = config.get("protocol_version", 1)
        material["max_judge_attempts"] = config.get("max_judge_attempts")
        if config.get("protocol_version", 1) == PILOT_V2_PROTOCOL_VERSION:
            material["environment_policy_id"] = (
                PILOT_V2_ENVIRONMENT_POLICY_ID)
            material["judge_output_policy"] = (
                PILOT_V2_JUDGE_OUTPUT_POLICY)
            material["runtime_pins"] = protocol_v2_runtime_pins(config)
            material["judge_live_probe"] = (
                protocol_v2_live_probe_binding(config))
    return hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_json_object(path, what):
    """User-supplied JSON artifacts (schedules, manifests, seal manifests,
    drift reports) fail as classified infrastructure errors, never as
    OSError/JSONDecodeError/AttributeError tracebacks."""
    try:
        data = _json_without_duplicate_keys(
            Path(path).read_bytes(), f"{what} {path}")
    except OSError as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc
    except (json.JSONDecodeError, InfraFailure) as exc:
        raise InfraFailure(f"{what} {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InfraFailure(f"{what} {path} must be a JSON object")
    return data


def _decode_backend_text(data, stream):
    """Decode one backend-owned stream without exposing malformed bytes.

    Backend stdout/stderr are private transport data.  Letting ``subprocess``
    decode them in text mode can raise an unclassified ``UnicodeDecodeError``
    whose default representation includes byte offsets and fragments.  Keep
    capture byte-exact until the child is terminal, then fail closed with one
    stable, content-free classification.
    """
    if not isinstance(data, bytes):
        raise InfraFailure(f"backend {stream} was not captured as bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Leave the handler before constructing the public exception.
        # ``from None`` only suppresses display; raising inside the handler
        # would still retain the raw byte object in ``__context__``.
        pass
    raise InfraFailure(f"backend {stream} is not valid UTF-8")


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
        proc = subprocess.run(probe, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfraFailure(f"backend version probe failed: {exc}") from exc
    stdout = _decode_backend_text(proc.stdout, "version-probe stdout")
    stderr = _decode_backend_text(proc.stderr, "version-probe stderr")
    if proc.returncode != 0:
        raise InfraFailure(
            f"backend version probe exited {proc.returncode}: "
            f"{stderr.strip()[:200]}"
        )
    actual = stdout.strip()
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


def backend_env(profile, protocol_version=1):
    """Build the child environment without leaking operator credentials.

    Historical v1 reproduction keeps its original ambient-environment
    behavior.  Protocol v2 is prospective and fail-closed: only the fixed
    CLI/auth/proxy/TLS/locale allowlist crosses the session boundary.
    """
    if protocol_version == PILOT_V2_PROTOCOL_VERSION:
        env = {
            name: os.environ[name]
            for name in PILOT_V2_ENV_ALLOWLIST
            if name in os.environ
        }
        # Never inherit an operator-host temp path into a filesystem sandbox;
        # Linux supplies private /tmp and the macOS wrapper replaces it again.
        env["TMPDIR"] = "/tmp"
        env["RPA_ENVIRONMENT_POLICY"] = PILOT_V2_ENVIRONMENT_POLICY_ID
    else:
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
    data = read_input_bytes(path, what)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc


def read_input_bytes(path, what):
    """Read one stable, ordinary, single-link input through O_NOFOLLOW.

    Callers retain and use the returned bytes; they never authenticate one
    version and later reopen the pathname for routing or model input.
    """
    path = Path(path)
    flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
            raise OSError("input is not a single-link ordinary file")
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino)
                    != (before.st_dev, before.st_ino)):
                raise OSError("input changed identity while opening")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        current = path.lstat()
        stable_fields = ("st_dev", "st_ino", "st_nlink", "st_size",
                         "st_mtime_ns", "st_ctime_ns")
        if (not stat.S_ISREG(current.st_mode)
                or any(getattr(opened, field) != getattr(after, field)
                       or getattr(after, field) != getattr(current, field)
                       for field in stable_fields)):
            raise OSError("input changed while it was being read")
        return b"".join(chunks)
    except OSError as exc:
        raise InfraFailure(f"cannot read {what} {path}: {exc}") from exc


def _json_without_duplicate_keys(data, what):
    def reject_constant(token):
        raise ValueError(f"non-finite numeric literal {token} is forbidden")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8"),
                          object_pairs_hook=reject_duplicates,
                          parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError,
            RecursionError, OverflowError) as exc:
        raise InfraFailure(f"{what} is not strict UTF-8 JSON: {exc}") from exc


def _validate_v2_sealed_schemas(seal_doc, seal_files, seal_manifest_path,
                                include_text=False):
    """Resolve both role schemas inside the sealed package without allowing
    absolute paths, traversal, or symlink escape.  The sealed bytes must be
    the exact contract emitted by ``judge_contract`` for that role."""
    associations = seal_doc.get("judge_response_schemas")
    if (not isinstance(associations, dict)
            or set(associations) != {"scorer", "verifier"}
            or not all(isinstance(value, str) and value.strip()
                       for value in associations.values())):
        raise InfraFailure(
            "protocol v2 seal `judge_response_schemas` must map exactly "
            "`scorer` and `verifier` to nonempty package-relative paths"
        )
    if seal_manifest_path is None or seal_files is None:
        raise InfraFailure(
            "protocol v2 seal validation requires the seal manifest path "
            "and its sealed file map"
        )

    package_root = Path(seal_manifest_path).resolve().parent
    digests = {}
    texts = {}
    for role in ("scorer", "verifier"):
        ref = associations[role]
        rel = Path(ref)
        if ("\\" in ref or rel.is_absolute() or not rel.parts
                or any(part in ("", ".", "..") for part in rel.parts)
                or rel.as_posix() != ref):
            raise InfraFailure(
                f"sealed {role} response schema path `{ref}` is not one "
                f"canonical package-relative path"
            )
        resolved = (package_root / rel).resolve()
        try:
            resolved.relative_to(package_root)
        except ValueError as exc:
            raise InfraFailure(
                f"sealed {role} response schema `{ref}` escapes the "
                f"package directory"
            ) from exc
        expected_digest = seal_files.get(ref)
        if not isinstance(expected_digest, str) or not expected_digest:
            raise InfraFailure(
                f"sealed {role} response schema `{ref}` has no digest in "
                f"the seal file map"
            )
        data = read_input_bytes(resolved, f"sealed {role} response schema")
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest:
            raise InfraFailure(
                f"sealed {role} response schema `{ref}` differs from its "
                f"registered digest"
            )
        schema = _json_without_duplicate_keys(
            data, f"sealed {role} response schema `{ref}`")
        if schema != judge_contract.contract_schema(role):
            raise InfraFailure(
                f"sealed {role} response schema `{ref}` is not exactly "
                f"the harness contract version "
                f"{judge_contract.RESPONSE_SCHEMA_VERSION}"
            )
        digests[role] = actual_digest
        texts[role] = data.decode("utf-8")
    return (digests, texts) if include_text else digests


def _verify_v2_seal_package(config, seal_manifest_path):
    """Run the package-level verifier (file set, ordinary-file/symlink
    policy, canonical manifest, and every digest) without surfacing private
    package paths or contents in the classified error."""
    if seal_manifest_path is None:
        raise InfraFailure(
            "protocol v2 requires the complete atomic seal package")
    try:
        registration = seal_package.verify_package(
            Path(seal_manifest_path).parent, seal_manifest_path)
    except seal_package.SealError as exc:
        raise InfraFailure(
            "protocol v2 atomic seal package failed full verification"
        ) from exc
    if registration.get("seal_package_sha256") != config.get(
            "seal_package_sha256"):
        raise InfraFailure(
            "protocol v2 atomic seal package differs from its registered "
            "SHA-256"
        )
    return registration


def validate_sealed_judge_config(config, seal_doc, seal_manifest_path=None,
                                 seal_files=None, include_schema_text=False):
    """The atomic seal registers the judge session configuration; the
    runtime config must match it exactly. config_digest alone binds
    whatever judge settings existed at schedule creation — without this
    check, a config changed after sealing but before scheduling would pass
    every later digest comparison while scoring under unregistered judge
    settings."""
    require_standard_v2_registration(config)
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
    if config.get("protocol_version", 1) != PILOT_V2_PROTOCOL_VERSION:
        return {}
    _verify_v2_seal_package(config, seal_manifest_path)
    if seal_doc.get("protocol_version") != PILOT_V2_PROTOCOL_VERSION:
        raise InfraFailure(
            "protocol v2 config requires a seal with `protocol_version: 2`"
        )
    if seal_doc.get("nonstandard_config") is not bool(
            config.get("nonstandard_config")):
        raise InfraFailure(
            "protocol v2 seal nonstandard marker differs from the runtime "
            "configuration")
    configured_attempts = config.get("max_judge_attempts")
    if (isinstance(configured_attempts, bool)
            or not isinstance(configured_attempts, int)
            or configured_attempts != PILOT_V2_MAX_JUDGE_ATTEMPTS):
        raise InfraFailure(
            "protocol v2 config requires `max_judge_attempts` exactly 3"
        )
    if (seal_doc.get("max_judge_attempts") != configured_attempts
            or seal_doc.get("max_judge_attempts")
            != PILOT_V2_MAX_JUDGE_ATTEMPTS):
        raise InfraFailure(
            "protocol v2 seal must record `max_judge_attempts: 3` and "
            "match the runtime config"
        )
    if seal_doc.get("judge_retry_policy") != PILOT_V2_JUDGE_RETRY_POLICY:
        raise InfraFailure(
            "protocol v2 seal `judge_retry_policy` must be exactly "
            f"{PILOT_V2_JUDGE_RETRY_POLICY!r}"
        )
    if seal_doc.get("judge_output_policy") != PILOT_V2_JUDGE_OUTPUT_POLICY:
        raise InfraFailure(
            "protocol v2 seal `judge_output_policy` must be exactly "
            f"{PILOT_V2_JUDGE_OUTPUT_POLICY!r}"
        )
    live_probe = protocol_v2_live_probe_binding(config)
    if not config.get("nonstandard_config"):
        registered_probe = pilot_registration.live_probe_binding()
        if pilot_registration.live_probe_registration_pending():
            raise InfraFailure(
                "standard protocol v2 requires a publicly registered live "
                "judge probe; pending registration cannot authorize a seal")
        if live_probe != registered_probe:
            raise InfraFailure(
                "standard protocol v2 live judge probe differs from the "
                "public receipt/execution registration")
    if seal_doc.get("judge_live_probe") != live_probe:
        raise InfraFailure(
            "protocol v2 seal `judge_live_probe` differs from the runtime "
            "receipt/execution registration")
    if seal_doc.get("aggregation_policy") != PILOT_V2_AGGREGATION_POLICY:
        raise InfraFailure(
            "protocol v2 seal `aggregation_policy` must be exactly "
            f"{PILOT_V2_AGGREGATION_POLICY!r}"
        )
    return _validate_v2_sealed_schemas(
        seal_doc, seal_files, seal_manifest_path,
        include_text=include_schema_text)


def parse_seal_manifest(seal_bytes, path):
    """The registered seal manifest is operator-supplied input: decode and
    parse through the classified boundary, and require `files` to be an
    object before any dereference."""
    try:
        seal_doc = _json_without_duplicate_keys(
            seal_bytes, f"seal manifest {path}")
    except InfraFailure as exc:
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


def decode_task_bytes(task_bytes, task_path):
    try:
        return task_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfraFailure(
            f"cannot decode task file {task_path} as UTF-8") from exc


def extract_task_prompt_text(text, task_path):
    """Only the `## Task prompt` section may reach an evaluated session.
    The marker is required unconditionally: a malformed task must fail the
    run, never silently alter the experiment by sending the whole file."""
    match = re.search(
        r"^## Task prompt\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not match or not match.group(1).strip():
        raise InfraFailure(
            f"{task_path}: no `## Task prompt` marker — refusing to send "
            f"the file to an evaluated run"
        )
    return match.group(1).strip(), text


def extract_task_prompt(task_path):
    task_bytes = read_task_bytes(task_path)
    return extract_task_prompt_text(
        decode_task_bytes(task_bytes, task_path), task_path)


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


def with_stream_json_transport(cmd):
    """Add CLI flags owned by the stream-json transport to a backend argv.

    This must run before ``apply_sandbox``: a wrapper may have its own
    ``--verbose`` option, which must not be mistaken for the backend flag.
    """
    full = list(cmd)
    if "--verbose" not in full:
        full.append("--verbose")
    return full


def kill_process_group(proc):
    """Ensure no subprocess from a finished model session survives it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def spawn_session(cmd, prompt, cwd, env, timeout, resume=None,
                  workflow_abort_exits=(), heartbeat_call=None,
                  heartbeat_call_total=None, heartbeat_completed=None,
                  heartbeat_total=None):
    """`workflow_abort_exits` lists backend exit codes that represent an
    evaluated-workflow abort: those are WorkflowFailure (counted, never
    replaced), while any other nonzero exit is an infra crash (rerun). The
    real-backend preflight establishes the pinned CLI's abort codes."""
    full = list(cmd)
    if resume:
        full += ["--resume", resume]
    # `-p` selects Claude Code's non-interactive mode; when no positional
    # prompt follows it, Claude 2.1.220 reads the prompt from stdin.  Task,
    # continuation, document, rubric, and judge-policy bytes must never be
    # placed in argv, where another process on the host could read them.
    full += ["-p", "--output-format", "stream-json"]
    prompt_invalid = False
    try:
        prompt_bytes = prompt.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        # As above, leave the handler before raising so a private prompt is
        # not retained in a UnicodeEncodeError exception context.
        prompt_invalid = True
    if prompt_invalid:
        raise InfraFailure(
            "backend prompt is not valid UTF-8 text")
    try:
        proc = subprocess.Popen(
            full, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, stdin=subprocess.PIPE,
            start_new_session=True
        )
    except OSError as exc:
        raise InfraFailure(f"backend could not be spawned: {exc}") from exc
    timeout_error = None
    try:
        with progress_heartbeat(
                "workflow-model-call", completed=heartbeat_completed,
                total=heartbeat_total, call=heartbeat_call,
                call_total=heartbeat_call_total):
            stdout_bytes, stderr_bytes = proc.communicate(
                input=prompt_bytes, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # The session runs in its OWN process group (start_new_session):
        # on timeout the WHOLE tree is killed, so spawned tool
        # subprocesses cannot keep consuming the budget or touching the
        # disposable worktree after the timeout is recorded.
        timeout_error = exc
        kill_process_group(proc)
        stdout_bytes, stderr_bytes = proc.communicate()
    # The parent CLI exiting is not proof that its tool subprocesses exited.
    # Kill the dedicated process group after *every* terminal parent outcome
    # before artifact discovery or worktree cleanup.
    kill_process_group(proc)

    try:
        stdout = _decode_backend_text(stdout_bytes, "stdout")
    except InfraFailure as exc:
        if timeout_error is not None:
            raise BlockingInfraFailure(
                "timed-out backend emitted non-UTF-8 stdout; the observed "
                "timeout cannot be counted or rerun",
                failure_kind="timeout",
            ) from exc
        if proc.returncode in workflow_abort_exits:
            raise BlockingInfraFailure(
                "aborted backend emitted non-UTF-8 stdout; the observed "
                "abort cannot be counted or rerun",
                failure_kind="abort",
            ) from exc
        raise
    try:
        stderr = _decode_backend_text(stderr_bytes, "stderr")
    except InfraFailure as exc:
        if timeout_error is not None:
            # The transcript remains valid accounting evidence.  Preserve
            # the already-observed timeout without retaining or repairing
            # the malformed diagnostic stream.
            raise WorkflowFailure(
                f"session timed out after {timeout}s; backend stderr was "
                "not valid UTF-8",
                stdout=stdout, failure_kind="timeout",
            ) from exc
        if proc.returncode in workflow_abort_exits:
            raise WorkflowFailure(
                f"workflow aborted (exit {proc.returncode}); backend "
                "stderr was not valid UTF-8",
                stdout=stdout, failure_kind="abort",
            ) from exc
        raise
    if timeout_error is not None:
        raise WorkflowFailure(
            f"session timed out after {timeout}s", stdout=stdout,
            failure_kind="timeout",
        ) from timeout_error
    if proc.returncode != 0:
        detail = (stderr or "").strip()[:500]
        if proc.returncode in workflow_abort_exits:
            # Counted experimental outcome: keep the partial transcript so
            # the failed run's tree-wide accounting survives.
            raise WorkflowFailure(
                f"workflow aborted (exit {proc.returncode}): {detail}",
                stdout=stdout,
                failure_kind="abort",
            )
        raise InfraFailure(f"backend exited {proc.returncode}: {detail}")
    return stdout


def spawn_judge_session_capped(cmd, prompt, cwd, env, timeout,
                               raw_stream_path, max_stream_bytes,
                               structured_output_schema=None,
                               heartbeat_call=None,
                               heartbeat_call_total=None,
                               heartbeat_completed=None,
                               heartbeat_total=None):
    """Run one v2 judge with stdout captured to disk and a live size cap.

    Disk capture avoids unbounded in-memory ``communicate`` buffering. The
    process group is killed as soon as the observed stream exceeds the cap;
    the exact emitted bytes remain at ``raw_stream_path`` for audit.
    Returns ``(text_or_none, byte_count, sha256, launch_defects, external)``.
    ``external`` means the preserved sidecar is intentionally not embedded
    in the bounded attempt JSON.
    """
    # See `spawn_session`: the full sealed judge input travels through stdin,
    # never a process-list-visible positional argv element. Protocol v2's one
    # argv exception is a deterministic generic/public structural schema: it
    # contains no sealed prompt, rubric, context, task, or document bytes.
    full = list(cmd)
    if structured_output_schema is not None:
        if (not isinstance(structured_output_schema, str)
                or not structured_output_schema):
            raise InfraFailure(
                "judge structured-output schema must be nonempty text")
        full += ["--json-schema", structured_output_schema]
    full += ["-p", "--output-format", "stream-json"]
    raw_stream_path = Path(raw_stream_path)
    launch_defects = []
    with (raw_stream_path.open("w+b") as raw_handle,
          tempfile.TemporaryFile() as err,
          tempfile.TemporaryFile() as prompt_handle):
        # Preload an anonymous, automatically unlinked file and present it as
        # stdin. Unlike a pipe feeder, this cannot block on a full pipe or
        # leave an unbounded writer-thread join after a timeout.
        prompt_handle.write(prompt.encode("utf-8"))
        prompt_handle.seek(0)
        try:
            proc = subprocess.Popen(
                full, cwd=cwd, env=env, stdin=prompt_handle,
                stdout=raw_handle, stderr=err, start_new_session=True)
        except OSError as exc:
            launch_defects.append(f"judge transport failed: {exc}")
            proc = None
        oversized = False
        timed_out = False
        if proc is not None:
            deadline = time.monotonic() + timeout
            with progress_heartbeat(
                    "judge-model-call", completed=heartbeat_completed,
                    total=heartbeat_total, call=heartbeat_call,
                    call_total=heartbeat_call_total):
                while proc.poll() is None:
                    raw_handle.flush()
                    if os.fstat(raw_handle.fileno()).st_size > max_stream_bytes:
                        oversized = True
                    elif time.monotonic() >= deadline:
                        timed_out = True
                    else:
                        time.sleep(0.02)
                        continue
                    kill_process_group(proc)
                    proc.wait()
                    break
            # A successful/nonzero parent can leave detached-stdio tool
            # children in its process group. Reap them before reading the
            # final stream or tearing down judge isolation.
            kill_process_group(proc)
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
            byte_count = os.fstat(raw_handle.fileno()).st_size
            oversized = oversized or byte_count > max_stream_bytes
            err.seek(0)
            detail = err.read(500).decode("utf-8", "replace").strip()
            if oversized:
                launch_defects.append(
                    f"judge raw stream exceeded {max_stream_bytes} bytes")
            elif timed_out:
                launch_defects.append(
                    f"judge session failed: session timed out after "
                    f"{timeout}s")
            elif proc.returncode != 0:
                launch_defects.append(
                    f"judge transport failed: backend exited "
                    f"{proc.returncode}: {detail}")
        else:
            raw_handle.flush()
            byte_count = os.fstat(raw_handle.fileno()).st_size
        raw_handle.seek(0)
        digest = hashlib.sha256()
        chunks = [] if not oversized else None
        while True:
            chunk = raw_handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
    if oversized:
        return None, byte_count, digest.hexdigest(), launch_defects, True
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        # Preserve the exact bytes as an external audit sidecar and consume
        # the attempt as invalid; tolerant replacement would be repair.
        launch_defects.append("judge raw stream is not UTF-8")
        return None, byte_count, digest.hexdigest(), launch_defects, True
    durable_unlink(raw_stream_path, missing_ok=True)
    return text, byte_count, digest.hexdigest(), launch_defects, False


def _nonnegative_event_int(value, label):
    """Strict accounting integer at the backend transport boundary."""
    if (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise InfraFailure(
            f"{label} must be a nonnegative integer, got {value!r}")
    return value


def _required_usage_int(usage, key, label):
    if key not in usage:
        raise InfraFailure(f"{label} is missing mandatory `{key}`")
    return _nonnegative_event_int(usage[key], f"{label} {key}")


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
        usage = event.get("usage")
        if not isinstance(usage, dict):
            raise InfraFailure("synthetic node usage must be an object")
        model = event.get("model")
        if not isinstance(model, str) or not model:
            raise InfraFailure("synthetic node model must be nonempty text")
        subagent = event.get("subagent", False)
        if not isinstance(subagent, bool):
            raise InfraFailure("synthetic node subagent flag must be boolean")
        input_tokens = _required_usage_int(
            usage, "input_tokens", "node usage")
        output_tokens = _required_usage_int(
            usage, "output_tokens", "node usage")
        if input_tokens + output_tokens == 0:
            raise InfraFailure(
                "node usage must contain a positive model-token total")
        return {
            "model": model,
            "effort": event.get("effort"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "tool_calls": _nonnegative_event_int(
                event.get("tool_calls", 0), "node tool_calls"),
            "subagent": subagent,
            "subagent_id": event.get("subagent_id"),
            "subagent_launches": _nonnegative_event_int(
                event.get("subagent_launches", 0),
                "node subagent_launches"),
        }
    if event.get("type") == "assistant":
        message = event.get("message")
        if not isinstance(message, dict):
            raise InfraFailure("assistant event message must be an object")
        # The real CLI also emits CLIENT-GENERATED assistant notices (e.g.
        # "Unknown command: ...") marked `model: "<synthetic>"`. They are
        # not API turns: no runtime ran and no usage was consumed, so they
        # are excluded from parity validation and accounting. A session
        # consisting only of synthetic notices therefore yields no nodes —
        # exactly the no-parity-evidence case, which blocks instead of
        # counting (real-backend shakedown finding, 2026-07-27).
        if message.get("model") == "<synthetic>":
            return None
        model = message.get("model")
        if not isinstance(model, str) or not model:
            raise InfraFailure("assistant node model must be nonempty text")
        usage = message.get("usage")
        if not isinstance(usage, dict):
            raise InfraFailure("assistant node usage must be an object")
        content = message.get("content")
        if (not isinstance(content, list)
                or any(not isinstance(block, dict) for block in content)):
            raise InfraFailure(
                "assistant node content must be an array of objects")
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
        input_total = sum((
            _required_usage_int(
                usage, "input_tokens", "assistant usage"),
            _nonnegative_event_int(
                usage.get("cache_creation_input_tokens", 0),
                "assistant cache_creation_input_tokens"),
            _nonnegative_event_int(
                usage.get("cache_read_input_tokens", 0),
                "assistant cache_read_input_tokens"),
        ))
        parent_id = event.get("parent_tool_use_id")
        if parent_id is not None and (
                not isinstance(parent_id, str) or not parent_id):
            raise InfraFailure(
                "assistant parent_tool_use_id must be null or nonempty text")
        output_tokens = _required_usage_int(
            usage, "output_tokens", "assistant usage")
        if input_total + output_tokens == 0:
            raise InfraFailure(
                "assistant usage must contain a positive model-token total")
        return {
            "model": model,
            "effort": event.get("effort"),
            "input_tokens": input_total,
            "output_tokens": output_tokens,
            "tool_calls": tool_calls,
            "subagent": parent_id is not None,
            # Identity, not just a boolean: several messages from one
            # subagent must stay distinguishable from one message each
            # from several subagents, or "subagents spawned" is unmeasurable.
            "subagent_id": parent_id,
            "subagent_launches": subagent_launches,
        }
    return None


def parse_transcript(stdout):
    """Parse stream-json lines into accounting nodes plus the final response
    text. Understands both the synthetic mock schema and the real Claude
    headless stream (see `_node_from_event`); `session_id` comes from any
    event carrying one, response text from the `result` event."""
    nodes, session_id, result_parts = [], None, []
    for line_number, line in enumerate(stdout.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = _json_without_duplicate_keys(
                line.encode("utf-8"), "backend stream event")
        except InfraFailure as exc:
            raise InfraFailure(f"unparseable backend output line: {line[:200]}") from exc
        if not isinstance(event, dict):
            raise InfraFailure("backend stream event is not a JSON object")
        if "session_id" in event:
            candidate = event["session_id"]
            if not isinstance(candidate, str) or not candidate.strip():
                raise InfraFailure(
                    f"stream line {line_number} has a non-string or empty "
                    f"session_id")
            elif session_id is None:
                session_id = candidate
            elif candidate != session_id:
                raise InfraFailure(
                    f"stream line {line_number} conflicts with the first "
                    f"session_id")
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
    """Extract nodes from a partial timeout/abort transcript.

    A partial stream may legitimately omit its final result, but every byte
    that did arrive is accounting evidence.  Reject malformed/non-object
    events instead of accepting a convenient valid prefix and undercounting
    the already-observed workflow failure.
    """
    nodes = []
    for line_number, line in enumerate((stdout or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = _json_without_duplicate_keys(
                line.encode("utf-8"), "partial backend stream event")
        except InfraFailure as exc:
            raise InfraFailure(
                f"partial stream line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(event, dict):
            raise InfraFailure(
                f"partial stream line {line_number} is not a JSON object")
        node = _node_from_event(event)
        if node is not None:
            nodes.append(node)
    return nodes


def parse_result_tolerant(stdout):
    """Best-effort final-response extraction from a failed partial stream.

    Timeout/abort is already a workflow outcome, so malformed transport is
    not repaired here.  Valid result events that did arrive remain necessary
    ritual-stop evidence and must not disappear merely because the process
    later exited or hit its deadline.
    """
    result_parts = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = _json_without_duplicate_keys(
                line.encode("utf-8"), "partial backend stream event")
        except InfraFailure:
            continue
        if (isinstance(event, dict)
                and event.get("type") == "result"
                and event.get("result") is not None):
            result_parts.append(str(event["result"]))
    return "\n".join(result_parts)


def account(nodes):
    totals = {"main": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
              "subagents": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0}}
    for node in nodes:
        if not isinstance(node, dict):
            raise InfraFailure("accounting node must be an object")
        if not isinstance(node.get("subagent"), bool):
            raise InfraFailure("accounting node subagent flag must be boolean")
        for field in ("input_tokens", "output_tokens", "tool_calls"):
            _nonnegative_event_int(
                node.get(field), f"accounting node {field}")
        if node["input_tokens"] + node["output_tokens"] <= 0:
            raise InfraFailure(
                "every model-bearing accounting node must carry positive "
                "token usage")
        _nonnegative_event_int(
            node.get("subagent_launches", 0),
            "accounting node subagent_launches")
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


def refuse_v2_structured_output_override(cmd):
    """Keep the public generation schema exclusively harness-owned."""

    if any(
            part == "--json-schema" or part.startswith("--json-schema=")
            for part in cmd):
        raise InfraFailure(
            "protocol v2 judge command must not supply `--json-schema`; "
            "the harness owns the exact public structural schema binding"
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


def validate_intervention_log(record):
    """Strictly recompute the complete ritual-stop evidence for one run."""
    log = record.get("interventions_log")
    if not isinstance(log, list):
        raise InfraFailure("run interventions_log must be an array")
    answered = 0
    unanswered_positions = []
    for position, item in enumerate(log):
        if (not isinstance(item, dict)
                or item.get("classification") not in {
                    "empty", "question", "statement"}
                or not isinstance(item.get("answered"), bool)
                or not isinstance(item.get("response"), str)
                or item != classify_stop(
                    item.get("response"), answered=item.get("answered"))):
            raise InfraFailure(
                "run intervention evidence differs from strict "
                "recomputation")
        if item["answered"]:
            answered += 1
        else:
            unanswered_positions.append(position)
    intervention_count = record.get("interventions")
    if (not isinstance(intervention_count, int)
            or isinstance(intervention_count, bool)
            or intervention_count < 0
            or intervention_count != answered
            or len(unanswered_positions) > 1
            or (unanswered_positions
                and unanswered_positions[0] != len(log) - 1)):
        raise InfraFailure(
            "run intervention counts or unanswered-stop placement are "
            "invalid")
    return len(log)


def snapshot_research(worktree):
    research = Path(worktree) / "thoughts" / "shared" / "research"
    if not research.is_dir():
        return {}
    return {p: p.stat().st_mtime for p in research.glob("*.md")}


def find_new_artifacts(worktree, before):
    """Return every document created or modified during the run.

    Selecting only the newest file would silently discard other observed
    workflow output.  The protocol's immutable population is one nonempty
    document per scheduled slot, so the caller must explicitly classify zero,
    one, or multiple fresh documents.
    """
    research = Path(worktree) / "thoughts" / "shared" / "research"
    if not research.is_dir():
        return []
    fresh = []
    for path in research.glob("*.md"):
        try:
            changed = path not in before or path.stat().st_mtime > before[path]
        except OSError:
            # Let the caller's byte read classify a disappeared/unreadable
            # fresh path as ambiguous observed output.
            changed = True
        if changed:
            fresh.append(path)
    return sorted(fresh, key=lambda path: path.name)


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
    lines = text.splitlines()
    # The frontmatter is metadata, not judged content. Replace the complete
    # block rather than trying to interpret every legal YAML spelling
    # (quoted/explicit/flow keys and block scalars can all hide identity from
    # a line-oriented masker).
    first_content = next(
        (index for index, line in enumerate(lines) if line.strip()), None)
    frontmatter_open = (
        first_content is not None
        and re.fullmatch(r"[ \t]*---[ \t]*", lines[first_content])
    )
    if frontmatter_open:
        closing = next(
            (index for index in range(first_content + 1, len(lines))
             if FRONTMATTER_DELIMITER_RE.fullmatch(lines[index])),
            None,
        )
        if closing is not None:
            lines[first_content:closing + 1] = [
                "---",
                f"anonymized_run: '[anonymized:{run_id}]'",
                "---",
            ]
        else:
            # An unclosed/indented opening is a gate failure, but its
            # diagnostic copy is still judged.  YAML permits arbitrarily
            # nested continuations, anchors, tags and flow constructs, so a
            # regex cannot prove where malformed metadata ends.  Erase the
            # entire metadata-looking prefix up to the first Markdown
            # heading (or EOF) and retain the research body from there.
            body_start = next(
                (index for index in range(first_content + 1, len(lines))
                 if re.match(r"^#{1,6}\s+", lines[index])),
                len(lines),
            )
            lines[first_content:body_start] = [
                "---",
                f"anonymized_run: '[anonymized:{run_id}]'",
                "---",
                "",
            ]
    # Malformed/unclosed frontmatter is still diagnostic-judge input. Mask
    # YAML's two-line explicit-key spelling (`? researcher` / `: Alice`),
    # including sequence-wrapped keys, before the ordinary mapping pass.
    sensitive_aliases = set()
    for index, line in enumerate(lines):
        explicit = FINGERPRINT_EXPLICIT_KEY_RE.match(line)
        if not explicit:
            continue
        lines[index] = (f"{explicit.group('key').lower()}: "
                        f"'[anonymized:{run_id}]'")
        if index + 1 < len(lines):
            value_match = YAML_EXPLICIT_VALUE_RE.match(lines[index + 1])
            if value_match:
                value = value_match.group("value").lstrip()
                alias_match = YAML_ALIAS_RE.match(value)
                if alias_match:
                    sensitive_aliases.add(alias_match.group("name"))
                value_indent = len(lines[index + 1]) - len(
                    lines[index + 1].lstrip(" \t"))
                lines[index + 1] = ""
                cursor = index + 2
                while cursor < len(lines):
                    continuation = lines[cursor]
                    indent = len(continuation) - len(
                        continuation.lstrip(" \t"))
                    if continuation.strip() and indent <= value_indent:
                        break
                    lines[cursor] = ""
                    cursor += 1
    block_indent = None
    for j, line in enumerate(lines):
        leading = len(line) - len(line.lstrip(" \t"))
        if block_indent is not None:
            if not line.strip() or leading > block_indent:
                lines[j] = ""
                continue
            block_indent = None
        match = FINGERPRINT_KEY_RE.search(line)
        if match:
            value = line[match.end():].lstrip()
            alias_match = YAML_ALIAS_RE.match(value)
            if alias_match:
                sensitive_aliases.add(alias_match.group("name"))
            lines[j] = (f"{match.group('key').lower()}: "
                        f"'[anonymized:{run_id}]'")
            # Plain empty values, malformed folded continuations, and legal
            # block scalars can all carry identity on subsequent indented
            # lines.  Conservatively erase every more-indented continuation.
            block_indent = leading
    # A fingerprint can be expressed through a YAML alias while the secret
    # appears on an innocently named anchor definition (`identity: &who
    # Alice`).  Once a fingerprint references an alias, conservatively erase
    # each matching anchor definition and any block-scalar continuation.
    if sensitive_aliases:
        anchor_block_indent = None
        for index, line in enumerate(lines):
            leading = len(line) - len(line.lstrip(" \t"))
            if anchor_block_indent is not None:
                if not line.strip() or leading > anchor_block_indent:
                    lines[index] = ""
                    continue
                anchor_block_indent = None
            anchor_match = YAML_ANCHOR_RE.search(line)
            if (anchor_match is None
                    or anchor_match.group("name") not in sensitive_aliases):
                continue
            lines[index] = f"anonymized_anchor: '[anonymized:{run_id}]'"
            anchor_block_indent = leading
    body = "\n".join(lines)
    body = BOLD_FINGERPRINT_RE.sub(
        lambda match: (
            f"**{match.group('label')}**: [anonymized:{run_id}]"),
        body,
    )
    return body + ("\n" if not body.endswith("\n") else "")


def run_task(config, arm_name, task_path, repo_dir, output_dir, attempt=1,
             scheduled=False, schedule_binding=None, output_binding=None,
             task_snapshot=None, heartbeat_completed=None,
             heartbeat_total=None):
    require_standard_v2_registration(config)
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
    if output_binding is None:
        output_dir, output_binding = bind_output_directory(output_dir)
    else:
        output_dir = verify_output_directory(
            Path(output_dir), output_binding, "run output directory")
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
    v2 = config.get("protocol_version", 1) == PILOT_V2_PROTOCOL_VERSION
    if v2:
        record.update({
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "runtime_pins": protocol_v2_runtime_pins(config),
            "failure_kind": None,
            "artifact_gate": "not_evaluated",
            "raw_sha256": None,
            "telemetry_policy_id": PILOT_V2_AGGREGATION_POLICY["telemetry"],
            "telemetry_eligible": False,
            "telemetry_exclusion_reason": "run_not_terminal",
        })
        if scheduled:
            if not isinstance(schedule_binding, dict):
                raise InfraFailure(
                    "protocol v2 scheduled run has no immutable schedule "
                    "binding"
                )
            binding_digest = schedule_binding.get("schedule_digest")
            binding_index = schedule_binding.get("schedule_index")
            if (not isinstance(binding_digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", binding_digest)
                    or isinstance(binding_index, bool)
                    or not isinstance(binding_index, int)
                    or binding_index < 0):
                raise InfraFailure(
                    "protocol v2 scheduled run has an invalid immutable "
                    "schedule binding"
                )
            record.update({
                "schedule_digest": binding_digest,
                "schedule_index": binding_index,
            })
    out = Path(output_dir)
    worktree = None
    all_nodes = []
    effort_modes = set()
    started = None
    # A timeout/registered abort can happen after the workflow has already
    # written a document.  Protocol v2 keeps that terminal workflow outcome,
    # but the produced document still owes the artifact gate and both judge
    # roles.  Capture the failure here and finish harvesting the artifact
    # before re-raising it as the final run status.
    terminal_workflow_failure = None
    try:
        # Immutable bindings recorded in the run record itself: orphan
        # adoption after a crash trusts a record only when these match the
        # current schedule's registered digests — a record produced under
        # an earlier task revision or runtime configuration is stale, not
        # adoptable.
        if task_snapshot is None:
            task_bytes = read_task_bytes(task_path)
        elif isinstance(task_snapshot, bytes):
            task_bytes = task_snapshot
        else:
            raise InfraFailure("task snapshot must contain exact bytes")
        task_text = decode_task_bytes(task_bytes, task_path)
        record["config_digest"] = config_digest(config)
        record["task_sha256"] = hashlib.sha256(task_bytes).hexdigest()
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
        prompt, _task_text = extract_task_prompt_text(task_text, task_path)
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
        cmd = with_stream_json_transport(cmd)
        cmd = apply_sandbox(config, cmd, worktree, profile)
        env = backend_env(profile, config.get("protocol_version", 1))
        abort_exits = validate_abort_exits(config)
        before = snapshot_research(worktree)
        # Duration budgets and latency telemetry share one monotonic clock;
        # wall-clock/NTP adjustments must neither extend the registered
        # compute ceiling nor bias the latency pass bar.
        started = time.monotonic()
        # ONE run-level deadline shared by the initial session and every
        # continuation: a per-session reset would grant stop-prone arms up
        # to (1 + MAX_CONTINUATIONS)x the registered compute ceiling.
        deadline = started + config["timeout_seconds"]

        def _spawn(prompt_text, resume=None):
            verify_output_directory(
                out, output_binding, "run output directory")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkflowFailure(
                    f"run-level deadline of {config['timeout_seconds']}s "
                    f"exhausted before the next session could start",
                    failure_kind="timeout",
                )
            # A timeout/abort WorkflowFailure carries the partial transcript:
            # harvest its nodes before propagating so the counted failure
            # keeps the cost it already incurred. Runtime drift outranks the
            # workflow verdict — partial nodes on the wrong model/effort mean
            # the run is invalid (infra, re-executed), not a counted outcome.
            try:
                return spawn_session(cmd, prompt_text, worktree, env,
                                     remaining, resume=resume,
                                     workflow_abort_exits=abort_exits,
                                     heartbeat_call=(
                                         record["interventions"] + 1),
                                     heartbeat_call_total=(
                                         MAX_CONTINUATIONS + 1),
                                     heartbeat_completed=heartbeat_completed,
                                     heartbeat_total=heartbeat_total)
            except WorkflowFailure as wf:
                try:
                    partial = parse_nodes_tolerant(wf.stdout)
                    if not partial:
                        raise InfraFailure(
                            "failed session emitted no accounting nodes")
                    validate_models(partial, arm["model"])
                    effort_capture = validate_efforts(
                        partial, arm.get("effort", "default"))
                    partial_accounting = account(partial)
                    if (partial_accounting["subagent_launches"]
                            > partial_accounting["subagent_children"]):
                        raise InfraFailure(
                            "subagent launch in the failed session has no "
                            "model-bearing child accounting")
                except InfraFailure as exc:
                    # The timeout/abort was already observed and may never
                    # be replaced. Any incomplete accounting or runtime
                    # parity evidence also makes it uncountable, so this is
                    # a terminal operator block — never an infrastructure
                    # retry that would add a second workflow observation.
                    raise BlockingInfraFailure(
                        "workflow-shaped failure carried invalid accounting "
                        "or incomplete runtime parity evidence; "
                        "the observed timeout/abort cannot be counted or "
                        f"rerun ({exc})",
                        failure_kind=wf.failure_kind,
                    ) from exc
                effort_modes.add(effort_capture)
                all_nodes.extend(partial)
                raise

        def _discover_artifact():
            """Classify the slot's complete fresh-document population.

            Empty/whitespace-only files are not documents and therefore keep
            the driver looking for an artifact. More than one nonempty file
            cannot be represented as the registered one-document run cell;
            preserve byte-exact evidence and terminally block the round rather
            than selecting a convenient winner.
            """
            nonempty = []
            empty = []
            for path in find_new_artifacts(worktree, before):
                try:
                    content = path.read_bytes()
                except OSError as exc:
                    raise BlockingInfraFailure(
                        "fresh artifact population became unreadable after "
                        "the backend ran; the observed slot cannot be rerun",
                        failure_kind="artifact_contract",
                    ) from exc
                item = {
                    "source_name": path.name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                }
                if content.strip():
                    nonempty.append((path, content, item))
                else:
                    empty.append(item)
            if empty:
                record["empty_artifacts"] = empty
            if len(nonempty) > 1:
                preserved = []
                for index, (_path, content, item) in enumerate(nonempty, 1):
                    evidence_path = out / (
                        f"run-{run_id}-extra-{index}.md")
                    verify_output_directory(
                        out, output_binding, "run output directory")
                    atomic_write_bytes(evidence_path, content)
                    preserved.append({
                        **item,
                        "evidence_file": evidence_path.name,
                    })
                record["produced_artifacts"] = preserved
                raise BlockingInfraFailure(
                    f"workflow produced {len(nonempty)} nonempty research "
                    f"documents for one registered schedule slot; the "
                    f"harness never selects one post hoc and this round "
                    f"cannot be resumed",
                    failure_kind="artifact_contract",
                )
            return nonempty[0][0] if nonempty else None

        # Durable journal BEFORE the backend launches: if the harness dies
        # after the session completes but before the terminal record is
        # written, the schedule finds this in-progress marker (with its
        # digest bindings) and blocks instead of silently executing an
        # extra observed replicate.
        verify_output_directory(out, output_binding, "run output directory")
        record["status"] = "in_progress"
        atomic_write_text(out / f"run-{run_id}.json",
                          json.dumps(record, indent=2) + "\n")
        artifact = None
        session_id = None
        response = ""
        try:
            stdout = _spawn(prompt)
        except WorkflowFailure as exc:
            terminal_workflow_failure = exc
            response = parse_result_tolerant(exc.stdout)
            artifact = _discover_artifact()
        else:
            session_id, nodes, response = parse_transcript(stdout)
            validate_models(nodes, arm["model"])
            effort_modes.add(validate_efforts(
                nodes, arm.get("effort", "default")))
            all_nodes.extend(nodes)
            artifact = _discover_artifact()
        while (terminal_workflow_failure is None
               and artifact is None
               and record["interventions"] < MAX_CONTINUATIONS):
            record["interventions"] += 1
            # The pre-artifact response IS the ritual-stop evidence: keep it
            # verbatim and tagged, or stops are uncountable afterwards.
            record["interventions_log"].append(classify_stop(response))
            try:
                stdout = _spawn(CONTINUATION_MESSAGE, resume=session_id)
            except WorkflowFailure as exc:
                terminal_workflow_failure = exc
                response = parse_result_tolerant(exc.stdout)
                artifact = _discover_artifact()
            else:
                session_id, nodes, response = parse_transcript(stdout)
                validate_models(nodes, arm["model"])
                effort_modes.add(
                    validate_efforts(nodes, arm.get("effort", "default")))
                all_nodes.extend(nodes)
                artifact = _discover_artifact()
        if len(effort_modes) > 1:
            message = (
                "inconsistent effort capture across sessions — run "
                "invalidated")
            if terminal_workflow_failure is not None:
                raise BlockingInfraFailure(
                    f"{message}; the observed timeout/abort cannot be "
                    f"counted or rerun",
                    failure_kind=terminal_workflow_failure.failure_kind,
                )
            raise InfraFailure(message)
        record["effort_capture"] = effort_modes.pop()
        record["wall_seconds"] = round(time.monotonic() - started, 3)
        record["accounting"] = account(all_nodes)
        record["nodes"] = all_nodes
        if artifact is None:
            # The exhausted run's final response is itself a pre-artifact
            # stop — unanswered, but it must still be counted or the
            # intervention/ritual-stop metrics underreport by one.
            record["interventions_log"].append(
                classify_stop(response, answered=False))
        subagent_policy_failure = bool(
            arm.get("forbid_subagents")
            and record["accounting"]["subagents_spawned"])
        if (v2 and subagent_policy_failure
                and terminal_workflow_failure is not None):
            # Deterministic combined-outcome precedence: a fully-accounted
            # forbidden spawn is the primary registered ablation failure;
            # retain the observed timeout/abort as secondary evidence.  This
            # keeps the no-subagent gate internally consistent without
            # erasing the backend termination that also happened.
            record["secondary_failure_kind"] = (
                terminal_workflow_failure.failure_kind)
            record["secondary_failure"] = str(terminal_workflow_failure)
        if subagent_policy_failure and not v2:
            # Pre-registered third-arm policy: the fleet-ablation arm may
            # not delegate at all, or its differences stop being
            # attributable to fleet removal. Counted, never replaced.
            raise WorkflowFailure(
                f"arm `{arm_name}` spawned "
                f"{record['accounting']['subagents_spawned']} subagent(s) — "
                f"forbidden by the pre-registered no-subagent policy",
                failure_kind="subagent_policy",
            )
        if (record["accounting"]["subagent_launches"]
                > record["accounting"]["subagent_children"]):
            # Every node in the agent tree owes model/effort evidence. A
            # Task launch whose child emitted nothing leaves a subagent
            # with NO model-bearing nodes: the tree cannot be validated
            # for runtime parity, so the run is invalid — never accepted
            # as completed on main-context evidence alone.
            message = (
                f"subagent launch evidence exceeds model-bearing child "
                f"identities (launches="
                f"{record['accounting']['subagent_launches']}, children="
                f"{record['accounting']['subagent_children']}) — a spawned "
                f"subagent's effective model cannot be validated; run "
                f"invalidated")
            if v2 and subagent_policy_failure:
                raise BlockingInfraFailure(
                    f"{message}; the forbidden launch is an observed "
                    f"ablation-policy event but its runtime tree is "
                    f"incomplete, so it cannot be counted or rerun",
                    failure_kind="subagent_policy",
                )
            if terminal_workflow_failure is not None:
                raise BlockingInfraFailure(
                    f"{message}; the observed timeout/abort cannot be "
                    f"counted or rerun",
                    failure_kind=terminal_workflow_failure.failure_kind,
                )
            raise InfraFailure(message)
        if artifact is None:
            if v2 and subagent_policy_failure:
                raise WorkflowFailure(
                    f"arm `{arm_name}` spawned "
                    f"{record['accounting']['subagents_spawned']} "
                    f"subagent(s) — forbidden by the pre-registered "
                    f"no-subagent policy",
                    failure_kind="subagent_policy",
                )
            if terminal_workflow_failure is not None:
                raise terminal_workflow_failure
            raise WorkflowFailure(
                f"no fresh research artifact after {MAX_CONTINUATIONS} continuations",
                failure_kind="missing_document",
            )
        try:
            raw_bytes = read_input_bytes(artifact, "produced artifact")
        except InfraFailure as exc:
            if terminal_workflow_failure is not None:
                raise BlockingInfraFailure(
                    "produced artifact became unreadable after a counted "
                    "timeout/abort; the workflow outcome cannot be rerun "
                    "and its artifact gate is indeterminate",
                    failure_kind=terminal_workflow_failure.failure_kind,
                ) from exc
            raise InfraFailure(
                f"cannot read produced artifact for validation: {exc}"
            ) from exc
        # Preserve byte-exact raw evidence even when the document is not
        # UTF-8.  The diagnostic judge copy uses deterministic replacement
        # characters; the validator's UTF-8 defect keeps it gate-failed.
        verify_output_directory(out, output_binding, "run output directory")
        atomic_write_bytes(out / f"run-{run_id}-raw.md", raw_bytes)
        if v2:
            record["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        raw = raw_bytes.decode("utf-8", "replace")
        # The artifact contract is enforced by the harness itself, not by
        # trusting the session to have followed its instructions: a fresh
        # document that violates the contract is a COUNTED workflow
        # failure — the workflow produced the wrong artifact — never a
        # completed, scoreable replicate. The raw copy above is preserved
        # as evidence.
        try:
            # Validate the exact captured bytes, not the live workflow path:
            # a model process (or local adversary) must not swap the artifact
            # between raw hashing and the contract parser's later open.
            with tempfile.TemporaryDirectory(
                    prefix="rpa-artifact-validate-") as validate_root:
                captured_artifact = Path(validate_root) / artifact.name
                captured_artifact.write_bytes(raw_bytes)
                contract_defects = artifact_validator.validate(
                    captured_artifact,
                    expected_git_commit=_git(
                        worktree, "rev-parse", "HEAD"),
                    expected_repository=task_target_repo(
                        task_text, task_path),
                    enforce_filename=True,
                )
        except BaseException as exc:
            if terminal_workflow_failure is not None:
                raise BlockingInfraFailure(
                    "artifact validator crashed after a counted timeout/"
                    "abort; the workflow outcome cannot be rerun and its "
                    "artifact gate is indeterminate",
                    failure_kind=terminal_workflow_failure.failure_kind,
                ) from exc
            raise InfraFailure("artifact validator crashed") from exc
        if (not isinstance(contract_defects, list)
                or any(not isinstance(defect, str) or not defect
                       for defect in contract_defects)):
            if terminal_workflow_failure is not None:
                raise BlockingInfraFailure(
                    "artifact validator returned indeterminate output after "
                    "a counted timeout/abort; the workflow outcome cannot "
                    "be rerun",
                    failure_kind=terminal_workflow_failure.failure_kind,
                )
            raise InfraFailure(
                "artifact validator returned indeterminate output")
        if contract_defects:
            record["artifact_defects"] = contract_defects
            if v2:
                record["artifact_gate"] = "failed"
            # Registered amendment (owner decision, 2026-07-28, recorded
            # before unsealing): the gate rejection stays a counted
            # workflow failure for the primary end-to-end outcome — no
            # repair, no re-run — but the document's CONTENT is still
            # blind-scored on a separate diagnostic axis, so the
            # anonymized diagnostic copy and its digest are preserved
            # alongside the raw evidence.
            diag_text = anonymize(raw, run_id)
            atomic_write_text(out / f"run-{run_id}-diag.md", diag_text)
            record["diagnostic_sha256"] = hashlib.sha256(
                diag_text.encode("utf-8")
            ).hexdigest()
            shown = "; ".join(contract_defects[:5])
            more = " …" if len(contract_defects) > 5 else ""
            if v2 and subagent_policy_failure:
                raise WorkflowFailure(
                    f"arm `{arm_name}` spawned "
                    f"{record['accounting']['subagents_spawned']} "
                    f"subagent(s) — forbidden by the pre-registered "
                    f"no-subagent policy; produced artifact also failed "
                    f"the artifact contract",
                    failure_kind="subagent_policy",
                )
            if terminal_workflow_failure is not None:
                raise terminal_workflow_failure
            raise WorkflowFailure(
                f"artifact violates the research artifact contract: "
                f"{shown}{more}",
                failure_kind="artifact_contract",
            )
        if v2:
            record["artifact_gate"] = "passed"
        anon_text = anonymize(raw, run_id)
        atomic_write_text(out / f"run-{run_id}-anon.md", anon_text)
        # The digest recorded here is what scoring later verifies: a scored
        # document must be the exact artifact this run produced.
        record["artifact_sha256"] = hashlib.sha256(
            anon_text.encode("utf-8")
        ).hexdigest()
        if v2 and subagent_policy_failure:
            raise WorkflowFailure(
                f"arm `{arm_name}` spawned "
                f"{record['accounting']['subagents_spawned']} subagent(s) — "
                f"forbidden by the pre-registered no-subagent policy",
                failure_kind="subagent_policy",
            )
        if terminal_workflow_failure is not None:
            raise terminal_workflow_failure
        record["status"] = "completed"
    except WorkflowFailure as exc:
        record["status"] = "workflow_failure"
        record["failure"] = str(exc)
        if v2:
            record["failure_kind"] = exc.failure_kind
    except BlockingInfraFailure as exc:
        record["status"] = "infra_failure"
        record["blocking"] = True
        record["failure"] = str(exc)
        if v2:
            record["failure_kind"] = exc.failure_kind
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
            record["wall_seconds"] = round(time.monotonic() - started, 3)
        if v2:
            final_workflow_outcome = record.get("status") in (
                "completed", "workflow_failure")
            complete_telemetry = (
                isinstance(record.get("accounting"), dict)
                and isinstance(record.get("wall_seconds"), (int, float))
                and not isinstance(record.get("wall_seconds"), bool)
            )
            record["telemetry_eligible"] = bool(
                final_workflow_outcome and complete_telemetry)
            if record["telemetry_eligible"]:
                record["telemetry_exclusion_reason"] = None
            elif not final_workflow_outcome:
                record["telemetry_exclusion_reason"] = (
                    "not_a_final_workflow_outcome")
            else:
                record["telemetry_exclusion_reason"] = (
                    "missing_accounting_or_wall_seconds")
        if worktree is not None:
            remove_worktree(repo_dir, worktree)
    verify_output_directory(out, output_binding, "run output directory")
    atomic_write_text(out / f"run-{run_id}.json",
                      json.dumps(record, indent=2) + "\n")
    return record


def run_task_with_retries(config, arm_name, task_path, repo_dir, output_dir,
                          scheduled=False, starting_attempt=1,
                          schedule_binding=None, output_binding=None,
                          task_snapshot=None, heartbeat_completed=None,
                          heartbeat_total=None):
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
    if (isinstance(starting_attempt, bool)
            or not isinstance(starting_attempt, int)
            or not 1 <= starting_attempt <= max_retries + 1):
        raise InfraFailure(
            f"invalid starting infrastructure attempt "
            f"{starting_attempt!r}; registered range is "
            f"1..{max_retries + 1}"
        )
    attempts = []
    for attempt in range(starting_attempt, max_retries + 2):
        record = run_task(config, arm_name, task_path, repo_dir, output_dir,
                          attempt=attempt, scheduled=scheduled,
                          schedule_binding=schedule_binding,
                          output_binding=output_binding,
                          task_snapshot=task_snapshot,
                          heartbeat_completed=heartbeat_completed,
                          heartbeat_total=heartbeat_total)
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
    require_standard_v2_registration(config)
    if (config.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION
            and seed != PILOT_V2_SCHEDULE_SEED):
        raise InfraFailure(
            f"protocol v2 requires the registered schedule seed "
            f"{PILOT_V2_SCHEDULE_SEED}")
    if (isinstance(replicates, bool) or not isinstance(replicates, int)
            or replicates < 1):
        raise InfraFailure(
            f"`replicates` must be a positive integer, got {replicates!r} — "
            f"zero entries would let an empty schedule complete"
        )
    tasks = [str(Path(t)) for t in task_paths]
    if len(set(tasks)) != len(tasks):
        raise InfraFailure("duplicate task paths in the schedule task list")
    tasks_by_basename = {}
    for task in tasks:
        basename = Path(task).name
        if basename in tasks_by_basename:
            raise InfraFailure(
                "schedule task basenames must be unique so portable arm "
                "scope registrations cannot resolve ambiguously")
        tasks_by_basename[basename] = task
    # Protocol-v2 randomization starts from one registered base order.  CLI
    # callers may supply the exact sealed set in any order, but that order
    # must never become an unregistered second randomization input: the same
    # registered seed would otherwise produce several self-consistent run
    # schedules.  Canonicalize before hashing, coverage checks, arm expansion,
    # and shuffling so every entry point reconstructs the identical schedule.
    if (config.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION
            and not allow_nonstandard
            and not config.get("nonstandard_config")):
        registered_names = list(seal_package.HOLDOUT_TASKS)
        if set(tasks_by_basename) != set(registered_names):
            raise InfraFailure(
                "a standard protocol-v2 schedule requires the exact sealed "
                f"holdout task names {registered_names!r}"
            )
        tasks = [tasks_by_basename[name] for name in registered_names]
    # The schedule binds task CONTENTS, not just paths: an edited prompt or
    # re-pinned target-sha after registration must break reconstruction,
    # never silently mix revisions inside one experimental cell.
    task_bytes_by_path = {task: read_task_bytes(task) for task in tasks}
    task_text_by_path = {
        task: decode_task_bytes(task_bytes_by_path[task], task)
        for task in tasks
    }
    task_digests = {
        task: hashlib.sha256(task_bytes_by_path[task]).hexdigest()
        for task in tasks
    }
    standard_topology = _standard_topology(config)
    if not allow_nonstandard:
        if config.get("protocol_version", 1) == PILOT_V2_PROTOCOL_VERSION:
            retries = config.get("max_infra_retries")
            if (isinstance(retries, bool)
                    or retries != DEFAULT_MAX_INFRA_RETRIES):
                raise InfraFailure(
                    "a standard protocol-v2 schedule requires "
                    f"`max_infra_retries` exactly "
                    f"{DEFAULT_MAX_INFRA_RETRIES}"
                )
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
            cov_text = task_text_by_path[task]
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
            frontmatter = re.match(
                r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)",
                cov_text, re.DOTALL)
            external_flag = bool(
                frontmatter and re.search(
                    r"^external-snapshots:\s*true\s*$",
                    frontmatter.group(1), re.MULTILINE))
            if (config.get("protocol_version", 1)
                    == PILOT_V2_PROTOCOL_VERSION
                    and number == 5 and not external_flag):
                raise InfraFailure(
                    f"{task}: registered archetype 5 must declare "
                    f"`external-snapshots: true` so its sealed snapshot "
                    f"and source-drift gates cannot be bypassed"
                )
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
        validate_sealed_judge_config(
            config, seal_doc_sched, seal_path, sealed_files)
        if config.get("protocol_version", 1) == PILOT_V2_PROTOCOL_VERSION:
            ablation_arms = [
                arm for arm in config["arms"].values()
                if arm.get("forbid_subagents")
            ]
            expected_ablation = [
                Path(task).name
                for task in ablation_arms[0].get("schedule_tasks", [])
            ] if len(ablation_arms) == 1 else []
            if seal_doc_sched.get("ablation_tasks") != expected_ablation:
                raise InfraFailure(
                    "protocol v2 seal `ablation_tasks` must exactly match "
                    "the configured ablation schedule-task basenames"
                )
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
            scoped_names = [Path(value).name
                            for value in arm["schedule_tasks"]]
            if (len(scoped_names) != 2
                    or len(set(scoped_names)) != 2):
                raise InfraFailure(
                    f"arm `{arm_name}` (no-subagent ablation) must be scoped "
                    f"to exactly 2 DISTINCT designated tasks, got "
                    f"{arm['schedule_tasks']!r}"
                )
            unknown_scoped = [name for name in scoped_names
                              if name not in tasks_by_basename]
            if unknown_scoped:
                raise InfraFailure(
                    f"arm `{arm_name}` schedule_tasks names are not in the "
                    f"registered task list: {unknown_scoped}")
            scoped_paths = [tasks_by_basename[name] for name in scoped_names]
            if not allow_nonstandard:
                # The designation is not free: the plan fixes the third arm
                # to specific archetypes, validated from the tasks' own
                # `archetype` frontmatter.
                found = []
                for scoped in scoped_paths:
                    scoped_text = task_text_by_path[scoped]
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
        arm_tasks = (scoped_paths if arm.get("forbid_subagents") else tasks)
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
    schedule = {
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
    if config.get("protocol_version", 1) == PILOT_V2_PROTOCOL_VERSION:
        schedule["protocol_version"] = PILOT_V2_PROTOCOL_VERSION
        schedule["environment_policy_id"] = PILOT_V2_ENVIRONMENT_POLICY_ID
        schedule["runtime_pins"] = protocol_v2_runtime_pins(config)
    return schedule


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
    if (not isinstance(results, list) or not isinstance(entries, list)
            or not all(isinstance(item, dict) for item in results)
            or not all(isinstance(item, dict) for item in entries)):
        raise InfraFailure(
            "schedule entries and manifest results must be arrays of objects")
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
        if (run_record.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION
                or done.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION):
            for field in (
                    "protocol_version", "environment_policy_id",
                    "runtime_pins",
                    "failure_kind", "artifact_gate",
                    "raw_sha256",
                    "telemetry_policy_id", "telemetry_eligible",
                    "telemetry_exclusion_reason"):
                if run_record.get(field) != done.get(field):
                    raise InfraFailure(
                        f"manifest result {done.get('index')} `{field}` "
                        f"does not match its immutable run record — edited "
                        f"manifest refused"
                    )
            if (run_record.get("schedule_index") != entry.get("index")
                    or run_record.get("schedule_digest")
                    != done.get("schedule_digest")):
                raise InfraFailure(
                    f"manifest result {done.get('index')} does not match "
                    f"the run record's immutable schedule binding"
                )


def validate_v2_final_record_semantics(config, entry, final_record,
                                       task_text):
    """Validate every invariant that makes one terminal v2 observation
    countable.  Run-schedule resume, scorer prelaunch, step-5 handoff, and
    aggregation all call this before another nondeterministic backend can be
    authorized."""
    arm = config.get("arms", {}).get(entry.get("arm"))
    if not isinstance(arm, dict):
        raise InfraFailure("final run refers to an unknown arm")
    status = final_record.get("status")
    failure_kind = final_record.get("failure_kind")
    gate = final_record.get("artifact_gate")
    defects = final_record.get("artifact_defects")
    if status not in {"completed", "workflow_failure"}:
        raise InfraFailure("final run is not a countable terminal outcome")
    if (final_record.get("environment_policy_id")
            != PILOT_V2_ENVIRONMENT_POLICY_ID
            or final_record.get("runtime_pins")
            != protocol_v2_runtime_pins(config)):
        raise InfraFailure(
            "final run does not bind the registered operator runtime")
    if (status == "completed"
            and (failure_kind is not None or gate != "passed")):
        raise InfraFailure(
            "completed run has an invalid failure/artifact-gate state")
    if (status == "workflow_failure"
            and failure_kind not in PILOT_V2_FAILURE_KINDS):
        raise InfraFailure("workflow failure has an unregistered failure kind")
    if failure_kind == "artifact_contract" and gate != "failed":
        raise InfraFailure(
            "artifact-contract failure must have a failed artifact gate")
    if failure_kind == "missing_document" and (
            gate != "not_evaluated"
            or final_record.get("raw_sha256") is not None
            or final_record.get("artifact_sha256") is not None
            or final_record.get("diagnostic_sha256") is not None):
        raise InfraFailure(
            "missing-document failure cannot carry produced document material")
    if gate == "passed" and (
            not isinstance(final_record.get("artifact_sha256"), str)
            or final_record.get("diagnostic_sha256") is not None
            or defects not in (None, [])):
        raise InfraFailure("passed artifact gate has invalid digests")
    if gate == "failed" and (
            not isinstance(final_record.get("diagnostic_sha256"), str)
            or final_record.get("artifact_sha256") is not None
            or not isinstance(defects, list) or not defects
            or not all(isinstance(item, str) and item for item in defects)):
        raise InfraFailure("failed artifact gate has invalid digests")
    if gate == "not_evaluated" and (
            final_record.get("raw_sha256") is not None
            or final_record.get("artifact_sha256") is not None
            or final_record.get("diagnostic_sha256") is not None):
        raise InfraFailure("not-evaluated artifact gate carries document material")
    if gate not in {"passed", "failed", "not_evaluated"}:
        raise InfraFailure("final run has an invalid artifact-gate value")
    validate_intervention_log(final_record)
    nodes = final_record.get("nodes")
    accounting = final_record.get("accounting")
    if (not isinstance(nodes, list) or not nodes
            or not isinstance(accounting, dict)):
        raise InfraFailure("final run lacks complete model-bearing accounting")
    try:
        recomputed = account(nodes)
        validate_models(nodes, arm.get("model"))
        effort_capture = validate_efforts(
            nodes, arm.get("effort", "default"))
    except (InfraFailure, KeyError, TypeError, ValueError) as exc:
        raise InfraFailure(
            "final run runtime/accounting evidence is invalid") from exc
    if (recomputed != accounting
            or final_record.get("effort_capture") != effort_capture
            or final_record.get("registered_model") != arm.get("model")
            or final_record.get("effort") != arm.get("effort", "default")
            or final_record.get("installation_sha256") != arm.get("sha256")
            or final_record.get("backend_version")
            != config.get("backend_version")
            or final_record.get("entrypoint") != arm.get("entrypoint")
            or final_record.get("standard_topology")
            is not validate_arm_topology(config)
            or final_record.get("target_sha") != task_target_sha(
                task_text, entry["task"])
            or final_record.get("telemetry_policy_id")
            != PILOT_V2_AGGREGATION_POLICY["telemetry"]
            or not isinstance(final_record.get("wall_seconds"), (int, float))
            or isinstance(final_record.get("wall_seconds"), bool)
            or final_record.get("wall_seconds") < 0
            or final_record.get("telemetry_eligible") is not True
            or final_record.get("telemetry_exclusion_reason") is not None):
        raise InfraFailure(
            "final run runtime, telemetry, or accounting bindings differ "
            "from the registered configuration")
    launches = recomputed.get("subagent_launches")
    children = recomputed.get("subagent_children")
    spawned = recomputed.get("subagents_spawned")
    if (not all(isinstance(value, int) and not isinstance(value, bool)
                and value >= 0 for value in (launches, children, spawned))
            or launches > children):
        raise InfraFailure(
            "final run subagent accounting is incomplete or invalid")
    forbidden = arm.get("forbid_subagents") is True
    if failure_kind == "subagent_policy" and (
            not forbidden or spawned <= 0):
        raise InfraFailure("subagent-policy failure lacks a forbidden spawn")
    if forbidden and spawned > 0 and (
            status != "workflow_failure" or failure_kind != "subagent_policy"):
        raise InfraFailure(
            "forbidden subagent spawn was not classified as a counted "
            "subagent-policy failure")


def validate_v2_record_artifacts(root, record):
    """Require every digest-bound run artifact and forbid alternates.

    This applies to terminal records and retained infrastructure attempts:
    a validator crash can legitimately leave raw evidence, but a missing or
    changed bound file can never be ignored before a retry/next slot.
    """
    root = Path(root)
    run_id = record.get("run_id")
    if (not isinstance(run_id, str)
            or re.fullmatch(r"[0-9a-f]{12}", run_id) is None):
        raise InfraFailure("run artifact audit has an invalid run id")
    paths = {
        "raw": root / f"run-{run_id}-raw.md",
        "anon": root / f"run-{run_id}-anon.md",
        "diag": root / f"run-{run_id}-diag.md",
    }

    def require_digest(kind, field):
        expected = record.get(field)
        if (not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                or not _safe_single_link_regular_file(paths[kind])):
            raise InfraFailure(
                f"run {run_id} lacks its bound {kind} artifact")
        actual = hashlib.sha256(read_input_bytes(
            paths[kind], f"{kind} run artifact")).hexdigest()
        if actual != expected:
            raise InfraFailure(f"{kind} run artifact digest mismatch")

    raw_digest = record.get("raw_sha256")
    artifact_digest = record.get("artifact_sha256")
    diagnostic_digest = record.get("diagnostic_sha256")
    if raw_digest is None:
        if _path_present(paths["raw"]):
            raise InfraFailure("run carries unbound raw artifact material")
    else:
        require_digest("raw", "raw_sha256")
    gate = record.get("artifact_gate")
    if gate == "passed":
        if raw_digest is None or diagnostic_digest is not None:
            raise InfraFailure(
                "gate-passed run has inconsistent artifact bindings")
        require_digest("anon", "artifact_sha256")
        if _path_present(paths["diag"]):
            raise InfraFailure("gate-passed run carries diagnostic material")
    elif gate == "failed":
        if raw_digest is None or artifact_digest is not None:
            raise InfraFailure(
                "gate-failed run has inconsistent artifact bindings")
        require_digest("diag", "diagnostic_sha256")
        if _path_present(paths["anon"]):
            raise InfraFailure("gate-failed run carries passing material")
    elif gate == "not_evaluated":
        if artifact_digest is not None or diagnostic_digest is not None:
            raise InfraFailure(
                "not-evaluated run carries scored artifact bindings")
        if _path_present(paths["anon"]) or _path_present(paths["diag"]):
            raise InfraFailure("no-document run carries scored material")
    else:
        raise InfraFailure("run artifact audit has an invalid gate value")


def audit_completed_v2_run_material(config, manifest_path, schedule,
                                    results, entries):
    """Strictly reconcile the complete protocol-v2 run namespace.

    Scoring must not launch a judge merely because expected final records
    still match a manifest while foreign runs, superseded observations,
    orphan artifacts, claims, or terminal-invalid markers also exist.  This
    read-only audit is shared with final aggregation.
    """
    root = Path(manifest_path).resolve().parent
    if schedule.get("protocol_version") != PILOT_V2_PROTOCOL_VERSION:
        raise InfraFailure(
            "completed protocol-v2 run audit requires a v2 schedule")
    if sorted(root.glob("schedule-entry-*"), key=lambda path: path.name):
        raise InfraFailure(
            "completed run directory retains claim, terminal-invalid, or "
            "foreign schedule-entry material")
    run_lock = root / ".run-schedule.lock"
    if not _safe_single_link_regular_file(run_lock):
        raise InfraFailure(
            "completed v2 run directory lacks its persistent ordinary "
            "run-schedule lock")

    expected_schedule_digest = schedule_digest(schedule)
    expected_config_digest = config_digest(config)
    task_digests = schedule.get("task_digests")
    if not isinstance(task_digests, dict):
        raise InfraFailure("schedule task digests must be an object")
    task_texts = {}
    for task, expected_digest in task_digests.items():
        task_bytes = read_task_bytes(task)
        if hashlib.sha256(task_bytes).hexdigest() != expected_digest:
            raise InfraFailure(
                f"{task}: completed-run task bytes differ from the schedule")
        task_texts[task] = decode_task_bytes(task_bytes, task)
    max_retries = config.get("max_infra_retries", DEFAULT_MAX_INFRA_RETRIES)
    if (not isinstance(max_retries, int) or isinstance(max_retries, bool)
            or max_retries < 0):
        raise InfraFailure("runtime infrastructure retry bound is invalid")
    max_attempt = max_retries + 1

    entries_by_index = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise InfraFailure("schedule entries must contain objects")
        index = entry.get("index")
        if (not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or index in entries_by_index):
            raise InfraFailure(
                "schedule entries have invalid or duplicate indices")
        entries_by_index[index] = entry

    material_by_run = {}
    grouped = {index: [] for index in entries_by_index}
    for record_path in sorted(root.glob("run-*.json"),
                              key=lambda path: path.name):
        match = re.fullmatch(r"run-([0-9a-f]{12})\.json", record_path.name)
        if match is None or not _safe_regular_file(record_path):
            raise InfraFailure(
                "run directory contains a malformed or foreign run record")
        record_bytes = read_input_bytes(record_path, "run material record")
        record = _json_without_duplicate_keys(
            record_bytes, f"run material record {record_path}")
        if not isinstance(record, dict):
            raise InfraFailure("run material record must be a JSON object")
        run_id = record.get("run_id")
        if run_id != match.group(1) or run_id in material_by_run:
            raise InfraFailure(
                "run material record identity differs from its filename")
        index = record.get("schedule_index")
        if (record.get("protocol_version") != PILOT_V2_PROTOCOL_VERSION
                or record.get("environment_policy_id")
                != PILOT_V2_ENVIRONMENT_POLICY_ID
                or record.get("runtime_pins")
                != protocol_v2_runtime_pins(config)
                or record.get("schedule_digest")
                != expected_schedule_digest
                or record.get("config_digest") != expected_config_digest
                or not isinstance(index, int) or isinstance(index, bool)
                or index not in entries_by_index):
            raise InfraFailure(
                "run directory contains material outside the registered "
                "protocol, configuration, schedule, or slot namespace")
        entry = entries_by_index[index]
        if (record.get("arm") != entry.get("arm")
                or record.get("task") != entry.get("task")
                or record.get("task_sha256")
                != task_digests.get(entry.get("task"))):
            raise InfraFailure("run record immutable slot binding mismatch")
        attempt = record.get("attempt")
        if (not isinstance(attempt, int) or isinstance(attempt, bool)
                or not 1 <= attempt <= max_attempt):
            raise InfraFailure("run material has an invalid attempt number")
        status = record.get("status")
        if status not in {"completed", "workflow_failure", "infra_failure"}:
            raise InfraFailure(
                "run directory contains ambiguous or nonterminal material")
        if status == "infra_failure" and record.get("blocking") is True:
            raise InfraFailure(
                "blocking infrastructure material invalidates the round")
        material_by_run[run_id] = (record_bytes, record)
        grouped[index].append((attempt, run_id, record_bytes, record))

    if len(results) != len(entries):
        raise InfraFailure(
            "schedule manifest is not a complete final population")
    record_hashes = []
    for summary, entry in zip(results, entries):
        if not isinstance(summary, dict):
            raise InfraFailure(
                "schedule manifest results must contain objects")
        index = entry["index"]
        final_run_id = summary.get("run_id")
        final_attempt = summary.get("attempts")
        if (summary.get("index") != index
                or not isinstance(final_run_id, str)
                or re.fullmatch(r"[0-9a-f]{12}", final_run_id) is None
                or not isinstance(final_attempt, int)
                or isinstance(final_attempt, bool)
                or not 1 <= final_attempt <= max_attempt):
            raise InfraFailure(
                "schedule result has an invalid slot, run, or attempt id")
        attempts = {}
        for attempt, run_id, record_bytes, record in grouped[index]:
            if attempt in attempts:
                raise InfraFailure(
                    "run slot contains duplicate attempt records")
            attempts[attempt] = run_id
            if attempt < final_attempt:
                if record.get("status") != "infra_failure":
                    raise InfraFailure(
                        "run slot contains an extra terminal observation")
            elif attempt == final_attempt:
                if (run_id != final_run_id or record.get("status")
                        not in {"completed", "workflow_failure"}):
                    raise InfraFailure(
                        "run slot final material differs from its manifest")
            else:
                raise InfraFailure(
                    "run slot contains material after its final attempt")
            record_hashes.append({
                "schedule_index": index, "attempt": attempt,
                "kind": "record", "file": f"run-{run_id}.json",
                "sha256": hashlib.sha256(record_bytes).hexdigest(),
            })
        if set(attempts) != set(range(1, final_attempt + 1)):
            raise InfraFailure(
                "run slot infrastructure attempt history is not contiguous")
        if final_run_id not in material_by_run:
            raise InfraFailure(
                "schedule result has no canonical final run record")
        final_record = material_by_run[final_run_id][1]
        validate_v2_final_record_semantics(
            config, entry, final_record, task_texts[entry["task"]])

    allowed_artifacts = {}
    for run_id, (_record_bytes, record) in material_by_run.items():
        status = record.get("status")
        gate = record.get("artifact_gate")
        raw_path = root / f"run-{run_id}-raw.md"
        anon_path = root / f"run-{run_id}-anon.md"
        diag_path = root / f"run-{run_id}-diag.md"
        if gate in {"passed", "failed"}:
            if not _safe_regular_file(raw_path):
                raise InfraFailure(
                    "document-producing run has no byte-exact raw artifact")
            allowed_artifacts[raw_path.name] = raw_path
        elif _path_present(raw_path):
            if status != "infra_failure" or not _safe_regular_file(raw_path):
                raise InfraFailure(
                    "no-document run carries unexpected raw artifact")
            allowed_artifacts[raw_path.name] = raw_path
        if _path_present(raw_path):
            raw_bytes = read_input_bytes(raw_path, "raw run artifact")
            if hashlib.sha256(raw_bytes).hexdigest() != record.get(
                    "raw_sha256"):
                raise InfraFailure("raw run artifact digest mismatch")
        elif record.get("raw_sha256") is not None:
            raise InfraFailure(
                "run record binds raw artifact bytes that are absent")
        if gate == "passed":
            if not _safe_regular_file(anon_path):
                raise InfraFailure(
                    "gate-passed run has no anonymized artifact")
            anon_bytes = read_input_bytes(anon_path, "anonymized run artifact")
            if hashlib.sha256(anon_bytes).hexdigest() != record.get(
                    "artifact_sha256"):
                raise InfraFailure("anonymized run artifact digest mismatch")
            allowed_artifacts[anon_path.name] = anon_path
        if gate == "failed":
            if not _safe_regular_file(diag_path):
                raise InfraFailure(
                    "gate-failed run has no diagnostic artifact")
            diag_bytes = read_input_bytes(diag_path, "diagnostic run artifact")
            if hashlib.sha256(diag_bytes).hexdigest() != record.get(
                    "diagnostic_sha256"):
                raise InfraFailure("diagnostic run artifact digest mismatch")
            allowed_artifacts[diag_path.name] = diag_path

    discovered_artifacts = {
        path.name: path for path in root.glob("run-*")
        if path.suffix != ".json"
    }
    if set(discovered_artifacts) != set(allowed_artifacts):
        raise InfraFailure(
            "run directory contains missing, foreign, or orphan artifact "
            "material")
    for name, path in sorted(allowed_artifacts.items()):
        if not _safe_regular_file(path):
            raise InfraFailure("run artifact material must be a regular file")
        record_hashes.append({
            "kind": "artifact", "file": name,
            "sha256": hashlib.sha256(read_input_bytes(
                path, "run artifact material")).hexdigest(),
        })
    record_hashes.sort(key=lambda item: (
        item.get("schedule_index", -1), item.get("attempt", -1),
        item["kind"], item["file"]))
    return material_by_run, record_hashes


def run_schedule(config, schedule_path, repos, output_dir, task_paths):
    """Serialize one schedule output from state scan through final manifest.

    Per-entry claim files remain durable audit evidence, but they are not the
    concurrency primitive: PID claims have stale-claim ABA races and a late
    winner can otherwise cross the scan-to-launch boundary.  One kernel lock
    covers the complete output state machine and is released automatically on
    process death.
    """
    require_standard_v2_registration(config)
    out, output_binding = bind_output_directory(output_dir)
    lock_path = out / ".run-schedule.lock"
    refuse_missing_persistent_lock_with_state(
        out, lock_path,
        ("schedule-manifest.json", "run-*", "schedule-entry-*"),
        "run-schedule output",
    )
    lock = acquire_advisory_lock(lock_path, "run-schedule output")
    try:
        return _run_schedule_locked(
            config, schedule_path, repos, out, task_paths,
            output_binding=output_binding)
    finally:
        release_advisory_lock(lock)


def _run_schedule_locked(config, schedule_path, repos, output_dir, task_paths,
                         output_binding=None):
    """Execute a pre-registered schedule in its recorded order. The expected
    schedule is RECONSTRUCTED from the registered config, the operator-
    supplied task set, and the recorded seed/replicates — the schedule
    file's own arms/tasks/entries are never trusted, so an edited file
    (dropped arm or task, truncated entries, reordering) is refused before
    any run. Progress is persisted to the manifest after every entry, and
    an interrupted schedule resumes at the first unfinished entry — never
    from index 0, so no extra runs are created after outcomes were
    observed."""
    if output_binding is None:
        output_dir, output_binding = bind_output_directory(output_dir)
    else:
        output_dir = verify_output_directory(
            Path(output_dir), output_binding, "run-schedule output")
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
    # Re-open each task exactly once at the execution boundary, prove those
    # bytes against the registered schedule digest, then retain the snapshot
    # for repository routing, target pinning, and the model prompt.  No later
    # pathname read may select different task bytes.
    task_snapshots = {}
    task_texts = {}
    for task in schedule["tasks"]:
        task_bytes = read_task_bytes(task)
        if hashlib.sha256(task_bytes).hexdigest() != schedule[
                "task_digests"].get(task):
            raise InfraFailure(
                f"{task}: task changed after schedule reconstruction")
        task_snapshots[task] = task_bytes
        task_texts[task] = decode_task_bytes(task_bytes, task)
    entries = schedule["entries"]
    sched_digest = schedule_digest(schedule)
    out = Path(output_dir)
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
        if (schedule.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION
                and (prior.get("protocol_version")
                     != PILOT_V2_PROTOCOL_VERSION
                     or prior.get("environment_policy_id")
                     != PILOT_V2_ENVIRONMENT_POLICY_ID
                     or prior.get("runtime_pins")
                     != schedule.get("runtime_pins")
                     or prior.get("config_digest")
                     != schedule.get("config_digest"))):
            raise InfraFailure(
                "existing manifest has a protocol-v2 runtime binding "
                "mismatch")
        results = list(prior.get("results", []))

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
        if schedule.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION:
            manifest["protocol_version"] = PILOT_V2_PROTOCOL_VERSION
            manifest["environment_policy_id"] = (
                PILOT_V2_ENVIRONMENT_POLICY_ID)
            manifest["runtime_pins"] = schedule["runtime_pins"]
        atomic_write_text(manifest_path,
                          json.dumps(manifest, indent=2) + "\n")
        return manifest

    protocol_v2 = (
        schedule.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION)

    def terminal_path_for(entry):
        return out / (
            f"schedule-entry-{entry['index']}-terminal-invalid.json")

    def claim_path_for(entry):
        return out / f"schedule-entry-{entry['index']}.claim"

    def terminal_core_for(entry):
        return {
            "status": "terminal_invalid",
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "runtime_pins": schedule["runtime_pins"],
            "schedule_digest": sched_digest,
            "config_digest": schedule["config_digest"],
            "schedule_index": entry["index"],
            "arm": entry["arm"],
            "task": entry["task"],
            "task_sha256": schedule["task_digests"][entry["task"]],
        }

    def refuse_terminal_invalid(entry):
        terminal_path = terminal_path_for(entry)
        terminal = load_json_object(
            terminal_path, "terminal-invalid schedule record")
        allowed_kinds = {
            "ambiguous_post_launch",
            "blocking_infrastructure_failure",
            "duplicate_terminal_outcomes",
            "foreign_schedule_material",
            "infrastructure_retries_exhausted",
            "invalid_attempt_history",
            "orphan_artifact_material",
            "out_of_order_future_material",
        }
        terminal_core = terminal_core_for(entry)
        if (any(terminal.get(key) != value
                for key, value in terminal_core.items())
                or terminal.get("kind") not in allowed_kinds
                or not isinstance(terminal.get("evidence"), list)):
            raise InfraFailure(
                f"terminal-invalid record for schedule entry "
                f"{entry['index']} is corrupted; the round remains "
                f"invalid and cannot be resumed"
            )
        raise InfraFailure(
            f"protocol v2 schedule entry {entry['index']} is "
            f"terminally invalid ({terminal['kind']}); this round "
            f"cannot be resumed — create a fresh seal and schedule"
        )

    def terminally_invalidate(entry, kind, record_paths):
        terminal_path = terminal_path_for(entry)
        if _path_present(terminal_path):
            refuse_terminal_invalid(entry)
        evidence = []
        seen_paths = set()
        for record_path in sorted(record_paths, key=lambda p: p.name):
            record_path = Path(record_path)
            if record_path in seen_paths:
                continue
            seen_paths.add(record_path)
            evidence.append(_evidence_descriptor(record_path))
        terminal = {**terminal_core_for(entry), "kind": kind,
                    "evidence": evidence}
        atomic_write_text(
            terminal_path, json.dumps(terminal, indent=2) + "\n")
        write_manifest(False)
        refuse_terminal_invalid(entry)

    def bound_run_records(entry):
        matched = []
        for record_path in sorted(out.glob("run-*.json")):
            if record_path.name.count("-") != 1:
                continue
            record = load_json_object(record_path, "run record")
            if (record.get("schedule_digest") == sched_digest
                    and record.get("schedule_index") == entry["index"]):
                matched.append((record_path, record))
        return matched

    def bound_run_state(entry):
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path, _record in bound_run_records(entry)
        }

    def audit_run_artifact_material():
        """Reject copied artifact residue without one immutable run record.

        A backend observation is not erased by deleting only its JSON record:
        raw/anonymized/diagnostic copies still prove that a run happened.  Any
        such orphan (or out-of-contract extra copy) terminally invalidates the
        round before another backend can launch.
        """
        bad_paths = []
        artifact_re = re.compile(
            r"^run-([0-9a-f]{12})-(raw|anon|diag|extra-[1-9][0-9]*)\.md$")
        record_re = re.compile(r"^run-([0-9a-f]{12})\.json$")
        entry_by_index = {entry["index"]: entry for entry in entries}

        # Scan the WHOLE schedule-entry namespace, not only the registered
        # filenames queried later.  An out-of-range/unknown claim or terminal
        # marker is launch evidence too and must block slot zero rather than
        # being ignored until final aggregation.
        schedule_material_re = re.compile(
            r"^schedule-entry-(\d+)(?:\.claim|-terminal-invalid\.json)$")
        foreign_schedule_paths = []
        for path in sorted(out.glob("schedule-entry-*"),
                           key=lambda item: item.name):
            match = schedule_material_re.fullmatch(path.name)
            if (match is None or int(match.group(1)) not in entry_by_index
                    or not _safe_regular_file(path)):
                foreign_schedule_paths.append(path)
        if foreign_schedule_paths:
            terminally_invalidate(
                entries[0], "foreign_schedule_material",
                foreign_schedule_paths)

        for path in sorted(out.glob("run-*"), key=lambda item: item.name):
            if not _safe_regular_file(path):
                bad_paths.append(path)
                continue
            if path.suffix == ".json":
                record_match = record_re.fullmatch(path.name)
                if record_match is None:
                    bad_paths.append(path)
                    continue
                try:
                    record = load_json_object(path, "schedule run material")
                except InfraFailure:
                    bad_paths.append(path)
                    continue
                index = record.get("schedule_index")
                entry = entry_by_index.get(index)
                if (record.get("run_id") != record_match.group(1)
                        or record.get("protocol_version")
                        != PILOT_V2_PROTOCOL_VERSION
                        or record.get("environment_policy_id")
                        != PILOT_V2_ENVIRONMENT_POLICY_ID
                        or record.get("runtime_pins")
                        != schedule.get("runtime_pins")
                        or record.get("schedule_digest") != sched_digest
                        or record.get("config_digest")
                        != schedule["config_digest"]
                        or entry is None
                        or record.get("arm") != entry["arm"]
                        or record.get("task") != entry["task"]
                        or record.get("task_sha256")
                        != schedule["task_digests"][entry["task"]]):
                    bad_paths.append(path)
                continue
            match = artifact_re.fullmatch(path.name)
            if match is None:
                bad_paths.append(path)
                continue
            run_id, kind = match.groups()
            record_path = out / f"run-{run_id}.json"
            if not record_path.exists() or kind.startswith("extra-"):
                bad_paths.append(path)
                continue
            try:
                record = load_json_object(record_path, "artifact run record")
            except InfraFailure:
                bad_paths.extend((record_path, path))
                continue
            if record.get("run_id") != run_id:
                bad_paths.extend((record_path, path))
                continue
            digest = hashlib.sha256(
                read_input_bytes(path, "schedule run artifact")).hexdigest()
            if kind == "raw" and record.get("raw_sha256") != digest:
                bad_paths.append(path)
            elif kind == "anon" and not (
                    record.get("artifact_gate") == "passed"
                    and record.get("artifact_sha256") == digest):
                bad_paths.append(path)
            elif kind == "diag" and not (
                    record.get("artifact_gate") == "failed"
                    and record.get("diagnostic_sha256") == digest):
                bad_paths.append(path)
        if bad_paths:
            terminally_invalidate(
                entries[0], "orphan_artifact_material", bad_paths)

        # Claim files are also pre-launch evidence.  A directory or dangling
        # symlink at a registered claim name must not vanish from `.exists()`
        # checks and later permit a fresh backend observation after deletion.
        for entry in entries:
            claim_path = claim_path_for(entry)
            if (_path_present(claim_path)
                    and not _safe_regular_file(claim_path)):
                terminally_invalidate(
                    entry, "invalid_attempt_history", [claim_path])

    # A complete manifest is not permission to ignore extra outcomes. A
    # concurrent legacy resume may have produced another terminal record for
    # the same slot after the manifest append. Audit every already-recorded
    # slot before returning, and persist invalidation so deleting the extra
    # record cannot make the round valid again.
    if protocol_v2:
        audit_run_artifact_material()
        for entry in entries:
            if _path_present(terminal_path_for(entry)):
                refuse_terminal_invalid(entry)
    verify_results_against_records(
        results, entries, out, require_all=False)
    if protocol_v2:
        for entry, summary in zip(entries, results):
            if _path_present(terminal_path_for(entry)):
                refuse_terminal_invalid(entry)
            matched = bound_run_records(entry)
            expected_path = out / f"run-{summary.get('run_id')}.json"
            expected_record = load_json_object(
                expected_path, "completed-prefix run record")
            final_attempt = summary.get("attempts")
            max_final_attempt = config.get(
                "max_infra_retries", DEFAULT_MAX_INFRA_RETRIES) + 1
            if (not isinstance(final_attempt, int)
                    or isinstance(final_attempt, bool)
                    or not 1 <= final_attempt <= max_final_attempt
                    or expected_record.get("attempt") != final_attempt):
                raise InfraFailure(
                    "completed-prefix final attempt differs from its "
                    "immutable run record")
            validate_v2_final_record_semantics(
                config, entry, expected_record, task_texts[entry["task"]])
            bad_paths = []
            prior_attempts = set()
            duplicate_terminal = False
            for record_path, record in matched:
                validate_v2_record_artifacts(out, record)
                if record_path == expected_path:
                    continue
                if (record.get("status") == "infra_failure"
                        and record.get("blocking") is not True
                        and isinstance(record.get("attempt"), int)
                        and not isinstance(record.get("attempt"), bool)
                        and isinstance(final_attempt, int)
                        and 1 <= record["attempt"] < final_attempt
                        and record["attempt"] not in prior_attempts
                        and record.get("arm") == entry["arm"]
                        and record.get("task") == entry["task"]
                        and record.get("task_sha256")
                        == schedule["task_digests"][entry["task"]]
                        and record.get("config_digest")
                        == schedule["config_digest"]
                        and record.get("protocol_version")
                        == PILOT_V2_PROTOCOL_VERSION
                        and record.get("environment_policy_id")
                        == PILOT_V2_ENVIRONMENT_POLICY_ID
                        and record.get("runtime_pins")
                        == schedule.get("runtime_pins")):
                    prior_attempts.add(record["attempt"])
                    continue
                bad_paths.append(record_path)
                if record.get("status") in (
                        "completed", "workflow_failure"):
                    duplicate_terminal = True
            if (not isinstance(final_attempt, int)
                    or isinstance(final_attempt, bool)
                    or prior_attempts != set(range(1, final_attempt))):
                bad_paths.extend(path for path, _record in matched
                                 if path != expected_path)
            claim_path = claim_path_for(entry)
            if claim_path.exists():
                bad_paths.append(claim_path)
                duplicate_terminal = True
            if bad_paths:
                terminally_invalidate(
                    entry,
                    ("duplicate_terminal_outcomes" if duplicate_terminal
                     else "invalid_attempt_history"),
                    bad_paths,
                )

        # Global pre-launch ordering gate.  Only the single first unfinished
        # slot may carry crash-window material for adoption/retry.  Material
        # for any later slot proves an out-of-order observation and is
        # terminal before the backend for the earlier slot can launch.
        first_unfinished = len(results)
        for entry in entries[first_unfinished + 1:]:
            future_paths = [path for path, _record
                            in bound_run_records(entry)]
            claim_path = claim_path_for(entry)
            if _path_present(claim_path):
                future_paths.append(claim_path)
            if future_paths:
                terminally_invalidate(
                    entry, "out_of_order_future_material", future_paths)

    referenced_runs = {r.get("run_id") for r in results}
    for entry in entries[len(results):]:
        verify_output_directory(out, output_binding, "run-schedule output")
        terminal_path = terminal_path_for(entry)
        claim_path = claim_path_for(entry)
        stale_claim = False
        if protocol_v2 and _path_present(terminal_path):
            refuse_terminal_invalid(entry)
        if protocol_v2 and _path_present(claim_path):
            claim = load_json_object(claim_path, "schedule entry claim")
            expected_claim = {
                "status": "claimed",
                "protocol_version": PILOT_V2_PROTOCOL_VERSION,
                "schedule_digest": sched_digest,
                "schedule_index": entry["index"],
                "arm": entry["arm"],
                "task": entry["task"],
            }
            if any(claim.get(key) != value
                   for key, value in expected_claim.items()) \
                    or isinstance(claim.get("pid"), bool) \
                    or not isinstance(claim.get("pid"), int) \
                    or claim["pid"] <= 0:
                raise InfraFailure(
                    f"schedule entry {entry['index']} has a corrupted "
                    f"exclusive claim; no backend was launched"
                )
            if process_is_alive(claim.get("pid")):
                raise InfraFailure(
                    f"schedule entry {entry['index']} is owned by an "
                    f"active concurrent resume; no backend was launched"
                )
            stale_claim = True
        # The registered holdout spans several repositories: each task is
        # routed to the clone registered for its own `target-repo`.
        entry_task_text = task_texts[entry["task"]]
        entry_repo = resolve_repo_mapping(
            task_target_repo(entry_task_text, entry["task"]),
            repos, "--repos")
        # Crash window: run_task_with_retries atomically wrote a terminal
        # run record, but the process died before the manifest update. The
        # backend already ran for this entry — re-executing it would add an
        # unaccounted observed replicate to the cell. A uniquely matching
        # orphan record (terminal status, this entry's arm+task, not yet
        # referenced by the manifest) is adopted instead of launched again.
        orphans = []
        inflight = []
        infra_attempts = []
        observed_bound_state = {}
        for record_path in sorted(out.glob("run-*.json")):
            if record_path.name.count("-") != 1:
                continue
            orphan = load_json_object(record_path, "run record")
            if protocol_v2:
                # A task/arm pair occurs in several replicates. Protocol v2
                # therefore binds every attempt to this exact schedule slot;
                # task-only matching would incorrectly consume retries from
                # an earlier replicate of the same cell.
                if (orphan.get("schedule_digest") != sched_digest
                        or orphan.get("schedule_index") != entry["index"]):
                    continue
                if orphan.get("status") in {
                        "completed", "workflow_failure", "infra_failure"}:
                    validate_v2_record_artifacts(out, orphan)
                elif orphan.get("status") != "in_progress":
                    terminally_invalidate(
                        entry, "invalid_attempt_history", [record_path])
                observed_bound_state[record_path.name] = hashlib.sha256(
                    record_path.read_bytes()).hexdigest()
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
            elif (protocol_v2
                  and orphan.get("status") == "infra_failure"):
                infra_attempts.append((record_path, orphan))
        if inflight:
            if protocol_v2:
                terminally_invalidate(
                    entry,
                    "ambiguous_post_launch",
                    [out / name for name in inflight]
                    + ([claim_path] if claim_path.exists() else []),
                )
            write_manifest(False)
            raise InfraFailure(
                f"schedule entry {entry['index']} ({entry['arm']} / "
                f"{entry['task']}) has in-progress run journal(s) without "
                f"a terminal outcome ({', '.join(sorted(inflight))}) — the "
                f"backend may have executed; investigate, then delete the "
                f"journal record(s) to explicitly authorize re-running "
                f"this entry"
            )
        starting_attempt = 1
        if protocol_v2 and infra_attempts:
            by_attempt = {}
            invalid_history = False
            for record_path, record in infra_attempts:
                attempt = record.get("attempt")
                if (isinstance(attempt, bool)
                        or not isinstance(attempt, int)
                        or not 1 <= attempt
                        <= config.get(
                            "max_infra_retries",
                            DEFAULT_MAX_INFRA_RETRIES) + 1
                        or attempt in by_attempt):
                    invalid_history = True
                    break
                by_attempt[attempt] = (record_path, record)
            ordered_attempts = sorted(by_attempt)
            if ordered_attempts != list(
                    range(1, len(ordered_attempts) + 1)):
                invalid_history = True
            if invalid_history:
                terminally_invalidate(
                    entry,
                    "invalid_attempt_history",
                    [path for path, _record in infra_attempts]
                    + ([claim_path] if claim_path.exists() else []),
                )
            if any(record.get("blocking")
                   for _path, record in infra_attempts):
                terminally_invalidate(
                    entry,
                    "blocking_infrastructure_failure",
                    [path for path, _record in infra_attempts]
                    + ([claim_path] if claim_path.exists() else []),
                )
            starting_attempt = ordered_attempts[-1] + 1
            if starting_attempt > config.get(
                    "max_infra_retries", DEFAULT_MAX_INFRA_RETRIES) + 1:
                terminally_invalidate(
                    entry,
                    "infrastructure_retries_exhausted",
                    [path for path, _record in infra_attempts]
                    + ([claim_path] if claim_path.exists() else []),
                )
        if len(orphans) > 1:
            if protocol_v2:
                terminally_invalidate(
                    entry,
                    "duplicate_terminal_outcomes",
                    [out / f"run-{record['run_id']}.json"
                     for record in orphans]
                    + ([claim_path] if claim_path.exists() else []),
                )
            raise InfraFailure(
                f"schedule entry {entry['index']} ({entry['arm']} / "
                f"{entry['task']}) has {len(orphans)} unreferenced terminal "
                f"run records — ambiguous orphan adoption; the output "
                f"directory holds runs the schedule cannot attribute"
            )
        if orphans:
            final = orphans[0]
            if (protocol_v2
                    and final.get("attempt") != starting_attempt):
                terminally_invalidate(
                    entry,
                    "invalid_attempt_history",
                    [path for path, _record in infra_attempts]
                    + [out / f"run-{final['run_id']}.json"]
                    + ([claim_path] if claim_path.exists() else []),
                )
            if protocol_v2:
                validate_v2_final_record_semantics(
                    config, entry, final, task_texts[entry["task"]])
                validate_v2_record_artifacts(out, final)
            if stale_claim:
                durable_unlink(claim_path)
        else:
            if protocol_v2:
                if stale_claim:
                    durable_unlink(claim_path)
                claim = {
                    "status": "claimed",
                    "protocol_version": PILOT_V2_PROTOCOL_VERSION,
                    "schedule_digest": sched_digest,
                    "schedule_index": entry["index"],
                    "arm": entry["arm"],
                    "task": entry["task"],
                    "pid": os.getpid(),
                }
                try:
                    exclusive_write_text(
                        claim_path, json.dumps(claim, indent=2) + "\n")
                except FileExistsError as exc:
                    raise InfraFailure(
                        f"schedule entry {entry['index']} was claimed by "
                        f"another concurrent resume; no backend was "
                        f"launched"
                    ) from exc
                except OSError as exc:
                    raise InfraFailure(
                        f"cannot create exclusive claim for schedule entry "
                        f"{entry['index']}: {exc}"
                    ) from exc
                try:
                    current_bound_state = bound_run_state(entry)
                except BaseException:
                    durable_unlink(claim_path, missing_ok=True)
                    raise
                if current_bound_state != observed_bound_state:
                    durable_unlink(claim_path, missing_ok=True)
                    raise InfraFailure(
                        f"schedule entry {entry['index']} changed while "
                        f"its exclusive launch claim was acquired; no "
                        f"backend was launched — resume to adopt or "
                        f"classify the newly persisted state"
                    )
            try:
                new_attempts = run_task_with_retries(
                    config, entry["arm"], entry["task"], entry_repo,
                    out, scheduled=True,
                    starting_attempt=starting_attempt,
                    schedule_binding={
                        "schedule_digest": sched_digest,
                        "schedule_index": entry["index"],
                    },
                    output_binding=output_binding,
                    task_snapshot=task_snapshots[entry["task"]],
                    heartbeat_completed=len(results),
                    heartbeat_total=len(entries),
                )
                if protocol_v2:
                    for new_record in new_attempts:
                        validate_v2_record_artifacts(out, new_record)
            finally:
                if protocol_v2:
                    durable_unlink(claim_path, missing_ok=True)
            final = new_attempts[-1]
        if final["status"] == "infra_failure":
            # Entry unfinished: persist progress so a re-run resumes HERE.
            if protocol_v2:
                all_infra_paths = [
                    path for path, _record in infra_attempts
                ] + [out / f"run-{record['run_id']}.json"
                     for record in new_attempts]
                terminally_invalidate(
                    entry,
                    ("blocking_infrastructure_failure"
                     if final.get("blocking")
                     else "infrastructure_retries_exhausted"),
                    all_infra_paths,
                )
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
        if protocol_v2:
            validate_v2_final_record_semantics(
                config, entry, final, task_texts[entry["task"]])
            validate_v2_record_artifacts(out, final)
        manifest_result = {
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
            "raw_sha256": final.get("raw_sha256"),
            "task_sha256": schedule["task_digests"][entry["task"]],
        }
        if final.get("protocol_version") == PILOT_V2_PROTOCOL_VERSION:
            manifest_result.update({
                "protocol_version": PILOT_V2_PROTOCOL_VERSION,
                "schedule_digest": final.get("schedule_digest"),
                "environment_policy_id": final.get(
                    "environment_policy_id"),
                "runtime_pins": final.get("runtime_pins"),
                "failure_kind": final.get("failure_kind"),
                "artifact_gate": final.get("artifact_gate"),
                "telemetry_policy_id": final.get("telemetry_policy_id"),
                "telemetry_eligible": final.get("telemetry_eligible"),
                "telemetry_exclusion_reason": final.get(
                    "telemetry_exclusion_reason"),
            })
        results.append(manifest_result)
        referenced_runs.add(final["run_id"])
        write_manifest(False)
    return write_manifest(True)


def _fetch_live_source(fetch_cmd, url, timeout):
    """Source drift is verified against the LIVE authoritative source: the
    harness itself fetches each sealed URL through the registered
    `drift_fetch_cmd`. An operator-supplied local copy is never drift
    evidence — it could be the sealed snapshot itself. The sealed URL is
    delivered as curl-config data on stdin, never exposed in argv or copied
    into an exception message."""
    dest_dir = Path(tempfile.mkdtemp(prefix="rpa-refetch-"))
    try:
        dest = dest_dir / "fetched"
        cmd = [part.replace("{dest}", str(dest)) for part in fetch_cmd]
        if any(url in part or "{url}" in part for part in cmd):
            raise InfraFailure(
                "drift_fetch_cmd must receive its sealed source URL only "
                "through stdin, never argv")
        # seal_package validates a credential-free HTTPS URL with no query,
        # fragment, NUL, or whitespace. Curl's config syntax additionally
        # requires backslash and quote escaping inside a quoted value.
        escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
        fetch_input = f'url = "{escaped_url}"\n'.encode("utf-8")
        try:
            proc = subprocess.run(
                cmd, input=fetch_input, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise InfraFailure(
                "live-source fetch timed out") from exc
        except OSError as exc:
            raise InfraFailure(
                f"cannot execute drift_fetch_cmd: {exc}") from exc
        if proc.returncode != 0:
            raise InfraFailure(
                f"live-source fetch failed (exit {proc.returncode}); "
                "backend detail suppressed because it may repeat the "
                "sealed source URL"
            )
        try:
            return dest.read_bytes()
        except OSError as exc:
            raise InfraFailure(
                f"drift_fetch_cmd produced no output file: {exc}"
            ) from exc
    finally:
        shutil.rmtree(dest_dir, ignore_errors=True)


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


def _read_sealed(path, seal_files, key=None):
    try:
        return _sealed_bytes(path, seal_files, key=key).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfraFailure(
            f"sealed judge input {Path(path).name} is not UTF-8"
        ) from exc


def _read_sealed_reference(registered_ref, seal_manifest_path, seal_files,
                           what):
    """Resolve and read a manifest-owned package-relative text artifact."""
    package_root = Path(seal_manifest_path).resolve().parent
    expected_path = package_root / str(registered_ref)
    key = _sealed_association_key(
        expected_path, registered_ref, seal_manifest_path, what)
    text = _read_sealed(expected_path, seal_files, key=key)
    if not text.strip():
        raise InfraFailure(f"sealed {what} must be nonempty UTF-8 text")
    return text, seal_files[key]


def _sealed_association_key(supplied_path, registered_ref,
                            seal_manifest_path, what):
    """Bind an operator-supplied path to its exact package-relative seal
    association. This supports nested refs without basename ambiguity and
    consistently rejects copies or paths outside the verified package."""
    if not isinstance(registered_ref, str) or not registered_ref:
        raise InfraFailure(f"sealed {what} association is missing")
    package_root = Path(seal_manifest_path).resolve().parent
    expected = (package_root / registered_ref).resolve()
    try:
        expected.relative_to(package_root)
    except ValueError as exc:
        raise InfraFailure(
            f"sealed {what} association is not package-relative") from exc
    try:
        actual = Path(supplied_path).resolve(strict=True)
    except OSError as exc:
        raise InfraFailure(f"cannot resolve supplied sealed {what}") from exc
    if actual != expected:
        raise InfraFailure(
            f"supplied path is not the sealed {what} registered as package "
            f"entry "
            f"`{registered_ref}`"
        )
    return registered_ref


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


def assert_blind_scorable_bytes(doc_path, data):
    """Blinding is enforced at the score boundary itself: a raw runner
    artifact or any document whose fingerprint fields are not masked is
    refused, so a CLI input mistake cannot leak identity to the judge."""
    path = Path(doc_path)
    if path.name.endswith("-raw.md"):
        raise InfraFailure(
            f"{doc_path}: raw runner artifact — blind scoring requires the "
            f"anonymized copy (`run-<id>-anon.md`)"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InfraFailure(
            f"{doc_path}: scoring document is not UTF-8") from exc
    # Fingerprint keys are scanned across the WHOLE document, not only a
    # frontmatter block assumed at line 0: a BOM or blank line before the
    # opening `---` must not smuggle researcher/commit/branch identity
    # past the blind judge. Overmatching refuses a scorable document
    # (operator re-anonymizes); undermatching unblinds the judge.
    for line in text.splitlines():
        explicit = FINGERPRINT_EXPLICIT_KEY_RE.match(line)
        if explicit:
            raise InfraFailure(
                f"{doc_path}: explicit fingerprint key "
                f"`{explicit.group('key').lower()}` is not anonymized — "
                f"blind scoring refused")
        match = FINGERPRINT_KEY_RE.search(line.lstrip("\ufeff"))
        if match and "[anonymized:" not in line:
            raise InfraFailure(
                f"{doc_path}: fingerprint key "
                f"`{match.group('key').lower()}` "
                f"is not anonymized — blind scoring refused"
            )
    for match in BOLD_FINGERPRINT_RE.finditer(text):
        if "[anonymized:" not in match.group(0):
            raise InfraFailure(
                f"{doc_path}: fingerprint line "
                f"`**{match.group('label')}**` is not "
                f"anonymized — blind scoring refused"
            )
    return text


def assert_blind_scorable(doc_path):
    return assert_blind_scorable_bytes(
        doc_path, read_input_bytes(doc_path, "scoring document"))


def _parse_judge_stream_tolerant(stdout, require_structured_output=False):
    """Recover auditable judge-attempt material even when the stream
    transport itself is invalid. Contract validation still fails closed;
    this helper never repairs response JSON."""
    session_id = None
    nodes = []
    result_parts = []
    structured_outputs = []
    stream_defects = []
    for line_number, line in enumerate((stdout or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = _json_without_duplicate_keys(
                line.encode("utf-8"), "judge stream event")
        except InfraFailure as exc:
            stream_defects.append(
                f"stream line {line_number} is not valid JSON: {exc}")
            continue
        if not isinstance(event, dict):
            stream_defects.append(
                f"stream line {line_number} is not a JSON object")
            continue
        if "session_id" in event:
            candidate = event["session_id"]
            if not isinstance(candidate, str) or not candidate.strip():
                stream_defects.append(
                    f"stream line {line_number} has a non-string or empty "
                    f"session_id")
            elif session_id is None:
                session_id = candidate
            elif candidate != session_id:
                stream_defects.append(
                    f"stream line {line_number} conflicts with the first "
                    f"session_id")
        if event.get("type") == "result":
            result_value = event.get("result")
            if require_structured_output:
                if event.get("subtype") != "success":
                    stream_defects.append(
                        f"stream line {line_number} has no successful "
                        "structured-output result")
                if not isinstance(result_value, str):
                    stream_defects.append(
                        f"stream line {line_number} has no string result")
                else:
                    result_parts.append(result_value)
                structured = event.get("structured_output")
                if not isinstance(structured, dict):
                    stream_defects.append(
                        f"stream line {line_number} has no object "
                        "structured_output")
                else:
                    structured_outputs.append(structured)
            elif result_value is not None:
                result_parts.append(str(result_value))
        try:
            node = _node_from_event(event)
        except InfraFailure as exc:
            stream_defects.append(
                f"stream line {line_number} has invalid accounting: {exc}")
            continue
        if node is not None:
            nodes.append(node)
    if session_id is None:
        stream_defects.append("backend output contained no session_id")
    if not nodes:
        stream_defects.append("backend output contained no accounting nodes")
    structured_output = None
    if require_structured_output:
        if len(result_parts) != 1:
            stream_defects.append(
                "backend output must contain exactly one string result")
        if len(structured_outputs) != 1:
            stream_defects.append(
                "backend output must contain exactly one structured_output "
                "object")
        else:
            structured_output = structured_outputs[0]
    return (session_id, nodes, "\n".join(result_parts), structured_output,
            stream_defects)


def _validate_v2_judge_response_pair(response, structured_output, role):
    """Validate both CLI views without treating either as response repair."""

    defects = []
    parsed_response = None
    parsed_structured = None
    try:
        parsed_response = judge_contract.validate_response(response, role)
    except judge_contract.JudgeResponseError as exc:
        defects.append(str(exc))
    if structured_output is None:
        defects.append("structured_output: required object is missing")
    else:
        try:
            structured_text = json.dumps(
                structured_output, ensure_ascii=False, allow_nan=False)
            parsed_structured = judge_contract.validate_response(
                structured_text, role)
        except (TypeError, ValueError,
                judge_contract.JudgeResponseError) as exc:
            defects.append(f"structured_output: {exc}")
    if (parsed_response is not None and parsed_structured is not None
            and parsed_response != parsed_structured):
        defects.append(
            "result JSON differs from the validated structured_output object")
    return parsed_response, defects


def _validate_v2_attempt_record(record, expected):
    """Validate an immutable attempt record during resume. Returns whether
    the attempt contains the first acceptable role response."""
    if not isinstance(record, dict):
        raise InfraFailure("judge attempt record must be a JSON object")
    for key, value in expected.items():
        actual = (Path(record.get(key, "")).name
                  if key == "doc" else record.get(key))
        target = Path(value).name if key == "doc" else value
        if actual != target:
            raise InfraFailure(
                f"judge attempt record `{key}` mismatch: expected "
                f"{target!r}, got {actual!r}"
            )
    for key in ("profile", "cwd"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise InfraFailure(
                f"judge attempt record has no nonempty `{key}` binding")
    launch_defects = record.get("launch_defects")
    if (not isinstance(launch_defects, list)
            or not all(isinstance(item, str) and item
                       for item in launch_defects)):
        raise InfraFailure("judge attempt has malformed launch_defects")

    raw_stream = record.get("raw_stream")
    external = record.get("raw_stream_external")
    external_reason = record.get("raw_stream_external_reason")
    if not isinstance(external, bool):
        raise InfraFailure("judge attempt raw-stream storage mode is invalid")
    if external:
        if external_reason not in ("oversize", "non_utf8"):
            raise InfraFailure(
                "external judge raw stream has no valid storage reason")
        if raw_stream is not None:
            raise InfraFailure(
                "external judge raw stream must not be duplicated inline")
        sidecar = Path(expected["raw_stream_sidecar"])
        if not sidecar.is_file() or sidecar.is_symlink():
            raise InfraFailure(
                "oversized judge raw-stream sidecar is missing or unsafe")
        digest = hashlib.sha256()
        raw_stream_bytes = 0
        utf8_decoder = (
            codecs.getincrementaldecoder("utf-8")()
            if external_reason == "non_utf8" else None)
        utf8_valid = True
        try:
            with sidecar.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    raw_stream_bytes += len(chunk)
                    if utf8_decoder is not None and utf8_valid:
                        try:
                            utf8_decoder.decode(chunk)
                        except UnicodeDecodeError:
                            utf8_valid = False
                if utf8_decoder is not None and utf8_valid:
                    try:
                        utf8_decoder.decode(b"", final=True)
                    except UnicodeDecodeError:
                        utf8_valid = False
        except OSError as exc:
            raise InfraFailure(
                "cannot verify external judge raw-stream sidecar") from exc
        if external_reason == "oversize":
            required_defect = (
                f"judge raw stream exceeded "
                f"{expected['raw_stream_limit_bytes']} bytes")
            proven = raw_stream_bytes > expected["raw_stream_limit_bytes"]
        else:
            required_defect = "judge raw stream is not UTF-8"
            proven = (
                raw_stream_bytes <= expected["raw_stream_limit_bytes"]
                and not utf8_valid)
        if not proven or required_defect not in launch_defects:
            raise InfraFailure(
                "external judge raw stream does not prove its storage reason")
        session_id, nodes, response, structured_output, stream_defects = (
            None, [], "", None, [])
        raw_digest = digest.hexdigest()
    else:
        if external_reason is not None:
            raise InfraFailure(
                "inline judge raw stream has an external storage reason")
        if not isinstance(raw_stream, str):
            raise InfraFailure("judge attempt record has no raw stream text")
        encoded_stream = raw_stream.encode("utf-8")
        raw_stream_bytes = len(encoded_stream)
        if raw_stream_bytes > expected["raw_stream_limit_bytes"]:
            raise InfraFailure("inline judge raw stream exceeds its bound")
        if Path(expected["raw_stream_sidecar"]).exists():
            raise InfraFailure(
                "inline judge attempt unexpectedly has a raw-stream sidecar")
        raw_digest = hashlib.sha256(encoded_stream).hexdigest()
        session_id, nodes, response, structured_output, stream_defects = (
            _parse_judge_stream_tolerant(
                raw_stream, require_structured_output=True))
    if raw_digest != record.get("raw_stream_sha256"):
        raise InfraFailure("judge attempt raw stream digest mismatch")
    if record.get("raw_stream_bytes") != raw_stream_bytes:
        raise InfraFailure("judge attempt raw stream byte count mismatch")
    if record.get("session_id") != session_id:
        raise InfraFailure("judge attempt session_id differs from raw stream")
    if record.get("nodes") != nodes:
        raise InfraFailure("judge attempt nodes differ from raw stream")
    if record.get("response") != response:
        raise InfraFailure("judge attempt response differs from raw stream")
    if ("structured_output" not in record
            or record.get("structured_output") != structured_output):
        raise InfraFailure(
            "judge attempt structured_output differs from raw stream")
    if hashlib.sha256(response.encode("utf-8")).hexdigest() != record.get(
            "response_sha256"):
        raise InfraFailure("judge attempt response digest mismatch")

    defects = list(launch_defects) + stream_defects
    effort_capture = None
    if nodes:
        try:
            validate_models(nodes, expected["judge_model"])
            effort_capture = validate_efforts(
                nodes, expected["judge_effort"])
        except InfraFailure as exc:
            defects.append(f"judge runtime parity failed: {exc}")
    transport_invalid = bool(defects)
    parsed = None
    if not defects:
        parsed, response_defects = _validate_v2_judge_response_pair(
            response, structured_output, expected["role"])
        defects.extend(response_defects)
    valid = not defects
    recomputed = {
        "validation": {"valid": valid, "defects": defects},
        "transport_invalid": transport_invalid,
        "schema_valid": valid,
        "effort_capture": effort_capture,
        "accounting": account(nodes) if nodes else None,
    }
    for field, value in recomputed.items():
        if record.get(field) != value:
            raise InfraFailure(
                f"judge attempt `{field}` differs from recomputation "
                f"over its raw stream and launch defects"
            )
    derived_fields = {
        "evidence_accuracy_numerator",
        "evidence_accuracy_denominator",
        "evidence_accuracy",
    }
    if valid:
        if record.get("parsed_response") != parsed:
            raise InfraFailure(
                "judge attempt parsed_response differs from strict "
                "re-validation"
            )
        if expected["role"] == "verifier":
            numerator = parsed["supported_claims"]
            denominator = parsed["verifiable_claims"]
            accuracy = numerator / denominator if denominator else 0.0
            derived = {
                "evidence_accuracy_numerator": numerator,
                "evidence_accuracy_denominator": denominator,
                "evidence_accuracy": accuracy,
            }
            for field, value in derived.items():
                if record.get(field) != value:
                    raise InfraFailure(
                        f"verifier attempt `{field}` differs from strict "
                        f"recomputation"
                    )
        elif derived_fields.intersection(record):
            raise InfraFailure(
                "scorer attempt unexpectedly carries verifier-derived "
                "metrics"
            )
    else:
        if "parsed_response" in record or derived_fields.intersection(record):
            raise InfraFailure(
                "invalid judge attempt carries accepted parsed/derived data"
            )
    return valid


def compose_v2_judge_prompt(judge_prompt, quality_rubric, response_schema,
                            task_context, document):
    """Compose every sealed protocol-v2 judge input in a fixed order.

    The candidate document remains the final evaluation material.  A short,
    deterministic reminder derived from the exact sealed role contract then
    closes the prompt so output-shape instructions retain highest recency.
    """
    materials = {
        "judge prompt": judge_prompt,
        "quality rubric": quality_rubric,
        "response schema": response_schema,
        "task context": task_context,
        "document": document,
    }
    for name, value in materials.items():
        if not isinstance(value, str) or not value.strip():
            raise InfraFailure(
                f"protocol v2 {name} must be nonempty UTF-8 text")
    try:
        schema_bytes = response_schema.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InfraFailure(
            "protocol v2 response schema is not valid UTF-8 text") from exc
    schema_doc = _json_without_duplicate_keys(
        schema_bytes, "protocol v2 response schema")
    role = schema_doc.get("role") if isinstance(schema_doc, dict) else None
    if (role not in ("scorer", "verifier")
            or schema_doc != judge_contract.contract_schema(role)):
        raise InfraFailure(
            "protocol v2 response schema is not the exact role contract")
    return "\n\n".join((
        judge_prompt,
        "## Sealed quality rubric\n\n" + quality_rubric,
        "## Required response schema\n\n" + response_schema,
        "## Task-specific sealed context\n\n" + task_context,
        "---\n\n" + document,
        judge_contract.output_contract_reminder(role),
    ))


def score(config, doc_paths, judge_prompt_path, output_dir,
          evidence_repo=None, evidence_sha=None, scoring_seed=None,
          manifest_path=None, allow_unscheduled=False, evidence_repos=None,
          task_contexts=None, seal_manifest_path=None, task_snapshots=None,
          drift_report_path=None, score_task_paths=None,
          diagnostic_axis=False):
    """Serialize one role/axis batch across its complete judge state machine."""
    require_standard_v2_registration(config)
    role = ("verifier" if (evidence_repo or evidence_repos is not None)
            else "scorer")
    axis = ("all-docs"
            if config.get("protocol_version", 1)
            == PILOT_V2_PROTOCOL_VERSION
            else ("diagnostic" if diagnostic_axis else "primary"))
    out, output_binding = bind_output_directory(output_dir)
    lock_path = out / f".scoring-{role}-{axis}.lock"
    refuse_missing_persistent_lock_with_state(
        out, lock_path, (f"scoring-{role}-{axis}-*",),
        f"scoring {role}/{axis} batch",
    )
    lock = acquire_advisory_lock(
        lock_path, f"scoring {role}/{axis} batch")
    try:
        return _score_locked(
            config, doc_paths, judge_prompt_path, out,
            evidence_repo=evidence_repo, evidence_sha=evidence_sha,
            scoring_seed=scoring_seed, manifest_path=manifest_path,
            allow_unscheduled=allow_unscheduled,
            evidence_repos=evidence_repos, task_contexts=task_contexts,
            seal_manifest_path=seal_manifest_path,
            task_snapshots=task_snapshots,
            drift_report_path=drift_report_path,
            score_task_paths=score_task_paths,
            diagnostic_axis=diagnostic_axis,
            output_binding=output_binding,
        )
    finally:
        release_advisory_lock(lock)


def _score_locked(config, doc_paths, judge_prompt_path, output_dir,
                  evidence_repo=None, evidence_sha=None, scoring_seed=None,
                  manifest_path=None, allow_unscheduled=False,
                  evidence_repos=None, task_contexts=None,
                  seal_manifest_path=None, task_snapshots=None,
                  drift_report_path=None, score_task_paths=None,
                  diagnostic_axis=False, output_binding=None):
    """One fresh pinned backend session per document. The judge's full
    response text is preserved on disk — it IS the scoring artifact. Judge
    prompts live in the sealed package and are passed in at runtime.
    Documents are presented in a RANDOMIZED order derived from the recorded
    `scoring_seed`, so time-dependent judge/service drift cannot stay
    correlated with an arm, and the sequence stays reproducible.

    Two roles: without evidence inputs the judge is a blind SCORER (empty cwd
    outside the experiment tree, all inspection tools denied). Unscheduled
    verification uses `evidence_repo` + `evidence_sha`; manifest-bound
    verification uses `evidence_repos` to route each task to its own pinned
    checkout. The single-repo arguments are all-or-nothing: one without the
    other is an operator mistake, never a silent role choice."""
    if output_binding is None:
        output_dir, output_binding = bind_output_directory(output_dir)
    else:
        output_dir = verify_output_directory(
            Path(output_dir), output_binding, "scoring output directory")
    protocol_version = config.get("protocol_version", 1)
    v2 = protocol_version == PILOT_V2_PROTOCOL_VERSION
    if not doc_paths and not (v2 and manifest_path is not None):
        raise InfraFailure(
            "an empty judge population is valid only for manifest-bound "
            "protocol-v2 scoring")
    v2_schema_digests = {}
    v2_schema_texts = {}
    quality_rubric_text = None
    quality_rubric_sha256 = None
    judge_prompt_sha256 = None
    doc_texts = None
    if v2 and diagnostic_axis:
        raise InfraFailure(
            "protocol v2 has one `all-docs` axis for both judge roles; "
            "`diagnostic_axis` is a protocol-v1-only mode"
        )
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
    if v2 and manifest_path is None:
        raise InfraFailure(
            "protocol v2 scoring is schedule- and seal-bound; unscheduled "
            "judge batches are not protocol-valid"
        )
    if diagnostic_axis and manifest_path is None:
        raise InfraFailure(
            "`diagnostic_axis` is defined only for manifest-bound scoring "
            "— the diagnostic batch is derived from the manifest's "
            "gate-failed replicates"
        )
    doc_evidence = None
    role = "verifier" if (evidence_repo or evidence_repos is not None) else "scorer"
    if v2:
        expected_scoring_seed = (
            PILOT_V2_VERIFIER_SEED
            if role == "verifier" else PILOT_V2_SCORER_SEED)
        if scoring_seed != expected_scoring_seed:
            raise InfraFailure(
                f"protocol v2 {role} requires the registered scoring seed "
                f"{expected_scoring_seed}")
    if diagnostic_axis and role == "verifier":
        raise InfraFailure(
            "`diagnostic_axis` is defined only for the blind SCORER — the "
            "registered amendment scores document CONTENT; verifier-mode "
            "diagnostic records are outside the protocol"
        )
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
        if v2:
            # Complete-population handoff gate: refuse every extra, foreign,
            # orphan, claimed, or terminal-invalid run artifact before a
            # judge backend can observe even the first document.
            audit_completed_v2_run_material(
                config, manifest_path, sched_obj,
                manifest.get("results", []), sched_obj.get("entries", []),
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
        if v2:
            scoreable = []
            for result in manifest.get("results", []):
                gate = result.get("artifact_gate")
                if gate == "passed":
                    if not result.get("artifact_sha256"):
                        raise InfraFailure(
                            "artifact-gate-passed v2 result has no bound "
                            "anonymized artifact digest")
                    scoreable.append((
                        result, f"run-{result['run_id']}-anon.md",
                        result["artifact_sha256"]))
                elif gate == "failed":
                    if not result.get("diagnostic_sha256"):
                        raise InfraFailure(
                            "artifact-gate-failed v2 result has no bound "
                            "anonymized diagnostic artifact digest")
                    scoreable.append((
                        result, f"run-{result['run_id']}-diag.md",
                        result["diagnostic_sha256"]))
                elif gate != "not_evaluated":
                    raise InfraFailure(
                        f"v2 result has invalid artifact_gate {gate!r}")
        else:
            scoreable = [(r, f"run-{r['run_id']}-anon.md",
                          r.get("artifact_sha256")) for r in completed]
        if not v2 and diagnostic_axis:
            scoreable += [
                (r, f"run-{r['run_id']}-diag.md",
                 r.get("diagnostic_sha256"))
                for r in manifest.get("results", [])
                if r.get("status") == "workflow_failure"
                and r.get("diagnostic_sha256")
            ]
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
        task_text_by_path = {}
        for registered_task in sched_obj["tasks"]:
            task_bytes = read_task_bytes(registered_task)
            if hashlib.sha256(task_bytes).hexdigest() != sched_obj[
                    "task_digests"].get(registered_task):
                raise InfraFailure(
                    f"{registered_task}: task file changed since the "
                    "scheduled run")
            task_text_by_path[registered_task] = decode_task_bytes(
                task_bytes, registered_task)
        # The seeded presentation shuffle also has one registered base order:
        # the produced-document order in the completed run manifest.  A set
        # comparison would let a caller permute the same documents and obtain
        # a different, yet apparently seed-valid, judge presentation.
        expected_names = [name for _, name, _ in scoreable]
        supplied_names = [Path(d).name for d in doc_paths]
        if supplied_names != expected_names:
            raise InfraFailure(
                f"scoring inputs must contain every produced scheduled "
                f"document exactly once in canonical manifest order — "
                f"expected {expected_names}, "
                f"got {supplied_names}"
            )
        # Identity by name is not enough: the contents must be the exact
        # artifact the run produced, or an edited/substituted file with the
        # right name would be scored as that replicate.
        digest_by_name = {name: digest for _, name, digest in scoreable}
        doc_texts = []
        for doc in doc_paths:
            doc_bytes = read_input_bytes(doc, "scoring document")
            actual = hashlib.sha256(doc_bytes).hexdigest()
            if actual != digest_by_name.get(Path(doc).name):
                raise InfraFailure(
                    f"{doc}: contents differ from the artifact digest "
                    f"recorded at run time — scored documents must be the "
                    f"exact run artifacts"
                )
            doc_texts.append(assert_blind_scorable_bytes(doc, doc_bytes))
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
        snapshot_by_task = {}
        inconclusive_docs = set()
        drift_notes = {}
        task_drift_notes = {}
        drift_report = None
        if drift_report_path is not None:
            drift_report = load_json_object(drift_report_path,
                                            "drift report")
        doc_evidence = {} if evidence_repos is not None else None
        for registered_task in sched_obj["tasks"]:
            registered_text = task_text_by_path[registered_task]
            if re.search(r"^external-snapshots:\s*true\s*$",
                         registered_text, re.MULTILINE):
                registered_name = Path(registered_task).name
                if (not task_snapshots
                        or registered_name not in task_snapshots):
                    raise InfraFailure(
                        f"{registered_task}: task requires sealed external "
                        f"snapshots — supply --task-snapshots "
                        f"{registered_name}=<sealed snapshot file/dir>")
                snapshot_by_task[registered_name] = task_snapshots[
                    registered_name]
        for r, doc_name, _ in scoreable:
            task_text = task_text_by_path[r["task"]]
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
            task_name = Path(r["task"]).name
            if task_name in snapshot_by_task:
                snapshot_by_doc[doc_name] = snapshot_by_task[task_name]
                snap_task_by_doc[doc_name] = task_name
    else:
        context_by_doc = None
        task_by_doc = None
        snapshot_by_doc = {}
        snapshot_by_task = {}
        inconclusive_docs = set()
        drift_notes = {}
        task_drift_notes = {}
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
        schema_validation = validate_sealed_judge_config(
            config, seal_doc, seal_manifest_path, seal_files,
            include_schema_text=v2)
        if v2:
            v2_schema_digests, v2_schema_texts = schema_validation
        else:
            v2_schema_digests = schema_validation
        # The seal binds each task to ITS scoring context: a per-file hash
        # proves a context is sealed, not that it belongs to this task —
        # swapped mappings would judge replicates against another task's
        # ground truth.
        seal_assoc = seal_doc.get("task_contexts", {})
        context_seal_keys = {}
        for assoc_doc, ctx_path in context_by_doc.items():
            assoc_task = Path(task_by_doc[assoc_doc]).name
            expected_ctx = seal_assoc.get(assoc_task)
            if not expected_ctx:
                raise InfraFailure(
                    f"{assoc_task}: the sealed package records no "
                    f"task→context association — the seal must bind each "
                    f"task to its scoring context"
                )
            context_seal_keys[assoc_doc] = _sealed_association_key(
                ctx_path, expected_ctx, seal_manifest_path,
                f"context for {assoc_task}")
        seal_prompts = seal_doc.get("judge_prompts", {})
        expected_prompt = seal_prompts.get(role)
        if not expected_prompt:
            raise InfraFailure(
                f"the sealed package records no judge prompt for role "
                f"`{role}` — the seal must bind each role to its prompt"
            )
        prompt_seal_key = _sealed_association_key(
            judge_prompt_path, expected_prompt, seal_manifest_path,
            f"{role} judge prompt")
        judge_prompt = _read_sealed(
            judge_prompt_path, seal_files, key=prompt_seal_key)
        if not judge_prompt.strip():
            raise InfraFailure(
                f"sealed {role} judge prompt must be nonempty UTF-8 text")
        judge_prompt_sha256 = seal_files[prompt_seal_key]
        if v2:
            quality_rubric_text, quality_rubric_sha256 = (
                _read_sealed_reference(
                    seal_doc.get("quality_rubric"), seal_manifest_path,
                    seal_files, "quality rubric"))
        sealed_context_texts = {
            doc_name: _read_sealed(
                ctx_path, seal_files, key=context_seal_keys[doc_name])
            for doc_name, ctx_path in context_by_doc.items()
        }
        empty_contexts = [
            doc_name for doc_name, text in sealed_context_texts.items()
            if not text.strip()
        ]
        if empty_contexts:
            raise InfraFailure(
                "sealed task contexts must be nonempty UTF-8 text")
        # Registered source-drift gate, COMPUTED by the harness: a status
        # claim is not evidence. The operator's recorded re-fetch step
        # supplies the re-fetched copies; the harness diffs them against
        # the SEALED snapshot digests — any mismatch makes the task
        # inconclusive for scorer and verifier alike.
        if snapshot_by_task:
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
                    or any("{url}" in p for p in fetch_cmd)
                    or not any("{dest}" in p for p in fetch_cmd)):
                raise InfraFailure(
                    "external-context scoring requires a registered "
                    "`drift_fetch_cmd` (non-empty command with a {dest} "
                    "placeholder and no {url} placeholder); the sealed "
                    "source URL is supplied only through stdin while the "
                    "harness re-fetches it — local copies are not accepted "
                    "as drift evidence"
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
            task_docs = {
                task_name: (snap_path, [])
                for task_name, snap_path in snapshot_by_task.items()
            }
            for doc_name, snap_path in snapshot_by_doc.items():
                task_name = snap_task_by_doc[doc_name]
                entry = task_docs[task_name]
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
                if set(drift_entry) != {"changed"} or not isinstance(
                        drift_entry.get("changed"), dict):
                    # The gate never trusts operator-supplied bytes or
                    # loosely typed status claims: a local path could be the
                    # sealed snapshot itself, while a malformed/extra field
                    # must not become meaningful only after live drift.
                    raise InfraFailure(
                        f"{task_name}: drift report entry must contain "
                        "exactly one `changed` object — the harness fetches "
                        "the sealed source URLs itself"
                    )
                adjudications = drift_entry["changed"]
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
                if set(adjudications) != set(changed_keys):
                    raise InfraFailure(
                        f"{task_name}: drift report must adjudicate exactly "
                        "the sources whose live bytes differ from the seal"
                    )
                material = False
                if changed_keys:
                    # The registered gate is about MATERIAL drift in a
                    # relevant section, not cosmetic churn: every changed
                    # file needs a recorded materiality adjudication
                    # (verdict + rationale). Material change -> task
                    # inconclusive; adjudicated-cosmetic change -> still
                    # scoreable, adjudication kept in the record.
                    for key in changed_keys:
                        adj = adjudications.get(key)
                        if (not isinstance(adj, dict)
                                or set(adj) != {
                                    "material", "rationale",
                                    "observed_sha256"}
                                or not isinstance(adj.get("material"), bool)
                                or not isinstance(adj.get("rationale"), str)
                                or not adj["rationale"].strip()
                                or not isinstance(
                                    adj.get("observed_sha256"), str)
                                or not re.fullmatch(
                                    r"[0-9a-f]{64}",
                                    adj["observed_sha256"])
                                or adj["observed_sha256"]
                                != fetched_digests[key]):
                            raise InfraFailure(
                                f"{task_name}: re-fetched source `{key}` "
                                f"changed but carries no recorded "
                                f"digest-bound materiality adjudication "
                                f"(observed_sha256 + material: true/false "
                                f"+ rationale) — a verdict for different "
                                f"live bytes is not accepted"
                            )
                        if adj["material"]:
                            material = True
                # The per-document decision is exactly the projection of the
                # role-level live-byte receipt, including the unchanged case.
                # This prevents two independently plausible but inconsistent
                # drift stories inside one judge manifest.
                note = {
                    "changed": changed_keys,
                    "material": material,
                    "adjudications": {
                        key: adjudications[key] for key in changed_keys
                    },
                }
                for doc_name in doc_names:
                    drift_notes[doc_name] = note
                    if material:
                        inconclusive_docs.add(doc_name)
                task_drift_notes[task_name] = {
                    "observed_sha256": {
                        seal_key: fetched_digests[seal_key]
                        for _snap, _rel, seal_key in snap_items
                    },
                    "changed": changed_keys,
                    "material": material,
                    "adjudications": {
                        key: adjudications[key] for key in changed_keys
                    },
                }
    else:
        judge_prompt = read_input_text(judge_prompt_path, "judge prompt")
        sealed_context_texts = None
    judge_cmd = config.get("judge_backend_cmd", config["backend_cmd"])
    if any("{installation}" in part for part in judge_cmd):
        raise InfraFailure(
            "judge command must be mount-free — set `judge_backend_cmd` "
            "(judges run without any arm installation)"
        )
    if v2:
        refuse_v2_structured_output_override(judge_cmd)
    judge_model = config.get("judge_model")
    if not judge_model:
        raise InfraFailure("`judge_model` must be configured for score mode")
    judge_effort = config.get("judge_effort", "default")
    validate_timeout(config)
    require_effort_pin(judge_cmd, "judge command")
    judge_cmd = expand_backend_cmd(judge_cmd, None, judge_effort)
    if doc_texts is None:
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
    axis = ("all-docs" if v2 else
            ("diagnostic" if diagnostic_axis else "primary"))
    if v2 and role not in v2_schema_digests:
        raise InfraFailure(
            f"protocol v2 scoring has no validated sealed schema for "
            f"role `{role}`"
        )
    batch_identity = {
        "scoring_seed": scoring_seed,
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "config_digest": config_digest(config),
        "role": role,
        "axis": axis,
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
            "tasks": task_drift_notes,
        },
    }
    if v2:
        batch_identity.update({
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "response_schema_version": judge_contract.RESPONSE_SCHEMA_VERSION,
            "schema_sha256": v2_schema_digests[role],
            "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
            "structured_output_schema_sha256": (
                judge_contract.structured_output_schema_sha256(role)),
            "final_response_contract_sha256": (
                judge_contract.final_response_contract_sha256(role)),
            "judge_prompt_sha256": judge_prompt_sha256,
            "quality_rubric_sha256": quality_rubric_sha256,
        })
    # Batch state is namespaced by role AND axis: the scorer pass, the
    # verifier pass, and the registered diagnostic-axis pass over the
    # same output directory must coexist — a completed primary batch
    # must not reject the diagnostic batch as already complete (nor an
    # interrupted one as a different identity).
    scoring_manifest_path = out / f"scoring-{role}-{axis}-manifest.json"
    def resume_batch(prior_batch):
        if set(prior_batch) != {"scoring_id", "identity", "results",
                                "complete"}:
            raise InfraFailure(
                "existing scoring batch manifest has an invalid shape")
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
        prior_scoring_id = prior_batch.get("scoring_id")
        if (not isinstance(prior_scoring_id, str)
                or re.fullmatch(r"[0-9a-f]{8}", prior_scoring_id) is None):
            raise InfraFailure("existing scoring batch has an invalid id")
        prior_results = prior_batch.get("results")
        if (not isinstance(prior_results, list)
                or len(prior_results) > len(doc_paths)):
            raise InfraFailure(
                "existing scoring batch has an invalid result prefix")
        return prior_scoring_id, list(prior_results)

    if scoring_manifest_path.exists():
        prior_batch = load_json_object(scoring_manifest_path,
                                       "scoring batch manifest")
        scoring_id, results = resume_batch(prior_batch)
    else:
        scoring_id = uuid.uuid4().hex[:8]
        results = []
        initial_batch = {
            "scoring_id": scoring_id,
            "identity": batch_identity,
            "results": results,
            "complete": False,
        }
        try:
            # Initial creation is itself the batch-id election. O_EXCL
            # prevents two empty-directory invocations from choosing two
            # scoring ids and both launching a full judge population.
            exclusive_write_text(
                scoring_manifest_path,
                json.dumps(initial_batch, indent=2) + "\n",
            )
        except FileExistsError:
            prior_batch = load_json_object(
                scoring_manifest_path, "concurrently initialized scoring "
                "batch manifest")
            scoring_id, results = resume_batch(prior_batch)
        except OSError as exc:
            raise InfraFailure(
                f"cannot initialize scoring batch exclusively: {exc}"
            ) from exc

    def write_scoring_manifest(complete):
        atomic_write_text(scoring_manifest_path, json.dumps({
            "scoring_id": scoring_id,
            "identity": batch_identity,
            "results": results,
            "complete": complete,
        }, indent=2) + "\n")

    def v2_batch_invalid_path():
        return out / f"scoring-{role}-{axis}-terminal-invalid.json"

    def v2_refuse_batch_invalid():
        invalid_path = v2_batch_invalid_path()
        terminal = load_json_object(
            invalid_path, "terminal-invalid scoring batch record")
        expected = {
            "status": "terminal_invalid",
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "role": role,
            "axis": axis,
            "scoring_id": scoring_id,
            "identity_sha256": hashlib.sha256(json.dumps(
                batch_identity, sort_keys=True).encode("utf-8")).hexdigest(),
        }
        if (any(terminal.get(key) != value
                for key, value in expected.items())
                or terminal.get("kind") != "foreign_batch_material"
                or not isinstance(terminal.get("evidence"), list)):
            raise InfraFailure(
                "terminal-invalid scoring batch record is corrupted; the "
                "batch remains invalid")
        raise InfraFailure(
            "protocol v2 scoring batch is terminally invalid (foreign or "
            "out-of-protocol judge material); create a fresh seal and "
            "scoring batch")

    def v2_terminally_invalidate_batch(evidence_paths):
        invalid_path = v2_batch_invalid_path()
        if _path_present(invalid_path):
            v2_refuse_batch_invalid()
        evidence = [
            _evidence_descriptor(path)
            for path in sorted(set(evidence_paths), key=lambda item: item.name)
        ]
        terminal = {
            "status": "terminal_invalid",
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "role": role,
            "axis": axis,
            "scoring_id": scoring_id,
            "identity_sha256": hashlib.sha256(json.dumps(
                batch_identity, sort_keys=True).encode("utf-8")).hexdigest(),
            "kind": "foreign_batch_material",
            "evidence": evidence,
        }
        atomic_write_text(
            invalid_path, json.dumps(terminal, indent=2) + "\n")
        write_scoring_manifest(False)
        v2_refuse_batch_invalid()

    def v2_audit_scoring_namespace():
        """Allow only the two registered v2 role manifests and locks."""
        required = {
            f"scoring-{role}-all-docs-manifest.json",
            f".scoring-{role}-all-docs.lock",
        }
        if role == "verifier":
            required.add("scoring-scorer-all-docs-manifest.json")
            required.add(".scoring-scorer-all-docs.lock")
        unexpected = []
        candidates = {
            path for pattern in ("scoring-*", ".scoring-*")
            for path in out.glob(pattern)
        }
        for path in sorted(candidates, key=lambda item: item.name):
            if (path.name not in required
                    or not _safe_single_link_regular_file(path)):
                unexpected.append(path)
        if unexpected or {path.name for path in candidates} != required:
            v2_terminally_invalidate_batch(unexpected)

    def v2_audit_judge_namespace(registered_ids):
        """Reject unknown ids/types and return current-role material by slot."""
        current_allowed = re.compile(
            rf"^judge-{re.escape(scoring_id)}-(\d+)(?:\.json|"
            rf"-exhausted\.json|-terminal-invalid\.json|"
            rf"-attempt-(\d+)(?:\.json|\.pending|-raw-stream\.txt))$")
        namespace = re.compile(r"^judge-([0-9a-f]{8})-(.+)$")
        unexpected = []
        current_by_slot = {}
        for path in sorted(out.glob("judge-*"), key=lambda item: item.name):
            match = namespace.fullmatch(path.name)
            if (not _safe_regular_file(path) or match is None
                    or match.group(1) not in registered_ids):
                unexpected.append(path)
                continue
            if match.group(1) != scoring_id:
                continue
            current_match = current_allowed.fullmatch(path.name)
            if current_match is None:
                unexpected.append(path)
                continue
            slot = int(current_match.group(1))
            attempt = current_match.group(2)
            if (not 0 <= slot < len(doc_paths)
                    or attempt is not None and not (
                        1 <= int(attempt)
                        <= PILOT_V2_MAX_JUDGE_ATTEMPTS)):
                unexpected.append(path)
                continue
            current_by_slot.setdefault(slot, []).append(path)
        if unexpected:
            v2_terminally_invalidate_batch(unexpected)
        return current_by_slot

    # The scoring id was persisted by the exclusive batch-id election before
    # the first judge record can be written. Existing incomplete manifests
    # are never rewritten merely by opening them: a concurrent resume must
    # not clobber progress written after its read.

    def v2_attempt_expected_for(batch_role, batch_id, batch_seed,
                                doc, slot, attempt):
        doc_name = Path(doc).name
        prompt_ref = seal_doc.get("judge_prompts", {}).get(batch_role)
        prompt_digest = seal_files.get(prompt_ref)
        expected = {
            "doc": str(doc),
            "presentation_index": slot,
            "scoring_id": batch_id,
            "role": batch_role,
            "axis": "all-docs",
            "attempt": attempt,
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "response_schema_version": judge_contract.RESPONSE_SCHEMA_VERSION,
            "schema_sha256": v2_schema_digests[batch_role],
            "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
            "structured_output_schema_sha256": (
                judge_contract.structured_output_schema_sha256(batch_role)),
            "final_response_contract_sha256": (
                judge_contract.final_response_contract_sha256(batch_role)),
            "judge_prompt_sha256": prompt_digest,
            "quality_rubric_sha256": quality_rubric_sha256,
            "config_digest": config_digest(config),
            "backend_version": config.get("backend_version"),
            "scoring_seed": batch_seed,
            "scheduled": manifest_path is not None,
            "judge_model": judge_model,
            "judge_effort": judge_effort,
            "profile_settings": (
                VERIFIER_SETTINGS
                if batch_role == "verifier" else JUDGE_SETTINGS),
            "task": (task_by_doc.get(doc_name)
                     if task_by_doc is not None else None),
            "task_context": (str(context_by_doc[doc_name])
                             if context_by_doc is not None else None),
            "seal_manifest": (str(seal_manifest_path)
                              if seal_manifest_path is not None else None),
            "snapshots": snapshot_by_doc.get(doc_name),
            "source_drift": drift_notes.get(doc_name),
            "raw_stream_limit_bytes": PILOT_V2_MAX_RAW_STREAM_BYTES,
            "raw_stream_sidecar": str(
                out / f"judge-{batch_id}-{slot}-attempt-{attempt}-"
                f"raw-stream.txt"),
        }
        if batch_role == "verifier" and doc_evidence is not None:
            expected["evidence_sha"] = doc_evidence[doc_name][1]
        elif batch_role == "verifier" and evidence_repo is not None:
            expected["evidence_sha"] = evidence_sha
        return expected

    def v2_attempt_expected(doc, slot, attempt):
        return v2_attempt_expected_for(
            role, scoring_id, scoring_seed, doc, slot, attempt)

    def v2_launch_attempt(doc, doc_text, slot, attempt, ev_repo, ev_sha):
        """Launch and durably record one fresh v2 judge attempt. Known
        transport/runtime/contract defects consume the attempt and are
        retained; an unexpected harness crash leaves the pending journal."""
        verify_output_directory(
            out, output_binding, "scoring output directory")
        attempt_path = out / (
            f"judge-{scoring_id}-{slot}-attempt-{attempt}.json")
        pending_path = out / (
            f"judge-{scoring_id}-{slot}-attempt-{attempt}.pending")
        backend_version = verify_backend_version(config)
        judge_root = Path(tempfile.mkdtemp(prefix="rpa-judge-"))
        workdir = None
        profile = None
        try:
            if ev_repo:
                profile, _ = make_profile(
                    judge_root, "judge", settings=VERIFIER_SETTINGS)
                workdir = make_worktree(ev_repo, ev_sha, judge_root)
                if Path(doc).name in snapshot_by_doc:
                    snap_src = Path(snapshot_by_doc[Path(doc).name])
                    snap_dest = workdir / "_sealed-snapshots"
                    snap_dest.mkdir()
                    for snap, rel, seal_key in _sealed_snapshot_items(
                            snap_src, seal_files):
                        dest = snap_dest / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(
                            _sealed_bytes(snap, seal_files, key=seal_key))
            else:
                profile, _ = make_profile(
                    judge_root, "judge", settings=JUDGE_SETTINGS)
                workdir = judge_root / "workdir"
                workdir.mkdir()

            env = backend_env(profile, protocol_version)
            sandboxed_cmd = apply_sandbox(
                config, with_stream_json_transport(judge_cmd), workdir,
                profile)
            prompt = compose_v2_judge_prompt(
                judge_prompt,
                quality_rubric_text,
                v2_schema_texts[role],
                sealed_context_texts[Path(doc).name],
                doc_text,
            )
            verify_output_directory(
                out, output_binding, "scoring output directory")
            try:
                exclusive_write_text(pending_path, json.dumps({
                    **v2_attempt_expected(doc, slot, attempt),
                    "status": "in_progress",
                    "pid": os.getpid(),
                }, indent=2) + "\n")
            except FileExistsError as exc:
                # Another resume won the only atomic launch claim. It may be
                # live, so this process blocks without invalidating or
                # overwriting its journal and, crucially, without launching
                # a second nondeterministic judge session.
                raise InfraFailure(
                    f"judge slot {slot} attempt {attempt} is owned by a "
                    f"concurrent resume; no judge session was launched"
                ) from exc
            except OSError as exc:
                raise InfraFailure(
                    f"cannot create exclusive judge claim for slot {slot}, "
                    f"attempt {attempt}: {exc}"
                ) from exc

            sidecar_path = Path(v2_attempt_expected(
                doc, slot, attempt)["raw_stream_sidecar"])
            (stdout, raw_stream_bytes, raw_stream_sha256, launch_defects,
             external_stream) = spawn_judge_session_capped(
                    sandboxed_cmd, prompt, str(workdir), env,
                    config["timeout_seconds"], sidecar_path,
                    PILOT_V2_MAX_RAW_STREAM_BYTES,
                    structured_output_schema=(
                        judge_contract.structured_output_schema_text(role)),
                    heartbeat_call=attempt,
                    heartbeat_call_total=PILOT_V2_MAX_JUDGE_ATTEMPTS,
                    heartbeat_completed=slot,
                    heartbeat_total=len(order))
            if external_stream:
                (session_id, nodes, response, structured_output,
                 stream_defects) = (None, [], "", None, [])
            else:
                (session_id, nodes, response, structured_output,
                 stream_defects) = _parse_judge_stream_tolerant(
                    stdout, require_structured_output=True)
            defects = launch_defects + stream_defects
            effort_capture = None
            if nodes:
                try:
                    validate_models(nodes, judge_model)
                    effort_capture = validate_efforts(nodes, judge_effort)
                except InfraFailure as exc:
                    defects.append(f"judge runtime parity failed: {exc}")
            non_schema_invalid = bool(defects)
            parsed_response = None
            if not defects:
                parsed_response, response_defects = (
                    _validate_v2_judge_response_pair(
                        response, structured_output, role))
                defects.extend(response_defects)
            valid = not defects
            result = {
                **v2_attempt_expected(doc, slot, attempt),
                "session_id": session_id,
                "profile": str(profile),
                "cwd": str(workdir),
                "backend_version": backend_version,
                "scoring_seed": scoring_seed,
                "scheduled": manifest_path is not None,
                "judge_model": judge_model,
                "judge_effort": judge_effort,
                "task": (task_by_doc.get(Path(doc).name)
                         if task_by_doc is not None else None),
                "task_context": (
                    str(context_by_doc[Path(doc).name])
                    if context_by_doc is not None else None),
                "seal_manifest": (str(seal_manifest_path)
                                  if seal_manifest_path is not None else None),
                "snapshots": snapshot_by_doc.get(Path(doc).name),
                "source_drift": drift_notes.get(Path(doc).name),
                "effort_capture": effort_capture,
                "raw_stream": stdout,
                "raw_stream_external": external_stream,
                "raw_stream_external_reason": (
                    "oversize" if external_stream and raw_stream_bytes
                    > PILOT_V2_MAX_RAW_STREAM_BYTES
                    else "non_utf8" if external_stream else None),
                "raw_stream_bytes": raw_stream_bytes,
                "raw_stream_sha256": raw_stream_sha256,
                "nodes": nodes,
                "launch_defects": launch_defects,
                "response": response,
                "structured_output": structured_output,
                "response_sha256": hashlib.sha256(
                    response.encode("utf-8")).hexdigest(),
                "accounting": account(nodes) if nodes else None,
                "schema_valid": valid,
                "transport_invalid": non_schema_invalid,
                "validation": {"valid": valid, "defects": defects},
            }
            if ev_repo:
                result["evidence_sha"] = ev_sha
            if valid:
                result["parsed_response"] = parsed_response
                if role == "verifier":
                    numerator = parsed_response["supported_claims"]
                    denominator = parsed_response["verifiable_claims"]
                    result.update({
                        "evidence_accuracy_numerator": numerator,
                        "evidence_accuracy_denominator": denominator,
                        "evidence_accuracy": (
                            numerator / denominator if denominator else 0.0),
                    })
            try:
                exclusive_write_text(
                    attempt_path, json.dumps(result, indent=2) + "\n")
            except FileExistsError:
                collision_path = out / (
                    f"judge-{scoring_id}-{slot}-attempt-{attempt}-"
                    f"collision-{uuid.uuid4().hex[:8]}.json")
                exclusive_write_text(
                    collision_path, json.dumps(result, indent=2) + "\n")
                durable_unlink(pending_path, missing_ok=True)
                v2_terminally_invalidate(
                    doc, slot, "invalid_attempt_history",
                    [attempt_path, collision_path])
            durable_unlink(pending_path, missing_ok=True)
            return result
        finally:
            if ev_repo and workdir is not None:
                remove_worktree(ev_repo, workdir)
            shutil.rmtree(judge_root, ignore_errors=True)

    def v2_attempt_material(slot):
        return sorted(
            out.glob(f"judge-{scoring_id}-{slot}-attempt-*"),
            key=lambda path: path.name,
        )

    def v2_scan_attempts(doc, slot):
        """Adopt a contiguous attempt prefix. A pending journal without its
        attempt record blocks; a valid orphan is returned for promotion."""
        # Raw-stream sidecars are immutable evidence belonging to exactly one
        # persisted attempt record.  A sidecar cannot authorize a fresh
        # launch when its record is missing: that would truncate/replace the
        # only evidence that a previous launch happened.  Sidecars paired to
        # inline records are rejected by `_validate_v2_attempt_record`; an
        # external record is accepted only after that validator re-hashes and
        # proves its declared storage reason.
        for sidecar in sorted(out.glob(
                f"judge-{scoring_id}-{slot}-attempt-*-raw-stream.txt")):
            match = re.fullmatch(
                rf"judge-{re.escape(scoring_id)}-{slot}-attempt-(\d+)-"
                rf"raw-stream\.txt",
                sidecar.name,
            )
            if match is None:
                v2_terminally_invalidate(
                    doc, slot, "invalid_attempt_history",
                    v2_attempt_material(slot))
            attempt_number = int(match.group(1))
            attempt_path = out / (
                f"judge-{scoring_id}-{slot}-attempt-"
                f"{attempt_number}.json")
            if not attempt_path.exists():
                v2_terminally_invalidate(
                    doc, slot, "invalid_attempt_history",
                    v2_attempt_material(slot))
        first_valid = None
        first_missing = None
        records = []
        for attempt in range(1, PILOT_V2_MAX_JUDGE_ATTEMPTS + 1):
            attempt_path = out / (
                f"judge-{scoring_id}-{slot}-attempt-{attempt}.json")
            pending_path = out / (
                f"judge-{scoring_id}-{slot}-attempt-{attempt}.pending")
            if not attempt_path.exists():
                if pending_path.exists():
                    try:
                        pending = load_json_object(
                            pending_path, "pending judge attempt claim")
                    except InfraFailure:
                        v2_terminally_invalidate(
                            doc, slot, "invalid_attempt_history",
                            v2_attempt_material(slot))
                    expected_pending = {
                        **v2_attempt_expected(doc, slot, attempt),
                        "status": "in_progress",
                    }
                    pending_matches = all(
                        pending.get(key) == value
                        for key, value in expected_pending.items())
                    if (pending_matches
                            and process_is_alive(pending.get("pid"))):
                        raise InfraFailure(
                            f"judge slot {slot} attempt {attempt} is owned "
                            f"by an active concurrent resume; no judge "
                            f"session was launched"
                        )
                    v2_terminally_invalidate(
                        doc, slot, "ambiguous_post_launch",
                        [pending_path],
                    )
                first_missing = attempt
                for later in range(
                        attempt + 1, PILOT_V2_MAX_JUDGE_ATTEMPTS + 1):
                    if ((out / f"judge-{scoring_id}-{slot}-attempt-"
                         f"{later}.json").exists()
                            or (out / f"judge-{scoring_id}-{slot}-attempt-"
                                f"{later}.pending").exists()):
                        v2_terminally_invalidate(
                            doc, slot, "invalid_attempt_history",
                            v2_attempt_material(slot))
                break
            try:
                record = load_json_object(
                    attempt_path, "judge attempt record")
                valid = _validate_v2_attempt_record(
                    record, v2_attempt_expected(doc, slot, attempt))
            except (InfraFailure, OSError, ValueError, TypeError):
                v2_terminally_invalidate(
                    doc, slot, "invalid_attempt_history",
                    v2_attempt_material(slot))
            records.append(record)
            if pending_path.exists():
                try:
                    pending = load_json_object(
                        pending_path, "pending judge attempt claim")
                except InfraFailure:
                    v2_terminally_invalidate(
                        doc, slot, "invalid_attempt_history",
                        v2_attempt_material(slot))
                expected_pending = {
                    **v2_attempt_expected(doc, slot, attempt),
                    "status": "in_progress",
                }
                if not all(pending.get(key) == value
                           for key, value in expected_pending.items()):
                    v2_terminally_invalidate(
                        doc, slot, "invalid_attempt_history",
                        v2_attempt_material(slot))
                durable_unlink(pending_path)
            if valid:
                if first_valid is not None:
                    v2_terminally_invalidate(
                        doc, slot, "invalid_attempt_history",
                        v2_attempt_material(slot))
                first_valid = record
                for later in range(
                        attempt + 1, PILOT_V2_MAX_JUDGE_ATTEMPTS + 1):
                    if ((out / f"judge-{scoring_id}-{slot}-attempt-"
                         f"{later}.json").exists()
                            or (out / f"judge-{scoring_id}-{slot}-attempt-"
                                f"{later}.pending").exists()):
                        v2_terminally_invalidate(
                            doc, slot, "invalid_attempt_history",
                            v2_attempt_material(slot))
                break
        return first_valid, first_missing, records

    def v2_invalid_path(slot):
        return out / f"judge-{scoring_id}-{slot}-terminal-invalid.json"

    def v2_terminal_core(doc, slot):
        return {
            "doc": str(doc),
            "scoring_id": scoring_id,
            "presentation_index": slot,
            "role": role,
            "axis": "all-docs",
            "status": "terminal_invalid",
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "response_schema_version": judge_contract.RESPONSE_SCHEMA_VERSION,
            "schema_sha256": v2_schema_digests[role],
            "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
            "structured_output_schema_sha256": (
                judge_contract.structured_output_schema_sha256(role)),
            "final_response_contract_sha256": (
                judge_contract.final_response_contract_sha256(role)),
            "judge_prompt_sha256": judge_prompt_sha256,
            "quality_rubric_sha256": quality_rubric_sha256,
            "config_digest": config_digest(config),
        }

    def v2_refuse_terminal_invalid(doc, slot):
        invalid_path = v2_invalid_path(slot)
        terminal = load_json_object(
            invalid_path, "terminal-invalid judge record")
        expected = v2_terminal_core(doc, slot)
        allowed_kinds = {
            "ambiguous_post_launch",
            "invalid_attempt_history",
        }
        if (any(terminal.get(key) != value
                for key, value in expected.items())
                or terminal.get("kind") not in allowed_kinds
                or not isinstance(terminal.get("evidence"), list)):
            raise InfraFailure(
                f"terminal-invalid judge record for slot {slot} is "
                f"corrupted; the batch remains invalid"
            )
        detail = ("ambiguous post-launch state"
                  if terminal["kind"] == "ambiguous_post_launch"
                  else terminal["kind"])
        raise InfraFailure(
            f"protocol v2 judge slot {slot} is terminally invalid "
            f"({detail}); this batch cannot be "
            f"resumed — create a fresh seal and scoring batch"
        )

    def v2_terminally_invalidate(doc, slot, kind, evidence_paths):
        invalid_path = v2_invalid_path(slot)
        if _path_present(invalid_path):
            v2_refuse_terminal_invalid(doc, slot)
        evidence = [
            _evidence_descriptor(evidence_path)
            for evidence_path in sorted(evidence_paths, key=lambda p: p.name)
        ]
        terminal = {
            **v2_terminal_core(doc, slot),
            "kind": kind,
            "evidence": evidence,
        }
        atomic_write_text(invalid_path,
                          json.dumps(terminal, indent=2) + "\n")
        write_scoring_manifest(False)
        v2_refuse_terminal_invalid(doc, slot)

    def v2_exhaust(doc, slot, records):
        exhausted_path = out / f"judge-{scoring_id}-{slot}-exhausted.json"
        terminal = {
            "doc": str(doc),
            "scoring_id": scoring_id,
            "presentation_index": slot,
            "role": role,
            "axis": "all-docs",
            "protocol_version": PILOT_V2_PROTOCOL_VERSION,
            "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
            "response_schema_version": judge_contract.RESPONSE_SCHEMA_VERSION,
            "schema_sha256": v2_schema_digests[role],
            "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
            "structured_output_schema_sha256": (
                judge_contract.structured_output_schema_sha256(role)),
            "final_response_contract_sha256": (
                judge_contract.final_response_contract_sha256(role)),
            "judge_prompt_sha256": judge_prompt_sha256,
            "quality_rubric_sha256": quality_rubric_sha256,
            "max_attempts": PILOT_V2_MAX_JUDGE_ATTEMPTS,
            "attempt_response_sha256": [
                record["response_sha256"] for record in records],
            "status": "exhausted",
        }
        if exhausted_path.exists():
            if load_json_object(
                    exhausted_path, "judge exhaustion record") != terminal:
                raise InfraFailure(
                    f"judge exhaustion record for slot {slot} is corrupted")
        else:
            atomic_write_text(exhausted_path,
                              json.dumps(terminal, indent=2) + "\n")
        write_scoring_manifest(False)
        raise InfraFailure(
            f"protocol v2 judge attempts exhausted for slot {slot}; this "
            f"terminal batch failure cannot be reset on resume"
        )

    def prepare_v1_judge_workspace(doc, ev_repo, ev_sha):
        """Create one legacy judge workspace with fail-safe setup cleanup.

        The paths remain in the judge record as freshness/placement
        evidence, but the temporary filesystem state must not survive the
        session.  Setup is kept in a helper so every exception between
        ``mkdtemp`` and the backend launch removes both the registered git
        worktree (when present) and its enclosing temporary root.
        """
        judge_root = Path(tempfile.mkdtemp(prefix="rpa-judge-"))
        workdir = None
        judge_settings = (
            VERIFIER_SETTINGS if ev_repo else JUDGE_SETTINGS)
        try:
            if ev_repo:
                profile, _ = make_profile(
                    judge_root, "judge", settings=judge_settings)
                workdir = make_worktree(ev_repo, ev_sha, judge_root)
                if Path(doc).name in snapshot_by_doc:
                    # Seal-verified frozen snapshots are placed INSIDE the
                    # confined workdir so the sandboxed verifier can read
                    # them. Directory layout is preserved and seal keys
                    # are package-relative, so same-named files in
                    # different subdirectories never overwrite each other.
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
                profile, _ = make_profile(
                    judge_root, "judge", settings=judge_settings)
                workdir = judge_root / "workdir"
                workdir.mkdir()
            env = backend_env(profile)
            sandboxed_cmd = apply_sandbox(
                config, with_stream_json_transport(judge_cmd), workdir,
                profile)
            # JSON round-tripping makes the audit snapshot independent of
            # the mutable module-level settings dictionaries.
            settings_snapshot = json.loads(json.dumps(judge_settings))
            return (judge_root, profile, workdir, env, sandboxed_cmd,
                    settings_snapshot)
        except BaseException:
            if ev_repo and workdir is not None:
                remove_worktree(ev_repo, workdir)
            shutil.rmtree(judge_root, ignore_errors=True)
            raise

    def v2_validate_complete_scorer_counterpart():
        """Recompute the scorer batch before verifier launch.

        Protocol v2 deliberately sequences the two independent judge roles:
        the scorer completes first; only then may a fresh verifier session
        begin.  This prevents an incomplete/corrupt counterpart namespace
        from becoming meaningful only after verifier observations exist.
        """
        counterpart_path = out / "scoring-scorer-all-docs-manifest.json"
        if not _safe_regular_file(counterpart_path):
            raise InfraFailure(
                "verifier requires a complete regular-file scorer manifest")
        counterpart = load_json_object(
            counterpart_path, "scorer counterpart manifest")
        if (set(counterpart) != {"scoring_id", "identity", "results",
                                 "complete"}
                or counterpart.get("complete") is not True):
            raise InfraFailure(
                "verifier requires a complete structurally valid scorer batch")
        counterpart_id = counterpart.get("scoring_id")
        if (not isinstance(counterpart_id, str)
                or re.fullmatch(r"[0-9a-f]{8}", counterpart_id) is None
                or counterpart_id == scoring_id):
            raise InfraFailure("scorer counterpart has an invalid batch id")
        identity = counterpart.get("identity")
        if (not isinstance(identity, dict)
                or set(identity) != set(batch_identity)
                or identity.get("role") != "scorer"
                or identity.get("axis") != "all-docs"
                or identity.get("protocol_version")
                != PILOT_V2_PROTOCOL_VERSION
                or identity.get("environment_policy_id")
                != PILOT_V2_ENVIRONMENT_POLICY_ID
                or identity.get("response_schema_version")
                != judge_contract.RESPONSE_SCHEMA_VERSION
                or identity.get("schema_sha256")
                != v2_schema_digests["scorer"]
                or identity.get("judge_output_policy")
                != PILOT_V2_JUDGE_OUTPUT_POLICY
                or identity.get("structured_output_schema_sha256")
                != judge_contract.structured_output_schema_sha256("scorer")
                or identity.get("final_response_contract_sha256")
                != judge_contract.final_response_contract_sha256("scorer")
                or identity.get("judge_prompt_sha256")
                != seal_files.get(
                    seal_doc.get("judge_prompts", {}).get("scorer"))
                or identity.get("quality_rubric_sha256")
                != quality_rubric_sha256
                or identity.get("config_digest") != config_digest(config)
                or identity.get("manifest") != str(manifest_path)
                or identity.get("docs") != batch_identity["docs"]
                or identity.get("drift_decisions")
                != batch_identity["drift_decisions"]
                or identity.get("scoring_seed")
                != PILOT_V2_SCORER_SEED):
            raise InfraFailure("scorer counterpart identity is invalid")
        counterpart_seed = identity["scoring_seed"]
        counterpart_results = counterpart.get("results")
        if (not isinstance(counterpart_results, list)
                or len(counterpart_results) != len(doc_paths)):
            raise InfraFailure(
                "scorer counterpart does not cover the complete population")

        counterpart_order = list(range(len(doc_paths)))
        random.Random(counterpart_seed).shuffle(counterpart_order)
        allowed_material = set()
        seen_profiles = set()
        seen_sessions = set()
        for slot, doc_index in enumerate(counterpart_order):
            doc = doc_paths[doc_index]
            doc_name = Path(doc).name
            result = counterpart_results[slot]
            canonical_path = out / f"judge-{counterpart_id}-{slot}.json"
            if not isinstance(result, dict) or not _safe_regular_file(
                    canonical_path):
                raise InfraFailure(
                    "scorer counterpart has a missing canonical record")
            canonical = load_json_object(
                canonical_path, "scorer counterpart canonical record")
            if canonical != result:
                raise InfraFailure(
                    "scorer counterpart manifest differs from its canonical "
                    "record")
            allowed_material.add(canonical_path.name)
            if (result.get("presentation_index") != slot
                    or result.get("doc") != str(doc)
                    or result.get("role") != "scorer"
                    or result.get("axis") != "all-docs"
                    or result.get("protocol_version")
                    != PILOT_V2_PROTOCOL_VERSION
                    or result.get("environment_policy_id")
                    != PILOT_V2_ENVIRONMENT_POLICY_ID
                    or result.get("response_schema_version")
                    != judge_contract.RESPONSE_SCHEMA_VERSION
                    or result.get("schema_sha256")
                    != v2_schema_digests["scorer"]
                    or result.get("judge_output_policy")
                    != PILOT_V2_JUDGE_OUTPUT_POLICY
                    or result.get("structured_output_schema_sha256")
                    != judge_contract.structured_output_schema_sha256(
                        "scorer")
                    or result.get("final_response_contract_sha256")
                    != judge_contract.final_response_contract_sha256(
                        "scorer")
                    or result.get("judge_prompt_sha256")
                    != identity["judge_prompt_sha256"]
                    or result.get("quality_rubric_sha256")
                    != quality_rubric_sha256
                    or result.get("scoring_seed") != counterpart_seed
                    or result.get("scheduled") is not True
                    or result.get("task") != task_by_doc.get(doc_name)
                    or result.get("source_drift")
                    != drift_notes.get(doc_name)):
                raise InfraFailure(
                    "scorer counterpart canonical binding is invalid")

            attempt_material = sorted(out.glob(
                f"judge-{counterpart_id}-{slot}-attempt-*"),
                key=lambda path: path.name)
            if result.get("inconclusive") is True:
                if (doc_name not in inconclusive_docs or attempt_material
                        or _path_present(out / (
                            f"judge-{counterpart_id}-{slot}-exhausted.json"))
                        or _path_present(out / (
                            f"judge-{counterpart_id}-{slot}-"
                            "terminal-invalid.json"))):
                    raise InfraFailure(
                        "scorer counterpart inconclusive slot is invalid")
                continue

            attempt = result.get("attempt")
            if (not isinstance(attempt, int) or isinstance(attempt, bool)
                    or not 1 <= attempt <= PILOT_V2_MAX_JUDGE_ATTEMPTS):
                raise InfraFailure(
                    "scorer counterpart accepted attempt is invalid")
            accepted = None
            for attempt_number in range(1, attempt + 1):
                attempt_path = out / (
                    f"judge-{counterpart_id}-{slot}-attempt-"
                    f"{attempt_number}.json")
                pending_path = out / (
                    f"judge-{counterpart_id}-{slot}-attempt-"
                    f"{attempt_number}.pending")
                if (not _safe_regular_file(attempt_path)
                        or _path_present(pending_path)):
                    raise InfraFailure(
                        "scorer counterpart attempt history is incomplete")
                attempt_record = load_json_object(
                    attempt_path, "scorer counterpart attempt record")
                expected = v2_attempt_expected_for(
                    "scorer", counterpart_id, counterpart_seed,
                    doc, slot, attempt_number)
                valid = _validate_v2_attempt_record(attempt_record, expected)
                if valid is (attempt_number < attempt):
                    raise InfraFailure(
                        "scorer counterpart attempts continue after a valid "
                        "response or accept an invalid response")
                allowed_material.add(attempt_path.name)
                if attempt_record.get("raw_stream_external") is True:
                    sidecar_path = Path(attempt_record["raw_stream_sidecar"])
                    allowed_material.add(sidecar_path.name)
                profile = attempt_record.get("profile")
                session = attempt_record.get("session_id")
                if (not isinstance(profile, str) or not profile
                        or profile in seen_profiles
                        or isinstance(session, str) and session
                        and session in seen_sessions):
                    raise InfraFailure(
                        "scorer counterpart did not use fresh isolation")
                seen_profiles.add(profile)
                if isinstance(session, str) and session:
                    seen_sessions.add(session)
                accepted = attempt_record
            if accepted != result:
                raise InfraFailure(
                    "scorer counterpart canonical record is not its first "
                    "valid contiguous attempt")
            if (_path_present(out / (
                    f"judge-{counterpart_id}-{slot}-exhausted.json"))
                    or _path_present(out / (
                        f"judge-{counterpart_id}-{slot}-"
                        "terminal-invalid.json"))):
                raise InfraFailure(
                    "scorer counterpart retains terminal failure material")
        discovered = {
            path.name for path in out.glob(f"judge-{counterpart_id}-*")
        }
        if discovered != allowed_material or any(
                not _safe_regular_file(out / name)
                for name in discovered):
            raise InfraFailure(
                "scorer counterpart contains foreign judge material")
        return counterpart_id

    if v2:
        if v2_batch_invalid_path().exists():
            v2_refuse_batch_invalid()
        v2_audit_scoring_namespace()
        registered_ids = {scoring_id}
        if role == "verifier":
            try:
                registered_ids.add(v2_validate_complete_scorer_counterpart())
            except (InfraFailure, OSError, ValueError, TypeError, KeyError):
                v2_terminally_invalidate_batch([
                    out / "scoring-scorer-all-docs-manifest.json",
                ])
        current_material = v2_audit_judge_namespace(registered_ids)
        next_slot = len(results)
        future_material = [
            path for slot, paths in current_material.items()
            if slot > next_slot for path in paths
        ]
        if future_material:
            v2_terminally_invalidate_batch(future_material)

    for i, doc_index in enumerate(order):
        verify_output_directory(
            out, output_binding, "scoring output directory")
        if v2:
            doc, doc_text = doc_paths[doc_index], doc_texts[doc_index]
            canonical_path = out / f"judge-{scoring_id}-{i}.json"
            if v2_invalid_path(i).exists():
                v2_refuse_terminal_invalid(doc, i)
            exhausted_path = out / (
                f"judge-{scoring_id}-{i}-exhausted.json")
            if exhausted_path.exists():
                raise InfraFailure(
                    f"protocol v2 judge attempts already exhausted for "
                    f"slot {i}; terminal batch failure cannot be reset"
                )
            if Path(doc).name in inconclusive_docs:
                attempt_material = list(out.glob(
                    f"judge-{scoring_id}-{i}-attempt-*"))
                if attempt_material:
                    v2_terminally_invalidate(
                        doc, i, "invalid_attempt_history", attempt_material)
                result = {
                    "doc": str(doc),
                    "inconclusive": True,
                    "reason": ("external source drift — task inconclusive "
                               "per the registered protocol"),
                    "source_drift": drift_notes.get(Path(doc).name),
                    "task": (task_by_doc.get(Path(doc).name)
                             if task_by_doc is not None else None),
                    "scoring_seed": scoring_seed,
                    "presentation_index": i,
                    "scheduled": manifest_path is not None,
                    "role": role,
                    "axis": "all-docs",
                    "protocol_version": PILOT_V2_PROTOCOL_VERSION,
                    "environment_policy_id": PILOT_V2_ENVIRONMENT_POLICY_ID,
                    "response_schema_version": (
                        judge_contract.RESPONSE_SCHEMA_VERSION),
                    "schema_sha256": v2_schema_digests[role],
                    "judge_output_policy": PILOT_V2_JUDGE_OUTPUT_POLICY,
                    "structured_output_schema_sha256": (
                        judge_contract.structured_output_schema_sha256(role)),
                    "final_response_contract_sha256": (
                        judge_contract.final_response_contract_sha256(role)),
                    "judge_prompt_sha256": judge_prompt_sha256,
                    "quality_rubric_sha256": quality_rubric_sha256,
                }
                if canonical_path.exists():
                    try:
                        canonical = load_json_object(
                            canonical_path, "inconclusive judge record")
                    except InfraFailure:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path])
                    if canonical != result:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path])
                else:
                    atomic_write_text(canonical_path,
                                      json.dumps(result, indent=2) + "\n")
                if i < len(results):
                    if results[i] != result:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path])
                else:
                    results.append(result)
                    write_scoring_manifest(False)
                continue

            valid_attempt, first_missing, attempt_records = (
                v2_scan_attempts(doc, i))
            if valid_attempt is not None:
                if canonical_path.exists():
                    try:
                        canonical = load_json_object(
                            canonical_path, "canonical judge record")
                    except InfraFailure:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path, *v2_attempt_material(i)])
                    if canonical != valid_attempt:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path, *v2_attempt_material(i)])
                else:
                    atomic_write_text(
                        canonical_path,
                        json.dumps(valid_attempt, indent=2) + "\n")
                if i < len(results):
                    if results[i] != valid_attempt:
                        v2_terminally_invalidate(
                            doc, i, "invalid_attempt_history",
                            [canonical_path, *v2_attempt_material(i)])
                else:
                    results.append(valid_attempt)
                    write_scoring_manifest(False)
                continue
            if canonical_path.exists():
                v2_terminally_invalidate(
                    doc, i, "invalid_attempt_history",
                    [canonical_path, *v2_attempt_material(i)])
            if i < len(results):
                v2_terminally_invalidate(
                    doc, i, "invalid_attempt_history",
                    [scoring_manifest_path, *v2_attempt_material(i)])
            next_attempt = first_missing or (
                PILOT_V2_MAX_JUDGE_ATTEMPTS + 1)
            if next_attempt > PILOT_V2_MAX_JUDGE_ATTEMPTS:
                v2_exhaust(doc, i, attempt_records)
            if doc_evidence is not None:
                ev_repo, ev_sha = doc_evidence[Path(doc).name]
            else:
                ev_repo, ev_sha = evidence_repo, evidence_sha
            for attempt in range(
                    next_attempt, PILOT_V2_MAX_JUDGE_ATTEMPTS + 1):
                attempt_record = v2_launch_attempt(
                    doc, doc_text, i, attempt, ev_repo, ev_sha)
                attempt_records.append(attempt_record)
                if attempt_record["validation"]["valid"]:
                    atomic_write_text(
                        canonical_path,
                        json.dumps(attempt_record, indent=2) + "\n")
                    results.append(attempt_record)
                    write_scoring_manifest(False)
                    break
            else:
                v2_exhaust(doc, i, attempt_records)
            continue

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
            durable_unlink(
                out / f"judge-{scoring_id}-{i}.pending", missing_ok=True)
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
            (judge_root, profile, workdir, env, sandboxed_cmd,
             judge_settings) = prepare_v1_judge_workspace(
                 doc, ev_repo, ev_sha)
        except BaseException:
            # Workspace preparation happens before the backend can launch;
            # retiring this journal cannot authorize a duplicate session.
            durable_unlink(pending_path, missing_ok=True)
            raise
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
                shutil.rmtree(judge_root, ignore_errors=True)
        except InfraFailure:
            durable_unlink(pending_path, missing_ok=True)
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
            durable_unlink(pending_path, missing_ok=True)
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
            "judge_settings": judge_settings,
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
        durable_unlink(pending_path, missing_ok=True)
    judged = [r for r in results if not r.get("inconclusive")]
    judged_sessions = [r.get("session_id") for r in judged]
    judged_profiles = [r.get("profile") for r in judged]
    if (any(not isinstance(value, str) or not value
            for value in judged_sessions + judged_profiles)
            or len(set(judged_sessions)) != len(judged_sessions)
            or len(set(judged_profiles)) != len(judged_profiles)):
        raise InfraFailure("judge sessions were not fresh/isolated")
    if v2:
        v2_audit_scoring_namespace()
        v2_audit_judge_namespace(registered_ids)
        attempts = [
            load_json_object(path, "judge attempt record")
            for path in sorted(out.glob(
                f"judge-{scoring_id}-*-attempt-*.json"))
        ]
        attempt_profiles = [r.get("profile") for r in attempts]
        if (any(not profile for profile in attempt_profiles)
                or len(set(attempt_profiles)) != len(attempt_profiles)):
            raise InfraFailure(
                "protocol v2 judge attempts did not use fresh profiles")
        attempt_sessions = [r.get("session_id") for r in attempts
                            if isinstance(r.get("session_id"), str)
                            and r.get("session_id")]
        if len(set(attempt_sessions)) != len(attempt_sessions):
            raise InfraFailure(
                "protocol v2 judge attempts reused a backend session")
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
    parser.add_argument(
        "--docs", nargs="*",
        help="documents to score; protocol-v2 manifest batches may pass an "
             "explicit empty population, while v1/unscheduled scoring may not")
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
                        help="historical protocol-v1 score mode: explicitly "
                             "allow ad-hoc/dev scoring without a schedule "
                             "manifest; protocol v2 always refuses it")
    parser.add_argument("--diagnostic-axis", action="store_true",
                        help="historical protocol-v1 score mode with "
                             "--manifest: the registered "
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
                        help="manifest-bound score mode: TASKFILE=PATH "
                             "mapping to sealed frozen external-source "
                             "snapshots for external-context tasks; both "
                             "judge roles apply the same drift gate")
    parser.add_argument("--drift-report",
                        help="score mode: JSON drift report from the "
                             "pre-score re-fetch of sealed external "
                             "sources ({taskfile: {changed: {seal_key: "
                             "{observed_sha256: hex, material: bool, "
                             "rationale: str}}}}); each adjudication is "
                             "bound to the exact live bytes; "
                             "materially drifted tasks are recorded "
                             "inconclusive, never judged")
    parser.add_argument("--output", default="runs", help="output directory")
    parser.add_argument("--make-schedule", action="store_true",
                        help="write a pre-registered randomized schedule "
                             "(requires --config, --tasks, --seed)")
    parser.add_argument("--tasks", nargs="+",
                        help="registered task files for --make-schedule, "
                             "--run-schedule, or manifest-bound --score")
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
                             "(requires --config, --repos, and --tasks)")
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
        try:
            atomic_write_text(
                args.schedule_out, json.dumps(schedule, indent=2) + "\n")
        except (InfraFailure, OSError) as exc:
            print(json.dumps({
                "status": "infra_failure",
                "failure": f"cannot safely write schedule: {exc}",
            }))
            sys.exit(1)
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
        if not (args.config and args.docs is not None and args.judge_prompt):
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
            if (not args.docs and not (
                    config.get("protocol_version")
                    == PILOT_V2_PROTOCOL_VERSION and args.manifest)):
                parser.error(
                    "an empty --docs population is valid only for "
                    "manifest-bound protocol-v2 scoring")
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
