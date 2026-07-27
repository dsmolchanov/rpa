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

The backend command is configurable (`backend_cmd`); production uses the
`claude` CLI in headless mode, while `--preflight` uses the bundled
deterministic `mock_claude.py`. A real-backend preflight on the throwaway
task is still required once before baseline runs (see the pilot plan).

Stdlib only.
"""

import argparse
import hashlib
import json
import random
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

MAX_CONTINUATIONS = 3
DEFAULT_MAX_INFRA_RETRIES = 2
# The pilot protocol fixes the replicate count and the holdout size;
# schedules that deviate must be explicitly marked nonstandard (dev-set
# tuning only, never holdout).
REGISTERED_REPLICATES = 3
REGISTERED_HOLDOUT_TASKS = 6
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
# pinned sha — never the experiment output tree.
VERIFIER_SETTINGS = {
    "permissions": {
        "deny": ["Bash", "Write", "Edit", "NotebookEdit",
                 "WebFetch", "WebSearch", "Task"]
    }
}


def hash_tree(root):
    """Deterministic SHA-256 of a directory tree: sorted relative POSIX
    paths, each followed by NUL + content + NUL."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8")
    ).hexdigest()


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
        mount = profile / "plugins" / label
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


def extract_task_prompt(task_path):
    """Only the `## Task prompt` section may reach an evaluated session.
    The marker is required unconditionally: a malformed task must fail the
    run, never silently alter the experiment by sending the whole file."""
    text = Path(task_path).read_text(encoding="utf-8")
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


def resolve_repo(task_path, repos):
    """The registered holdout spans several repositories: each task names
    its `target-repo` and the operator supplies a NAME=PATH clone mapping;
    one clone can never serve a multi-repo schedule."""
    text = Path(task_path).read_text(encoding="utf-8")
    name = task_target_repo(text, task_path)
    if name not in repos:
        raise InfraFailure(
            f"{task_path}: target-repo `{name}` has no registered clone — "
            f"supply it as {name}=/path/to/clone"
        )
    return repos[name]


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


def make_worktree(repo_dir, sha, workspace):
    """Disposable detached worktree at the pinned SHA, verified. The
    destination is resolved to an absolute path BEFORE reaching git:
    `git -C <repo>` resolves relative destinations under the repo while the
    caller would resolve them under its own cwd — two different places."""
    dest = (Path(workspace) / "worktrees" / uuid.uuid4().hex[:12]).resolve()
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
        proc = subprocess.run(
            full, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        raise WorkflowFailure(
            f"session timed out after {timeout}s", stdout=partial
        ) from exc
    except OSError as exc:
        raise InfraFailure(f"backend could not be spawned: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip()[:500]
        if proc.returncode in workflow_abort_exits:
            # Counted experimental outcome: keep the partial transcript so
            # the failed run's tree-wide accounting survives.
            raise WorkflowFailure(
                f"workflow aborted (exit {proc.returncode}): {detail}",
                stdout=proc.stdout,
            )
        raise InfraFailure(f"backend exited {proc.returncode}: {detail}")
    return proc.stdout


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
        }
    if event.get("type") == "assistant" and isinstance(event.get("message"), dict):
        message = event["message"]
        usage = message.get("usage") or {}
        content = message.get("content") or []
        tool_calls = sum(
            1 for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
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
    totals["subagents_spawned"] = len(distinct) + anonymous
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
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                for j in range(1, idx):
                    key = lines[j].split(":", 1)[0].strip().lower()
                    if key in FINGERPRINT_KEYS:
                        lines[j] = f"{key}: '[anonymized:{run_id}]'"
                break
    body = "\n".join(lines)
    body = re.sub(
        r"^\*\*(Date|Researcher|Git Commit|Branch)\*\*:.*$",
        lambda m: f"**{m.group(1)}**: [anonymized:{run_id}]",
        body,
        flags=re.MULTILINE,
    )
    return body + ("\n" if not body.endswith("\n") else "")


def run_task(config, arm_name, task_path, repo_dir, output_dir, attempt=1):
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
    started = None
    try:
        validate_arm_parity(config)
        record["standard_topology"] = validate_arm_topology(config)
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
        worktree = make_worktree(repo_dir, sha, output_dir)
        record["target_sha"] = sha
        record["worktree"] = str(worktree)
        profile, mount = make_profile(output_dir, arm_name, arm["installation_dir"])
        mount_hash = hash_tree(mount)
        if mount_hash != arm["sha256"]:
            raise InfraFailure("mounted installation copy hash mismatch")
        require_effort_pin(config["backend_cmd"], "backend_cmd")
        require_installation_mount(config["backend_cmd"])
        cmd = expand_backend_cmd(config["backend_cmd"], mount,
                                 arm.get("effort", "default"))
        env = backend_env(profile)
        abort_exits = tuple(config.get("workflow_abort_exit_codes", ()))
        before = snapshot_research(worktree)
        effort_modes = set()
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
                if partial:
                    validate_models(partial, arm["model"])
                    effort_modes.add(
                        validate_efforts(partial, arm.get("effort", "default")))
                    all_nodes.extend(partial)
                elif not all_nodes:
                    # A counted failure needs effective-runtime evidence from
                    # SOME session of this run; a completely empty transcript
                    # proves nothing and must invalidate, not count.
                    raise InfraFailure(
                        f"workflow failure with no accounting nodes in any "
                        f"session — no effective-runtime parity evidence; "
                        f"run invalidated ({wf})"
                    ) from wf
                raise

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
        if artifact is None:
            raise WorkflowFailure(
                f"no fresh research artifact after {MAX_CONTINUATIONS} continuations"
            )
        raw = artifact.read_text(encoding="utf-8")
        (out / f"run-{run_id}-raw.md").write_text(raw, encoding="utf-8")
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
        if started is not None and "wall_seconds" not in record:
            record["wall_seconds"] = round(time.time() - started, 3)
        if worktree is not None:
            remove_worktree(repo_dir, worktree)
    (out / f"run-{run_id}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def run_task_with_retries(config, arm_name, task_path, repo_dir, output_dir):
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
                          attempt=attempt)
        attempts.append(record)
        if record["status"] != "infra_failure":
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
    tasks = [str(Path(t)) for t in task_paths]
    if len(set(tasks)) != len(tasks):
        raise InfraFailure("duplicate task paths in the schedule task list")
    standard_topology = _standard_topology(config)
    if not allow_nonstandard:
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
    # The schedule binds task CONTENTS, not just paths: an edited prompt or
    # re-pinned target-sha after registration must break reconstruction,
    # never silently mix revisions inside one experimental cell.
    task_digests = {}
    for task in tasks:
        try:
            task_digests[task] = hashlib.sha256(
                Path(task).read_bytes()
            ).hexdigest()
        except OSError as exc:
            raise InfraFailure(f"cannot read task file {task}: {exc}") from exc
    rng = random.Random(seed)
    rng.shuffle(entries)
    for index, entry in enumerate(entries):
        entry["index"] = index
    return {
        "seed": seed,
        "replicates": replicates,
        "task_digests": task_digests,
        "nonstandard": (replicates != REGISTERED_REPLICATES
                        or not standard_topology
                        or len(tasks) != REGISTERED_HOLDOUT_TASKS),
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
    schedule = json.loads(Path(schedule_path).read_text(encoding="utf-8"))
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
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        if len(results) > len(entries):
            raise InfraFailure("existing manifest is longer than the schedule")
        for done, entry in zip(results, entries):
            if (done.get("index"), done.get("arm"), done.get("task")) != (
                    entry["index"], entry["arm"], entry["task"]):
                raise InfraFailure(
                    "existing manifest does not match the schedule prefix"
                )

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
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return manifest

    for entry in entries[len(results):]:
        # The registered holdout spans several repositories: each task is
        # routed to the clone registered for its own `target-repo`.
        entry_repo = resolve_repo(entry["task"], repos)
        attempts = run_task_with_retries(
            config, entry["arm"], entry["task"], entry_repo, output_dir
        )
        final = attempts[-1]
        if final["status"] == "infra_failure":
            # Entry unfinished: persist progress so a re-run resumes HERE.
            write_manifest(False)
            raise InfraFailure(
                f"schedule interrupted at entry {entry['index']} "
                f"({entry['arm']} / {entry['task']}): infra retries "
                f"exhausted; progress persisted — re-run --run-schedule to "
                f"resume at this entry"
            )
        results.append({
            "index": entry["index"],
            "arm": entry["arm"],
            "task": entry["task"],
            "run_id": final["run_id"],
            "status": final["status"],
            "attempts": len(attempts),
            "artifact_sha256": final.get("artifact_sha256"),
            "task_sha256": schedule["task_digests"][entry["task"]],
        })
        write_manifest(False)
    return write_manifest(True)


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
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                break
            key = lines[idx].split(":", 1)[0].strip().lower()
            if key in FINGERPRINT_KEYS and "[anonymized:" not in lines[idx]:
                raise InfraFailure(
                    f"{doc_path}: fingerprint key `{key}` is not anonymized "
                    f"— blind scoring refused"
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
          manifest_path=None, allow_unscheduled=False, evidence_repos=None):
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
    doc_evidence = None
    if manifest_path is not None:
        # No post-hoc selection: the supplied documents must cover every
        # completed scheduled replicate exactly once — no subsets, no
        # duplicates, no extras.
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not manifest.get("complete"):
            raise InfraFailure(
                "schedule manifest is incomplete — score only after the "
                "whole schedule has run"
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
        for r in completed:
            recorded_task = r.get("task_sha256")
            if recorded_task is not None:
                actual_task = hashlib.sha256(
                    Path(r["task"]).read_bytes()
                ).hexdigest()
                if actual_task != recorded_task:
                    raise InfraFailure(
                        f"{r['task']}: task file changed since the "
                        f"scheduled run — evidence selection and protocol "
                        f"binding would use a different task"
                    )
        expected_names = sorted(f"run-{r['run_id']}-anon.md" for r in completed)
        supplied_names = sorted(Path(d).name for d in doc_paths)
        if supplied_names != expected_names:
            raise InfraFailure(
                f"scoring inputs must cover every completed scheduled "
                f"replicate exactly once — expected {expected_names}, "
                f"got {supplied_names}"
            )
        # Identity by name is not enough: the contents must be the exact
        # artifact the run produced, or an edited/substituted file with the
        # right name would be scored as that replicate.
        digest_by_name = {f"run-{r['run_id']}-anon.md": r.get("artifact_sha256")
                          for r in completed}
        for doc in doc_paths:
            actual = hashlib.sha256(Path(doc).read_bytes()).hexdigest()
            if actual != digest_by_name.get(Path(doc).name):
                raise InfraFailure(
                    f"{doc}: contents differ from the artifact digest "
                    f"recorded at run time — scored documents must be the "
                    f"exact run artifacts"
                )
        if evidence_repo or evidence_sha:
            raise InfraFailure(
                "manifest-bound verification checks each document against "
                "ITS OWN task's pinned repo@sha — pass `evidence_repos` "
                "(NAME=PATH mapping), not a single evidence repo/sha"
            )
        if evidence_repos is not None:
            # A holdout batch spans several target repositories: every
            # document is verified against the worktree of its own task's
            # pinned repo@sha, never one shared checkout.
            doc_evidence = {}
            for r in completed:
                task_text = Path(r["task"]).read_text(encoding="utf-8")
                repo_name = task_target_repo(task_text, r["task"])
                if repo_name not in evidence_repos:
                    raise InfraFailure(
                        f"{r['task']}: target-repo `{repo_name}` has no "
                        f"registered evidence clone — supply it as "
                        f"{repo_name}=/path/to/frozen-clone"
                    )
                doc_evidence[f"run-{r['run_id']}-anon.md"] = (
                    evidence_repos[repo_name],
                    task_target_sha(task_text, r["task"]),
                )
    elif evidence_repos is not None:
        raise InfraFailure(
            "`evidence_repos` requires manifest-bound scoring — for "
            "unscheduled verification use evidence_repo/evidence_sha"
        )
    judge_prompt = Path(judge_prompt_path).read_text(encoding="utf-8")
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
    require_effort_pin(judge_cmd, "judge command")
    judge_cmd = expand_backend_cmd(judge_cmd, None, judge_effort)
    doc_texts = [assert_blind_scorable(doc) for doc in doc_paths]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Unique per-invocation id: separate scorer and verifier passes into the
    # same output directory must never overwrite each other's judge files.
    scoring_id = uuid.uuid4().hex[:8]
    results = []
    role = "verifier" if (evidence_repo or doc_evidence is not None) else "scorer"
    order = list(range(len(doc_paths)))
    random.Random(scoring_seed).shuffle(order)
    for i, doc_index in enumerate(order):
        doc, doc_text = doc_paths[doc_index], doc_texts[doc_index]
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
        else:
            profile, _ = make_profile(judge_root, "judge",
                                      settings=JUDGE_SETTINGS)
            workdir = judge_root / "workdir"
            workdir.mkdir()
        env = backend_env(profile)
        prompt = judge_prompt + "\n\n---\n\n" + doc_text
        try:
            stdout = spawn_session(
                judge_cmd, prompt, str(workdir), env, config["timeout_seconds"]
            )
        finally:
            if ev_repo:
                remove_worktree(ev_repo, workdir)
        session_id, nodes, response = parse_transcript(stdout)
        if not response.strip():
            raise InfraFailure(f"judge session {session_id} returned no response text")
        validate_models(nodes, judge_model)
        effort_capture = validate_efforts(nodes, judge_effort)
        result = {
            "doc": str(doc),
            "session_id": session_id,
            "profile": str(profile),
            "cwd": str(workdir),
            "role": role,
            "backend_version": backend_version,
            "scoring_seed": scoring_seed,
            "presentation_index": i,
            "scheduled": manifest_path is not None,
            "judge_model": judge_model,
            "effort_capture": effort_capture,
            "response": response,
            "accounting": account(nodes),
        }
        if ev_repo:
            result["evidence_sha"] = ev_sha
        (out / f"judge-{scoring_id}-{i}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        results.append(result)
    if len({r["session_id"] for r in results}) != len(results) or len(
        {r["profile"] for r in results}
    ) != len(results):
        raise InfraFailure("judge sessions were not fresh/isolated")
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
        config = load_config(args.config)
        try:
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
        config = load_config(args.config)
        try:
            evidence_repos = (parse_repo_mapping(args.evidence_repos,
                                                 "--evidence-repos")
                              if args.evidence_repos else None)
        except InfraFailure as exc:
            print(json.dumps({"status": "infra_failure", "failure": str(exc)}))
            sys.exit(1)
        results = score(config, args.docs, args.judge_prompt, args.output,
                        evidence_repo=args.evidence_repo,
                        evidence_sha=args.evidence_sha,
                        scoring_seed=args.scoring_seed,
                        manifest_path=args.manifest,
                        allow_unscheduled=args.unscheduled_docs,
                        evidence_repos=evidence_repos)
        print(json.dumps([{k: r[k] for k in ("doc", "session_id")} for r in results]))
        sys.exit(0)

    if not (args.config and args.arm and args.task and args.repo):
        parser.error("run mode requires --config, --arm, --task, --repo")
    config = load_config(args.config)
    try:
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
