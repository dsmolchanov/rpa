#!/usr/bin/env python3
"""Eval-runner harness for the /research_codebase modernization pilot.

Implements prerequisite 5 of
`thoughts/shared/plans/2026-07-26-thinking-model-modernization-pilot.md`.
Capability map (each proven by `--preflight` before any scored run):

  1. installation-hash verification  — every run hashes the arm's
     installation tree against the registered SHA-256, mounts a copy into
     the run's profile, and passes its path to the backend via the
     `{installation}` placeholder in `backend_cmd`.
  2. per-node model/effort capture   — every transcript node records its
     model; effort is pinned in configuration; any node whose model differs
     from the registered one invalidates the run.
  3. clean profile                   — each run uses a runner-created
     CLAUDE_CONFIG_DIR containing only `settings.json` and the mounted
     installation; ambient personal skills/config are never on the load
     path.
  4. worktree isolation              — each run executes in a disposable
     detached git worktree at the task's pinned `target-sha` (verified),
     removed afterwards; a dirty/wrong checkout can never be researched.
  5. prompt extraction               — only the `## Task prompt` section of
     a task file reaches the evaluated session; a task carrying ground
     truth without that marker is refused.
  6. infra vs workflow failure       — backend crashes / unparseable output
     / wrong SHA are `infra_failure` (run invalid, re-executed); timeouts
     and missing-artifact completions are `workflow_failure` (counted per
     the failed-run rule, never replaced).
  7. tree-wide accounting            — tokens and tool calls are summed over
     every transcript node, main-context and subagent subtotals.
  8. artifact freshness              — only documents created or modified
     during the run count; pre-existing research docs are ignored.
  9. anonymization                   — scored copies carry a random run id
     and masked fingerprint frontmatter.
 10. fresh pinned judge sessions     — `--score` spawns each judge call as a
     new backend session in its own fresh profile, and preserves the
     judge's full response text on disk.

The backend command is configurable (`backend_cmd`); production uses the
`claude` CLI in headless mode, while `--preflight` uses the bundled
deterministic `mock_claude.py`. A real-backend preflight on the throwaway
task is still required once before baseline runs (see the pilot plan).

Stdlib only.
"""

import argparse
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
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
TARGET_SHA_RE = re.compile(r"^target-sha:\s*([0-9a-f]{7,40})\s*$", re.MULTILINE)


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


def make_profile(workspace, label, installation_dir=None):
    """Create a fresh profile directory used as CLAUDE_CONFIG_DIR so ambient
    personal skills/commands/settings are never on the load path. When an
    installation is given, mount a verified copy inside the profile."""
    profile = Path(workspace) / "profiles" / f"{label}-{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=False)
    (profile / "settings.json").write_text("{}\n", encoding="utf-8")
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


def expand_backend_cmd(backend_cmd, mount):
    expanded = []
    for part in backend_cmd:
        if "{installation}" in part:
            if mount is None:
                raise InfraFailure(
                    "backend_cmd expects {installation} but no installation mounted"
                )
            part = part.replace("{installation}", str(mount))
        expanded.append(part)
    return expanded


def extract_task_prompt(task_path):
    """Only the `## Task prompt` section may reach an evaluated session."""
    text = Path(task_path).read_text(encoding="utf-8")
    match = re.search(
        r"^## Task prompt\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if match:
        return match.group(1).strip(), text
    if re.search(r"^## Ground truth", text, re.MULTILINE):
        raise InfraFailure(
            f"{task_path}: contains ground truth but no `## Task prompt` "
            f"marker — refusing to send the whole file to an evaluated run"
        )
    return text.strip(), text


def task_target_sha(task_text, task_path):
    match = TARGET_SHA_RE.search(task_text)
    if not match:
        raise InfraFailure(f"{task_path}: no pinned `target-sha` in frontmatter")
    return match.group(1)


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
    """Disposable detached worktree at the pinned SHA, verified."""
    dest = Path(workspace) / "worktrees" / uuid.uuid4().hex[:12]
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


def spawn_session(cmd, prompt, cwd, env, timeout, resume=None):
    full = list(cmd)
    if resume:
        full += ["--resume", resume]
    full += ["-p", prompt, "--output-format", "stream-json"]
    try:
        proc = subprocess.run(
            full, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
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
    """Parse stream-json lines into accounting nodes plus the final response
    text. Node fields: `model`, `usage.input_tokens`, `usage.output_tokens`,
    `tool_calls`, `subagent`; `session_id` and optional `result` text on the
    result line."""
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
    return session_id, nodes, "\n".join(result_parts)


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
    worktree = None
    try:
        record["installation_sha256"] = verify_installation(arm_name, arm)
        prompt, task_text = extract_task_prompt(task_path)
        sha = task_target_sha(task_text, task_path)
        worktree = make_worktree(repo_dir, sha, output_dir)
        record["target_sha"] = sha
        record["worktree"] = str(worktree)
        profile, mount = make_profile(output_dir, arm_name, arm["installation_dir"])
        mount_hash = hash_tree(mount)
        if mount_hash != arm["sha256"]:
            raise InfraFailure("mounted installation copy hash mismatch")
        cmd = expand_backend_cmd(config["backend_cmd"], mount)
        env = backend_env(profile)
        before = snapshot_research(worktree)
        started = time.time()
        stdout = spawn_session(cmd, prompt, worktree, env,
                               config["timeout_seconds"])
        session_id, nodes, _ = parse_transcript(stdout)
        all_nodes = list(nodes)
        artifact = find_new_artifact(worktree, before)
        while artifact is None and record["interventions"] < MAX_CONTINUATIONS:
            record["interventions"] += 1
            stdout = spawn_session(cmd, CONTINUATION_MESSAGE, worktree, env,
                                   config["timeout_seconds"], resume=session_id)
            session_id, nodes, _ = parse_transcript(stdout)
            all_nodes.extend(nodes)
            artifact = find_new_artifact(worktree, before)
        record["wall_seconds"] = round(time.time() - started, 3)
        if artifact is None:
            raise WorkflowFailure(
                f"no fresh research artifact after {MAX_CONTINUATIONS} continuations"
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
    finally:
        if worktree is not None:
            remove_worktree(repo_dir, worktree)
    (out / f"run-{run_id}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def score(config, doc_paths, judge_prompt_path, output_dir):
    """One fresh pinned backend session per document. The judge's full
    response text is preserved on disk — it IS the scoring artifact. Judge
    prompts live in the sealed package and are passed in at runtime."""
    judge_prompt = Path(judge_prompt_path).read_text(encoding="utf-8")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, doc in enumerate(doc_paths):
        profile, _ = make_profile(output_dir, "judge")
        env = backend_env(profile)
        prompt = judge_prompt + "\n\n---\n\n" + Path(doc).read_text(encoding="utf-8")
        stdout = spawn_session(
            config["backend_cmd"], prompt, str(profile), env,
            config["timeout_seconds"]
        )
        session_id, nodes, response = parse_transcript(stdout)
        if not response.strip():
            raise InfraFailure(f"judge session {session_id} returned no response text")
        result = {
            "doc": str(doc),
            "session_id": session_id,
            "profile": str(profile),
            "response": response,
            "accounting": account(nodes),
        }
        (out / f"judge-{i}.json").write_text(
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
    parser.add_argument("--output", default="runs", help="output directory")
    args = parser.parse_args()

    if args.preflight:
        from preflight import run_preflight  # noqa: PLC0415 — colocated module

        sys.exit(run_preflight())

    if args.score:
        if not (args.config and args.docs and args.judge_prompt):
            parser.error("score mode requires --config, --docs, --judge-prompt")
        config = load_config(args.config)
        results = score(config, args.docs, args.judge_prompt, args.output)
        print(json.dumps([{k: r[k] for k in ("doc", "session_id")} for r in results]))
        sys.exit(0)

    if not (args.config and args.arm and args.task and args.repo):
        parser.error("run mode requires --config, --arm, --task, --repo")
    config = load_config(args.config)
    record = run_task(config, args.arm, args.task, args.repo, args.output)
    print(json.dumps({k: record[k] for k in ("run_id", "status", "interventions")}))
    sys.exit(0 if record["status"] == "completed" else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
