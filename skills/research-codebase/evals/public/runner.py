#!/usr/bin/env python3
"""Eval-runner harness for the /research_codebase modernization pilot.

Implements prerequisite 5 of
`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`.
Capability map (each proven by `--preflight` before any scored run):

  1. installation-hash verification  — every run starts by hashing the arm's
     installation tree and comparing against the registered SHA-256.
  2. per-node model/effort capture   — every transcript node records its
     model; the session-level effort comes from the pinned configuration and
     the harness-reported model of every node is validated against the
     registered model (mismatch invalidates the run).
  3. clean profile                   — each run uses a runner-created
     CLAUDE_CONFIG_DIR containing only the arm's installation; ambient
     personal skills/config are never on the load path.
  4. infra vs workflow failure       — backend crashes / unparseable output
     are `infra_failure` (run invalid, re-executed); timeouts and
     missing-artifact completions are `workflow_failure` (counted per the
     failed-run rule, never replaced).
  5. tree-wide accounting            — tokens and tool calls are summed over
     every transcript node, reported as main-context and subagent subtotals.
  6. anonymization                   — scored copies carry a random run id
     and masked fingerprint frontmatter (researcher, git commit, branch,
     dates).
  7. fresh pinned judge sessions     — `score` spawns each scorer/verifier
     call as a new backend session in its own fresh profile directory.

The backend command is configurable (`backend_cmd`); production uses the
`claude` CLI in headless mode, while `--preflight` uses the bundled
deterministic `mock_claude.py`, so the harness mechanics are provable
offline and in CI. A real-backend preflight on the throwaway task is still
required before baseline runs (see the pilot plan).

Stdlib only — no dependencies beyond those already registered for the docs
gate (this script itself uses none).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

MAX_CONTINUATIONS = 3
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


class InfraFailure(Exception):
    """Harness/environment fault: the run is invalid and must be re-executed."""


class WorkflowFailure(Exception):
    """The evaluated workflow failed (timeout, no artifact): counted, never replaced."""


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


def verify_installation(arm_name, arm_cfg):
    actual = hash_tree(arm_cfg["installation_dir"])
    expected = arm_cfg["sha256"]
    if actual != expected:
        raise InfraFailure(
            f"arm `{arm_name}`: installation hash mismatch "
            f"(expected {expected}, got {actual}) — run blocked"
        )
    return actual


def make_profile(workspace, label):
    """Create a fresh, empty profile directory used as CLAUDE_CONFIG_DIR so
    ambient personal skills/commands/settings are never on the load path."""
    profile = Path(workspace) / "profiles" / f"{label}-{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=False)
    (profile / "settings.json").write_text("{}\n", encoding="utf-8")
    entries = sorted(p.name for p in profile.iterdir())
    if entries != ["settings.json"]:
        raise InfraFailure(f"profile {profile} not clean: {entries}")
    return profile


def backend_env(profile):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(profile)
    return env


def spawn_session(backend_cmd, prompt, cwd, env, timeout, resume=None):
    cmd = list(backend_cmd)
    if resume:
        cmd += ["--resume", resume]
    cmd += ["-p", prompt, "--output-format", "stream-json"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowFailure(f"session timed out after {timeout}s") from exc
    except OSError as exc:
        raise InfraFailure(f"backend could not be spawned: {exc}") from exc
    if proc.returncode != 0:
        raise InfraFailure(
            f"backend exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout


def parse_transcript(stdout):
    """Parse stream-json lines into accounting nodes.

    Recognized node fields: `model`, `usage.input_tokens`,
    `usage.output_tokens`, `tool_calls`, `subagent` (bool),
    `session_id` (on the result line)."""
    nodes, session_id = [], None
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
        if event.get("type") == "node":
            usage = event.get("usage", {})
            nodes.append(
                {
                    "model": event.get("model"),
                    "input_tokens": int(usage.get("input_tokens", 0)),
                    "output_tokens": int(usage.get("output_tokens", 0)),
                    "tool_calls": int(event.get("tool_calls", 0)),
                    "subagent": bool(event.get("subagent", False)),
                }
            )
    if session_id is None:
        raise InfraFailure("backend output contained no session_id")
    if not nodes:
        raise InfraFailure("backend output contained no accounting nodes")
    return session_id, nodes


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
    return totals


def validate_models(nodes, registered_model):
    bad = sorted({n["model"] for n in nodes if n["model"] != registered_model})
    if bad:
        raise InfraFailure(
            f"effective model(s) {bad} differ from registered "
            f"`{registered_model}` — run invalidated"
        )


def find_artifact(worktree, since_mtime):
    research = Path(worktree) / "thoughts" / "shared" / "research"
    if not research.is_dir():
        return None
    candidates = [
        p for p in research.glob("*.md") if p.stat().st_mtime >= since_mtime
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


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


def run_task(config, arm_name, task_path, repo_dir, output_dir):
    arm = config["arms"][arm_name]
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
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        record["installation_sha256"] = verify_installation(arm_name, arm)
        prompt = Path(task_path).read_text(encoding="utf-8")
        profile = make_profile(output_dir, arm_name)
        env = backend_env(profile)
        start_mtime = 0.0
        all_nodes, session_id = [], None
        stdout = spawn_session(
            config["backend_cmd"], prompt, repo_dir, env, config["timeout_seconds"]
        )
        session_id, nodes = parse_transcript(stdout)
        all_nodes.extend(nodes)
        artifact = find_artifact(repo_dir, start_mtime)
        while artifact is None and record["interventions"] < MAX_CONTINUATIONS:
            record["interventions"] += 1
            stdout = spawn_session(
                config["backend_cmd"],
                CONTINUATION_MESSAGE,
                repo_dir,
                env,
                config["timeout_seconds"],
                resume=session_id,
            )
            session_id, nodes = parse_transcript(stdout)
            all_nodes.extend(nodes)
            artifact = find_artifact(repo_dir, start_mtime)
        if artifact is None:
            raise WorkflowFailure(
                f"no research artifact after {MAX_CONTINUATIONS} continuations"
            )
        validate_models(all_nodes, arm["model"])
        record["accounting"] = account(all_nodes)
        record["nodes"] = all_nodes
        raw = artifact.read_text(encoding="utf-8")
        (out / f"run-{run_id}-raw.md").write_text(raw, encoding="utf-8")
        (out / f"run-{run_id}-anon.md").write_text(
            anonymize(raw, run_id), encoding="utf-8"
        )
        record["status"] = "completed"
    except WorkflowFailure as exc:
        record["status"] = "workflow_failure"
        record["failure"] = str(exc)
    except InfraFailure as exc:
        record["status"] = "infra_failure"
        record["failure"] = str(exc)
    (out / f"run-{run_id}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def score(config, doc_paths, judge_prompt_path, output_dir):
    """Spawn one fresh pinned backend session per document per judge prompt.
    Judge prompts live in the sealed package and are passed in at runtime —
    never committed here."""
    judge_prompt = Path(judge_prompt_path).read_text(encoding="utf-8")
    results = []
    for doc in doc_paths:
        profile = make_profile(output_dir, "judge")
        env = backend_env(profile)
        prompt = judge_prompt + "\n\n---\n\n" + Path(doc).read_text(encoding="utf-8")
        # cwd is the judge's own fresh profile dir so nothing a judge
        # session writes can land in a repository working tree.
        stdout = spawn_session(
            config["backend_cmd"], prompt, str(profile), env, config["timeout_seconds"]
        )
        session_id, nodes = parse_transcript(stdout)
        results.append(
            {"doc": str(doc), "session_id": session_id, "profile": str(profile),
             "accounting": account(nodes)}
        )
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
    parser.add_argument("--arm", help="arm name for `run`")
    parser.add_argument("--task", help="task prompt file for `run`")
    parser.add_argument("--repo", help="target repo worktree for `run`")
    parser.add_argument("--output", default="runs", help="output directory")
    args = parser.parse_args()

    if args.preflight:
        from preflight import run_preflight  # noqa: PLC0415 — colocated module

        sys.exit(run_preflight())

    if not (args.config and args.arm and args.task and args.repo):
        parser.error("run mode requires --config, --arm, --task, --repo")
    config = load_config(args.config)
    record = run_task(config, args.arm, args.task, args.repo, args.output)
    print(json.dumps({k: record[k] for k in ("run_id", "status", "interventions")}))
    sys.exit(0 if record["status"] == "completed" else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
