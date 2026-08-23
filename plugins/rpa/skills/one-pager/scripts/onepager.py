#!/usr/bin/env python3
"""One-pager digest: a deterministic, bounded projection of a repository's
recent work.

Contract: ../references/artifact-contract.md (single source for paths, shape,
bounds, determinism, and validator checks).

    onepager.py generate [--repo P] [--repos P...] [--since S] [--json]
                         [--write] [--out PATH] [--previous PATH]
    onepager.py validate <file.md|file.json>

Exit codes: 0 success/valid, 1 failure/invalid, 2 usage.
Standard library only; `git` required, `gh` used when available.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1

BOUNDS = {"repo": (80, 12 * 1024), "all": (160, 24 * 1024)}
BULLET_MAX_BYTES = 200
NARRATIVE_RESERVE_LINES = 13  # blank + heading + blank + marker + blank + 8 prose lines
NARRATIVE_RESERVE_BYTES = 1024
NARRATIVE_MAX_LINES = 8
NARRATIVE_MARKER = "_Model-written summary of the facts above; not a source._"

MAX_ARTIFACT_BYTES = 1024 * 1024
DEFAULT_WINDOW_DAYS = 14
GIT_DATE_FMT = "--date=format-local:%Y-%m-%dT%H:%M:%SZ"

ARTIFACT_ROOTS = (
    "plans",
    "tests",
    "implementations",
    "handoffs",
    "research",
    "debt",
    "test-suite",
)
ONE_PAGER_ROOT = "one-pagers"  # never a source (self-reference)
SHARED = ("thoughts", "shared")

PLACEHOLDER = "\x00generated_at\x00"
OUTCOMES = ("passed", "failed", "not_applicable")
DROP_PRIORITY = ("landed", "artifacts", "health", "open", "next")

SESSION_LOG_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-TDD-SESSION-.+\.md$")
SESSION_LOG_H1 = "# TDD Session:"
TEST_CASE_RE = re.compile(r"\b([UIE]-\d+)\b")
CRITERION_RE = re.compile(r"^\s*[-*] \[([ xX])\]\s*(.*)$")
NOT_APPLICABLE_RE = re.compile(r"^(not applicable|not run|n/a)\b", re.I)
ENHANCEMENT_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s+Enhancement", re.M)
RECEIPT_TOKEN_RE = re.compile(r"receipt\s+[0-9a-f]{12}\b")
ABS_PATH_RE = re.compile(r"(?:(?<=\s)|^|[(`])(?:~/|[A-Za-z]:\\\\|/(?:[A-Za-z0-9._-]+/){1,}[A-Za-z0-9._-]+)")
NEXT_SHAPES = (
    re.compile(r"^- \d+ open in \S+$"),
    re.compile(r"^- \S+ — cycle (continuing|blocked)$"),
    re.compile(r"^- next: .+ \(\S+\)$"),
    re.compile(r"^- #\d+ checks fail$"),
    re.compile(r"^- none$"),
    re.compile(r"^- \[\+\d+ more\]$"),
)
FACT_TOKEN_RES = (
    re.compile(r"#\d+"),
    re.compile(r"\b(?:thoughts/[\w./-]+|[\w.-]+/[\w./-]+\.\w+)"),
    re.compile(r"\b\d+\s+(?:PRs?|commits?|criteria|cases?|receipts?)\b", re.I),
)


class UsageError(Exception):
    """Bad invocation — exit 2."""


class GenerateError(Exception):
    """Required source unavailable — exit 1."""


# ---------------------------------------------------------------------------
# process helpers


def _run(cmd, cwd=None):
    env = dict(os.environ, TZ="UTC", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, env=env
    )


def _git(repo, *args):
    return _run(["git", "-C", str(repo), *args])


def _sanitize(text):
    """Reasons never carry absolute paths (validator check j)."""
    text = " ".join((text or "").split())
    text = ABS_PATH_RE.sub("<path>", text)
    return text[:120]


# ---------------------------------------------------------------------------
# git


def repo_root(path):
    res = _run(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    if res.returncode != 0:
        raise GenerateError(f"not a git repository: {path}")
    return Path(res.stdout.strip()).resolve()


def head_sha(repo):
    res = _git(repo, "rev-parse", "HEAD")
    if res.returncode != 0:
        raise GenerateError("repository has no commits")
    return res.stdout.strip()


def head_date(repo):
    res = _git(repo, "log", "-1", GIT_DATE_FMT, "--format=%cd", "HEAD")
    return res.stdout.strip()[:10] if res.returncode == 0 else "1970-01-01"


def default_branch(repo):
    res = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip().rsplit("/", 1)[-1]
    for name in ("master", "main"):
        if _git(repo, "rev-parse", "--verify", "--quiet", name).returncode == 0:
            return name
    res = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return res.stdout.strip() or "master"


def _rev(repo, ref):
    res = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


def resolve_since(repo, since, previous):
    """Fixed point: an unchanged HEAD reuses the previous window start."""
    head = head_sha(repo)
    if since in (None, "", "last"):
        if previous:
            if previous.get("generated_from") == head and previous.get("window.since"):
                return previous["window.since"]
            if previous.get("generated_from"):
                return previous["generated_from"]
        base = _git(repo, "log", "-1", GIT_DATE_FMT, "--format=%cd", "HEAD").stdout.strip()
        try:
            stamp = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            stamp = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (stamp - timedelta(days=DEFAULT_WINDOW_DAYS)).strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        return since
    rev = _rev(repo, since)
    if not rev:
        raise UsageError(f"--since is neither an ISO date nor a git ref: {since}")
    return rev


def _log_args(repo, since):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        return [f"--since={since}"]
    return [f"{since}..HEAD"]


def git_commits(repo, since):
    res = _git(
        repo, "log", GIT_DATE_FMT, "--format=%H%x1f%s%x1f%cd", *_log_args(repo, since)
    )
    if res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) == 3:
            out.append({"sha": parts[0], "subject": parts[1], "date": parts[2]})
    return out


def git_window_paths(repo, since):
    res = _git(repo, "log", "--name-only", "--format=%x00", *_log_args(repo, since))
    if res.returncode != 0:
        return set()
    return {l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith("\x00")}


def git_dirty_paths(repo):
    res = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if res.returncode != 0:
        return set()
    tokens = [t for t in res.stdout.split("\0") if t]
    paths, i = set(), 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        paths.add(path)
        if code[0] in ("R", "C"):
            if i < len(tokens):
                paths.add(tokens[i])
                i += 1
    return paths


# ---------------------------------------------------------------------------
# gh (degrading)


AUTH_MARKERS = ("gh auth login", "not logged in", "authentication", "unauthorized")


def _has_github_remote(repo):
    res = _git(repo, "remote", "get-url", "origin")
    return res.returncode == 0 and "github.com" in res.stdout


def _gh(repo, args):
    """Returns (data, outcome, reason)."""
    if shutil.which("gh") is None:
        return None, "not_applicable", "gh not found"
    if not _has_github_remote(repo):
        return None, "not_applicable", "no github remote"
    res = _run(["gh", *args], cwd=repo)
    if res.returncode != 0:
        err = _sanitize(res.stderr) or f"exit {res.returncode}"
        if any(m in res.stderr.lower() for m in AUTH_MARKERS):
            return None, "not_applicable", "gh not authenticated"
        return None, "failed", err
    try:
        return json.loads(res.stdout or "null"), "passed", ""
    except ValueError:
        return None, "failed", "malformed json"


def gh_prs(repo, state, since=None):
    args = [
        "pr", "list", "--state", state, "--limit", "200" if state == "merged" else "100",
        "--json",
        "number,title,mergedAt,author,mergeCommit,files"
        if state == "merged"
        else "number,title,isDraft,reviewDecision,headRefName",
    ]
    if state == "merged" and since and re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        args += ["--search", f"merged:>={since}"]
    data, outcome, reason = _gh(repo, args)
    return (data if isinstance(data, list) else []), outcome, reason


def gh_pr_commits(repo, number):
    data, outcome, reason = _gh(repo, ["pr", "view", str(number), "--json", "commits"])
    if outcome != "passed" or not isinstance(data, dict):
        return [], outcome, reason
    return (
        [c.get("oid", "") for c in data.get("commits", []) if isinstance(c, dict)],
        outcome,
        reason,
    )


def combine(parts):
    """One Sources row from many calls: any failure fails the row. A per-call
    outcome that never reaches the table is a degraded source presented as a
    healthy one."""
    parts = [p for p in parts if p]
    failed = [(o, r) for o, r in parts if o == "failed"]
    if failed:
        reason = failed[0][1] or "call failed"
        if len(failed) > 1:
            reason = f"{reason} ({len(failed)} of {len(parts)} calls failed)"
        return "failed", reason
    skipped = [(o, r) for o, r in parts if o == "not_applicable"]
    if skipped and len(skipped) == len(parts):
        return "not_applicable", skipped[0][1]
    return "passed", ""


def gh_checks(repo, number):
    data, outcome, reason = _gh(repo, ["pr", "checks", str(number), "--json", "name,bucket"])
    if outcome != "passed" or not isinstance(data, list):
        # Never report an unreadable rollup as `pending`: that is a claim
        # about the pull request, not about the failed call.
        return "unknown", outcome, reason
    buckets = [str(c.get("bucket", "")).lower() for c in data if isinstance(c, dict)]
    if any(b == "fail" for b in buckets):
        return "fail", outcome, reason
    if buckets and all(b in ("pass", "skipping") for b in buckets):
        return "pass", outcome, reason
    return "pending", outcome, reason


def gh_runs(repo, branch):
    data, outcome, reason = _gh(
        repo,
        ["run", "list", "--workflow", "ci.yml", "--branch", branch, "--limit", "1",
         "--json", "headSha,conclusion,status"],
    )
    if outcome != "passed" or not isinstance(data, list) or not data:
        return None, outcome, reason
    return data[0], outcome, reason


def attribute_commits(commits, merged_prs, pr_commit_shas):
    """A commit belongs to a PR via mergeCommit or the PR's commit list."""
    owned = set()
    for pr in merged_prs:
        merge = (pr.get("mergeCommit") or {})
        if isinstance(merge, dict) and merge.get("oid"):
            owned.add(merge["oid"])
        owned.update(pr_commit_shas.get(pr.get("number"), []))
    unattributed = [c for c in commits if c["sha"] not in owned]
    return unattributed


# ---------------------------------------------------------------------------
# artifacts


def contained_regular_file(repo, rel):
    """'ok' | 'symlink' | 'special' | 'oversized' | 'outside' | 'missing'."""
    base = repo.resolve()
    target = base / rel
    parent = target.parent
    probe = parent
    while True:
        if os.path.islink(probe):
            return "symlink"
        if probe == base or probe.parent == probe:
            break
        probe = probe.parent
    if os.path.islink(target):
        return "symlink"
    try:
        real = target.resolve()
    except OSError:
        return "missing"
    try:
        real.relative_to(base)
    except ValueError:
        return "outside"
    parts = real.relative_to(base).parts
    if parts[:2] != SHARED:
        return "outside"
    if not target.exists():
        return "missing"
    st = os.stat(target)
    if not stat.S_ISREG(st.st_mode):
        return "special"
    if st.st_size > MAX_ARTIFACT_BYTES:
        return "oversized"
    return "ok"


def _root_of(rel):
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[:2] == SHARED and parts[2] in ARTIFACT_ROOTS:
        return parts[2]
    return None


def _read(repo, rel):
    return (repo / rel).read_text(encoding="utf-8", errors="replace")


def plan_status(text):
    satisfied = opened = na = 0
    for line in text.splitlines():
        m = CRITERION_RE.match(line)
        if not m:
            continue
        mark, body = m.group(1), m.group(2).strip()
        if mark in ("x", "X"):
            satisfied += 1
        elif NOT_APPLICABLE_RE.match(body):
            na += 1
        else:
            opened += 1
    enhanced = ENHANCEMENT_RE.findall(text)
    status = f"satisfied {satisfied} / open {opened} / not-applicable {na}"
    if enhanced:
        status += f"; enhanced {sorted(enhanced)[-1]}"
    return {"satisfied": satisfied, "open": opened, "not_applicable": na, "status": status}


def test_plan_status(text):
    cases = sorted(set(TEST_CASE_RE.findall(text)))
    return {"cases": len(cases), "status": f"{len(cases)} cases"}


def is_session_log(rel, text):
    return SESSION_LOG_NAME_RE.match(Path(rel).name) or text.lstrip().startswith(SESSION_LOG_H1)


def session_log_status(repo, rel, text):
    def field(name, default="unknown"):
        m = re.search(rf"\*\*{name}\*\*:\s*`?([^`\n]+)", text)
        return m.group(1).strip().strip("`") if m else default

    achieved = field("Achieved phase")
    cycle = field("Cycle state")
    receipts = "none"
    m = re.search(r"\*\*Evidence export\*\*:\s*`?([^`\s]+)", text)
    if m:
        export_rel = (Path(rel).parent / m.group(1)).as_posix()
        if contained_regular_file(repo, export_rel) == "ok":
            try:
                data = json.loads(_read(repo, export_rel))
                if isinstance(data, dict) and "records_through" in data:
                    receipts = str(data["records_through"])
            except ValueError:
                receipts = "none"
    return {
        "achieved": achieved,
        "cycle": cycle,
        "receipts": receipts,
        "status": f"{achieved}; cycle {cycle}; receipts {receipts}",
    }


def validation_status(text):
    m = re.search(r"\*\*Plan\*\*:\s*`?([^`\n]+)", text)
    status = "present"
    if m:
        status += f"; plan {m.group(1).strip().strip('`')}"
    return {"status": status}


def handoff_status(text):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip("#").strip().strip("*").strip()
        if re.match(r"^(action items( & next steps)?|next steps)\b", stripped, re.I):
            start = i + 1
            break
    if start is None:
        return {"steps": [], "status": "no next-steps section"}
    steps = []
    for line in lines[start:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or (s.startswith("**") and s.endswith(":")):
            break
        m = re.match(r"^[-*]\s+(?:\[[ xX]\]\s*)?(.+)$", s)
        if m:
            steps.append(" ".join(m.group(1).split()))
            if len(steps) == 3:
                break
    return {"steps": steps, "status": "; ".join(steps) if steps else "no next-steps section"}


def parse_artifact(repo, rel):
    root = _root_of(rel)
    text = _read(repo, rel)
    if root == "plans":
        info = plan_status(text)
    elif root == "tests":
        info = session_log_status(repo, rel, text) if is_session_log(rel, text) else test_plan_status(text)
    elif root == "implementations":
        info = validation_status(text)
    elif root == "handoffs":
        info = handoff_status(text)
    else:
        info = {"status": "present"}
    info["root"] = root
    info["path"] = rel
    return info


def scan_artifacts(repo, rels):
    """Parse the given repo-relative paths; return (infos, skipped) where
    `skipped` maps a root to {path: verdict} — keyed by path so the same file
    rejected by two scans is counted once."""
    infos, skipped = [], {}
    for rel in sorted(rels):
        root = _root_of(rel)
        if root is None or not rel.endswith(".md"):
            continue
        verdict = contained_regular_file(repo, rel)
        if verdict == "missing":
            continue
        if verdict != "ok":
            skipped.setdefault(root, {})[rel] = verdict
            continue
        infos.append(parse_artifact(repo, rel))
    return infos, skipped


def merge_skips(*maps):
    merged = {}
    for source in maps:
        for root, entries in source.items():
            merged.setdefault(root, {}).update(entries)
    return merged


def all_active_artifacts(repo):
    """Every readable artifact under plans/, tests/, handoffs/ — the basis for
    `## Next`, which must not be limited to the window."""
    rels = []
    for root in ("plans", "tests", "handoffs"):
        base = repo / "thoughts" / "shared" / root
        if not base.is_dir() or os.path.islink(base):
            continue
        for path in sorted(base.rglob("*.md")):
            rels.append(path.relative_to(repo).as_posix())
    return scan_artifacts(repo, rels)


def derive_next(all_infos, open_prs):
    items = []
    for info in all_infos:
        if info["root"] == "plans" and info.get("open"):
            items.append(f"{info['open']} open in {info['path']}")
        elif info["root"] == "tests" and info.get("cycle") in ("continuing", "blocked"):
            items.append(f"{info['path']} — cycle {info['cycle']}")
    newest_handoff = {}
    for info in all_infos:
        if info["root"] == "handoffs" and info.get("steps"):
            ticket = str(Path(info["path"]).parent)
            prev = newest_handoff.get(ticket)
            if prev is None or info["path"] > prev["path"]:
                newest_handoff[ticket] = info
    for ticket in sorted(newest_handoff):
        info = newest_handoff[ticket]
        items.append(f"next: {info['steps'][0]} ({info['path']})")
    for pr in open_prs:
        if pr.get("checks") == "fail":
            items.append(f"#{pr['number']} checks fail")
    return items


# ---------------------------------------------------------------------------
# facts


def collect_repo_facts(path, since_arg, previous):
    repo = repo_root(path)
    head = head_sha(repo)
    sources = [{"source": "git", "outcome": "passed", "reason": ""}]
    since = resolve_since(repo, since_arg, previous)
    commits = git_commits(repo, since)
    branch = default_branch(repo)

    merged, merged_outcome, merged_reason = gh_prs(repo, "merged", since)
    pr_parts = [(merged_outcome, merged_reason)]
    window_shas = {c["sha"] for c in commits}
    pr_commit_shas = {}
    landed = []
    for pr in merged:
        number = pr.get("number")
        shas, shas_outcome, shas_reason = gh_pr_commits(repo, number)
        pr_parts.append((shas_outcome, shas_reason))
        pr_commit_shas[number] = shas
        merge_oid = (pr.get("mergeCommit") or {}).get("oid") if isinstance(pr.get("mergeCommit"), dict) else None
        if not (window_shas & set(shas)) and merge_oid not in window_shas:
            continue
        landed.append(
            {
                "number": number,
                "title": " ".join(str(pr.get("title", "")).split()),
                "merged_at": str(pr.get("mergedAt") or ""),
                "author": ((pr.get("author") or {}).get("login") if isinstance(pr.get("author"), dict) else "") or "unknown",
                "files": len(pr.get("files") or []),
            }
        )
    landed.sort(key=lambda p: (p["merged_at"], p["number"]), reverse=True)
    unattributed = attribute_commits(commits, merged, pr_commit_shas)

    open_raw, open_outcome, open_reason = gh_prs(repo, "open")
    pr_parts.append((open_outcome, open_reason))
    check_parts = []
    open_prs = []
    for pr in open_raw:
        rollup, check_outcome, check_reason = gh_checks(repo, pr.get("number"))
        check_parts.append((check_outcome, check_reason))
        open_prs.append(
            {
                "number": pr.get("number"),
                "title": " ".join(str(pr.get("title", "")).split()),
                "draft": bool(pr.get("isDraft")),
                "review": str(pr.get("reviewDecision") or "none"),
                "checks": rollup,
            }
        )
    open_prs.sort(key=lambda p: p["number"], reverse=True)

    prs_outcome, prs_reason = combine(pr_parts)
    sources.append({"source": "gh-prs", "outcome": prs_outcome, "reason": prs_reason})
    if check_parts:
        checks_outcome, checks_reason = combine(check_parts)
    elif open_outcome == "passed":
        checks_outcome, checks_reason = "not_applicable", "no open pull requests"
    else:
        checks_outcome, checks_reason = open_outcome, "open pull requests unavailable"
    sources.append({"source": "gh-checks", "outcome": checks_outcome, "reason": checks_reason})

    run, run_outcome, run_reason = gh_runs(repo, branch)
    sources.append({"source": "gh-runs", "outcome": run_outcome, "reason": run_reason})
    health = []
    if run:
        state = run.get("conclusion") or run.get("status") or "unknown"
        health.append(f"ci on {branch}: {state} ({str(run.get('headSha') or '')[:7]})")
    for pr in open_prs:
        if pr["checks"] == "fail":
            health.append(f"#{pr['number']} checks fail")

    window_paths = git_window_paths(repo, since)
    dirty = git_dirty_paths(repo)
    infos, window_skips = scan_artifacts(repo, window_paths | dirty)
    active_infos, active_skips = all_active_artifacts(repo)
    # A containment rejection is a degraded root wherever it was found: the
    # `## Next` scan reaches artifacts the window never touches.
    skipped = merge_skips(window_skips, active_skips)
    for root in ARTIFACT_ROOTS:
        base = repo / "thoughts" / "shared" / root
        reason = ""
        if not base.is_dir():
            outcome = "not_applicable"
            reason = "absent"
        else:
            outcome = "passed"
            marks = skipped.get(root, {})
            if marks:
                reason = f"skipped: {len(marks)} " + "/".join(sorted(set(marks.values())))
        sources.append({"source": root, "outcome": outcome, "reason": reason})

    artifacts = [
        {"root": i["root"], "path": i["path"], "status": i["status"]}
        for i in sorted(infos, key=lambda i: (i["root"], i["path"]), reverse=True)
    ]
    nxt = derive_next(active_infos, open_prs)

    return {
        "repo": slugify(repo.name),
        "generated_from": head,
        "window": {"since": since, "head": head, "commits": len(commits)},
        "landed": landed,
        "unattributed": [
            {"sha": c["sha"], "subject": " ".join(c["subject"].split()), "date": c["date"]}
            for c in unattributed
        ],
        "open": open_prs,
        "artifacts": artifacts,
        "health": health,
        "next": nxt,
        "sources": sources,
    }


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "repo"


def facts_json(facts):
    return json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# rendering


def _clip(text):
    raw = text.encode("utf-8")
    if len(raw) <= BULLET_MAX_BYTES:
        return text
    return raw[: BULLET_MAX_BYTES - 3].decode("utf-8", "ignore") + "…"


def landed_order(entry):
    """One chronological list over two fact lists. Rendering pull requests
    first and commits second would let tail truncation drop a recent commit
    while keeping an older pull request — the opposite of the newest-first
    guarantee. Sorted from the facts alone, so the JSON companion agrees."""
    items = []
    for index, pr in enumerate(entry["landed"]):
        items.append((pr.get("merged_at") or "", 1, f"{pr.get('number') or 0:09d}", "pr", index))
    for index, commit in enumerate(entry["unattributed"]):
        items.append((commit.get("date") or "", 0, commit.get("sha") or "", "commit", index))
    items.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [(kind, index) for _, _, _, kind, index in items]


def _bullets(name, entry):
    if name == "landed":
        out = []
        for kind, index in landed_order(entry):
            if kind == "pr":
                p = entry["landed"][index]
                count = p["files"]
                files = "1 file" if count == 1 else f"{count}{'+' if count >= 100 else ''} files"
                out.append(
                    f"- #{p['number']} {p['title']} — merged {p['merged_at'][:10]} "
                    f"by {p['author']} ({files})"
                )
            else:
                c = entry["unattributed"][index]
                out.append(f"- unattributed {c['sha'][:7]} {c['subject']} ({c['date'][:10]})")
        return out
    if name == "open":
        return [
            f"- #{p['number']} {p['title']} — {'draft' if p['draft'] else 'open'}, "
            f"checks {p['checks']}, review {p['review']}"
            for p in entry["open"]
        ]
    if name == "artifacts":
        return [f"- {a['root']} {a['path']} — {a['status']}" for a in entry["artifacts"]]
    if name == "health":
        return [f"- {h}" for h in entry["health"]]
    if name == "next":
        return [f"- {n}" for n in entry["next"]]
    return []


def _section(title, bullets, kept, dropped, level="##"):
    lines = [f"{level} {title}", ""]
    shown = [_clip(b) for b in bullets[:kept]]
    dropped += len(bullets) - kept
    if not shown and dropped <= 0:
        shown = ["- none"]
    lines += shown
    if dropped > 0:
        lines.append(f"- [+{dropped} more]")
    lines.append("")
    return lines


def _keep_and_drop(entry, name, index, kept):
    """(keep, already-dropped) for one section. `kept` is the search loop's
    side channel; without it the counts come from the facts themselves, which
    is what makes the JSON companion agree with the Markdown."""
    bullets = _bullets(name, entry)
    dropped = int((entry.get("truncated") or {}).get(name, 0))
    keep = len(bullets) if kept is None else kept.get((index, name), len(bullets))
    return bullets, keep, dropped


def materialize(facts, kept):
    """Write the search loop's decisions into the facts: slice each list and
    record what was dropped. After this, `render_markdown(facts)` alone
    reproduces the bounded page and `facts_json(facts)` describes exactly it."""
    for index, entry in enumerate(facts["repos"]):
        truncated = {}
        for name in SECTION_NAMES:
            key = (index, name)
            if key not in kept:
                continue
            total = len(_bullets(name, entry))
            keep = kept[key]
            dropped = total - keep
            if dropped <= 0:
                continue
            truncated[name] = dropped
            if name == "landed":
                # keep the newest `keep` entries of the chronological order,
                # then rebuild both fact lists from the survivors.
                survivors = landed_order(entry)[:keep]
                prs = sorted(i for kind, i in survivors if kind == "pr")
                commits = sorted(i for kind, i in survivors if kind == "commit")
                entry["landed"] = [entry["landed"][i] for i in prs]
                entry["unattributed"] = [entry["unattributed"][i] for i in commits]
            elif name == "open":
                entry["open"] = entry["open"][:keep]
            elif name == "artifacts":
                entry["artifacts"] = entry["artifacts"][:keep]
            elif name == "health":
                entry["health"] = entry["health"][:keep]
            elif name == "next":
                entry["next"] = entry["next"][:keep]
        if truncated:
            entry["truncated"] = truncated


def _sources_table(rows, prefix=""):
    lines = ["## Sources", "", "| source | outcome | reason |", "| --- | --- | --- |"]
    for row in rows:
        name = f"{prefix}{row['source']}"
        lines.append(f"| {name} | {row['outcome']} | {_sanitize(row['reason'])} |")
    lines.append("")
    return lines


SECTION_NAMES = ("landed", "open", "artifacts", "health", "next")
SECTION_TITLES = {
    "landed": "Landed",
    "open": "Open",
    "artifacts": "Artifacts",
    "health": "Health",
    "next": "Next",
}


def render_markdown(facts, kept=None):
    mode = facts["mode"]
    if mode == "repo":
        entry = facts["repos"][0]
        lines = [
            f"# One-pager: {entry['repo']}",
            "",
            "mode: repo",
            f"generated_at: {facts['generated_at']}",
            f"repo: {entry['repo']}",
            f"generated_from: {entry['generated_from']}",
            f"window.since: {entry['window']['since']}",
            f"window.head: {entry['window']['head']}",
            "",
            "## Window",
            "",
            f"- since: {entry['window']['since']}",
            f"- head: {entry['window']['head'][:7]}",
            f"- commits: {entry['window']['commits']}",
            "",
        ]
        for name in SECTION_NAMES:
            bullets, keep, dropped = _keep_and_drop(entry, name, 0, kept)
            lines += _section(SECTION_TITLES[name], bullets, keep, dropped)
        lines += _sources_table(entry["sources"])
        return "\n".join(lines).rstrip("\n") + "\n"

    lines = ["# One-pager (all repos)", "", "mode: all", f"generated_at: {facts['generated_at']}", ""]
    rows = []
    for index, entry in enumerate(facts["repos"]):
        lines += [
            f"## {entry['repo']}",
            "",
            f"repo: {entry['repo']}",
            f"generated_from: {entry['generated_from']}",
            f"window.since: {entry['window']['since']}",
            f"window.head: {entry['window']['head']}",
            "",
            "### Window",
            "",
            f"- since: {entry['window']['since']}",
            f"- head: {entry['window']['head'][:7]}",
            f"- commits: {entry['window']['commits']}",
            "",
        ]
        for name in ("landed", "open", "next"):
            bullets, keep, dropped = _keep_and_drop(entry, name, index, kept)
            lines += _section(SECTION_TITLES[name], bullets, keep, dropped, level="###")
        rows.append(aggregate_sources(entry))
    lines += _sources_table(rows)
    return "\n".join(lines).rstrip("\n") + "\n"


def aggregate_sources(entry):
    """`mode: all` carries one row per repository: eleven rows each would put
    the page over its bound before a single fact was rendered."""
    rows = entry["sources"]
    failed = [r["source"] for r in rows if r["outcome"] == "failed"]
    skipped = [r["source"] for r in rows if r["outcome"] == "not_applicable"]
    if failed:
        outcome, reason = "failed", "failed: " + ", ".join(sorted(failed))
    else:
        outcome = "passed"
        reason = f"{len(skipped)} not_applicable" if skipped else ""
    return {"source": entry["repo"], "outcome": outcome, "reason": reason}


def _over_budget(text, mode):
    max_lines, max_bytes = BOUNDS[mode]
    budget_lines = max_lines - NARRATIVE_RESERVE_LINES
    budget_bytes = max_bytes - NARRATIVE_RESERVE_BYTES
    return len(text.splitlines()) > budget_lines or len(text.encode("utf-8")) > budget_bytes


def allocate_and_bound(facts):
    """Fill lists after reserving structure and narrative capacity; truncate
    tails (oldest) so the newest items and every heading survive."""
    mode = facts["mode"]
    names = SECTION_NAMES if mode == "repo" else ("landed", "open", "next")
    kept = {}
    for index, entry in enumerate(facts["repos"]):
        for name in names:
            kept[(index, name)] = len(_bullets(name, entry))
    text = render_markdown(facts, kept)
    while _over_budget(text, mode):
        candidates = [(count, key) for key, count in kept.items() if count > 0]
        if not candidates:
            # Structure alone exceeds the bound. Emitting the page anyway
            # would hand the caller a digest its own validator rejects, so
            # refuse instead — the caller can split the repository set.
            max_lines, _ = BOUNDS[mode]
            raise UsageError(
                f"{len(facts['repos'])} repositories do not fit the "
                f"{max_lines}-line bound for mode {mode}; pass fewer --repos"
            )
        best = max(c for c, _ in candidates)
        pick = min(
            (k for c, k in candidates if c == best),
            key=lambda k: (DROP_PRIORITY.index(k[1]), k[0]),
        )
        kept[pick] -= 1
        text = render_markdown(facts, kept)
    materialize(facts, kept)
    return render_markdown(facts)


# ---------------------------------------------------------------------------
# previous digest


def _header_fields(block):
    out = {}
    for field in ("repo", "generated_from", "window.since", "window.head"):
        m = re.search(rf"^{re.escape(field)}:\s*(.+)$", block, re.M)
        if m:
            out[field] = m.group(1).strip()
    return out


def read_previous(path):
    """Previous digest, indexed by repository. A cross-repository page carries
    one header block per `## <slug>` section; without reading them, a
    scheduled `--repos` refresh would silently fall back to a fresh 14-day
    window every time any repository advanced."""
    if not path or not Path(path).is_file():
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    mode_match = re.search(r"(?m)^mode: (repo|all)$", text)
    mode = mode_match.group(1) if mode_match else "repo"
    stamp = re.search(r"(?m)^generated_at:\s*(.+)$", text)
    out = {"_text": text, "mode": mode, "repos": {}}
    if stamp:
        out["generated_at"] = stamp.group(1).strip()
    if mode == "all":
        for chunk in text.split("\n## ")[1:]:
            fields = _header_fields(chunk)
            if fields.get("repo"):
                out["repos"][fields["repo"]] = fields
    else:
        fields = _header_fields(text)
        if fields.get("repo"):
            out["repos"][fields["repo"]] = fields
    return out


def preserved_generated_at(previous, rendered_with_placeholder):
    """Reuse the previous timestamp when the canonical facts are identical."""
    if not previous or "generated_at" not in previous:
        return None
    prev = previous["_text"].split("\n## Narrative", 1)[0].rstrip("\n") + "\n"
    prev = re.sub(r"(?m)^generated_at: .*$", f"generated_at: {PLACEHOLDER}", prev, count=1)
    fresh = rendered_with_placeholder.split("\n## Narrative", 1)[0].rstrip("\n") + "\n"
    return previous["generated_at"] if prev == fresh else None


# ---------------------------------------------------------------------------
# writing


def _atomic_write(path, data):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if os.path.islink(parent) or not parent.is_dir():
        raise UsageError(f"refusing to write under a symlinked or non-directory parent: {parent.name}")
    if os.path.islink(path):
        raise UsageError(f"refusing to replace a symlink: {path.name}")
    if path.exists() and not path.is_file():
        raise UsageError(f"refusing to replace a non-regular file: {path.name}")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    fd = os.open(str(parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def rpa_home():
    return Path(os.environ.get("RPA_HOME") or (Path.home() / ".rpa"))


def default_out(mode, repos, date):
    if mode == "repo":
        repo = repos[0]
        return repo / "thoughts" / "shared" / ONE_PAGER_ROOT / f"{date}-{slugify(repo.name)}.md"
    home = rpa_home() / ONE_PAGER_ROOT
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    return home / f"{date}-all.md"


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# validation


def _strip_fences(lines):
    out, fenced = [], False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return out


def _headings(lines):
    return [l for l in _strip_fences(lines) if l.startswith("#")]


# Check (b) is an ORDER check: a header whose fields merely exist somewhere in
# the file is not the header the contract describes.
PAGE_HEADER_KEYS = {
    "repo": ["mode", "generated_at", "repo", "generated_from", "window.since", "window.head"],
    "all": ["mode", "generated_at"],
}
REPO_HEADER_KEYS = {
    "repo": [],
    "all": ["repo", "generated_from", "window.since", "window.head"],
}
HEADER_LINE_RE = re.compile(r"^([a-z_.]+):\s+\S")


def _header_keys(lines, start):
    """Keys of the contiguous `key: value` block after a heading, in order."""
    keys, seen = [], False
    for line in lines[start:]:
        if not line.strip():
            if seen:
                break
            continue
        m = HEADER_LINE_RE.match(line)
        if not m:
            break
        seen = True
        keys.append(m.group(1))
    return keys


def validate_text(text, companion=None):
    errors = []
    lines = text.splitlines()
    body = _strip_fences(lines)
    mode_match = re.search(r"(?m)^mode: (repo|all)$", text)
    mode = mode_match.group(1) if mode_match else None
    if mode is None:
        errors.append("one-pager: b — missing or invalid `mode:` header field")
        return errors

    headings = _headings(lines)
    if mode == "repo":
        expected = [
            "# One-pager: ",
            "## Window",
            "## Landed",
            "## Open",
            "## Artifacts",
            "## Health",
            "## Next",
            "## Sources",
        ]
        actual = headings[: len(expected)]
        ok = len(actual) == len(expected) and actual[0].startswith(expected[0]) and actual[1:] == expected[1:]
        extra = headings[len(expected):]
        if not ok:
            errors.append(f"one-pager: a — heading sequence {actual} != expected {expected}")
        if extra and extra != ["## Narrative"]:
            errors.append(f"one-pager: a — unexpected trailing headings {extra}")
    else:
        if not headings or headings[0] != "# One-pager (all repos)":
            errors.append("one-pager: a — cross-repo page must start with `# One-pager (all repos)`")
        rest = headings[1:]
        tail = rest[-1:] if rest and rest[-1] == "## Narrative" else []
        if tail:
            rest = rest[:-1]
        if not rest or rest[-1] != "## Sources":
            errors.append("one-pager: a — cross-repo page must end with `## Sources`")
        else:
            rest = rest[:-1]
            if not rest or len(rest) % 5 != 0:
                errors.append("one-pager: a — each repository needs one `## <slug>` + four `###` sections")
            for i in range(0, len(rest), 5):
                group = rest[i : i + 5]
                if len(group) != 5 or not group[0].startswith("## ") or group[1:] != [
                    "### Window",
                    "### Landed",
                    "### Open",
                    "### Next",
                ]:
                    errors.append(f"one-pager: a — malformed repository section {group}")
                    break

    if len(re.findall(r"(?m)^generated_at: .+$", text)) != 1:
        errors.append("one-pager: b — exactly one page-level `generated_at` required")
    page_keys = PAGE_HEADER_KEYS[mode]
    repo_keys = REPO_HEADER_KEYS[mode]
    heading_re = re.compile(r"^# " if mode == "repo" else r"^## ")
    blocks = []
    for index, line in enumerate(body):
        if line.startswith("# ") or (mode == "all" and line.startswith("## ") and line != "## Sources"):
            blocks.append((line, _header_keys(body, index + 1)))
    if not blocks:
        errors.append("one-pager: b — no header block found")
    else:
        title_keys = blocks[0][1]
        if title_keys != page_keys:
            errors.append(
                f"one-pager: b — page header must be {page_keys} in order, got {title_keys}"
            )
        for heading, keys in blocks[1:]:
            if keys != repo_keys:
                errors.append(
                    f"one-pager: b — header block under `{heading}` must be "
                    f"{repo_keys} in order, got {keys}"
                )
        if mode == "all" and len(blocks) < 2:
            errors.append("one-pager: b — a cross-repository page needs one repository block")

    max_lines, max_bytes = BOUNDS[mode]
    if len(lines) > max_lines:
        errors.append(f"one-pager: c — {len(lines)} lines exceeds {max_lines} for mode {mode}")
    if len(text.encode("utf-8")) > max_bytes:
        errors.append(f"one-pager: c — {len(text.encode('utf-8'))} bytes exceeds {max_bytes} for mode {mode}")
    for line in body:
        if line.startswith("- ") and len(line.encode("utf-8")) > BULLET_MAX_BYTES:
            errors.append(f"one-pager: c — bullet over {BULLET_MAX_BYTES} bytes: {line[:40]}…")

    in_sources = False
    rows = 0
    for line in body:
        if line.startswith("## Sources"):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            in_sources = False
        if in_sources and line.startswith("|") and "---" not in line and "outcome" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows += 1
            if len(cells) != 3 or cells[1] not in OUTCOMES:
                errors.append(f"one-pager: d — invalid Sources row: {line[:60]}")
    if rows == 0:
        errors.append("one-pager: d — Sources table has no rows")

    if RECEIPT_TOKEN_RE.search(text):
        errors.append("one-pager: e — receipt token present; a digest cites logs, not receipts")

    collecting = False
    for line in body:
        if re.match(r"^#{2,3} Next$", line):
            collecting = True
            continue
        if collecting and line.startswith("#"):
            collecting = False
        if collecting and line.startswith("- "):
            if not any(shape.match(line) for shape in NEXT_SHAPES):
                errors.append(f"one-pager: f — Next bullet not an allowed shape: {line[:60]}")

    if "## Narrative" in text:
        above, narrative = text.split("## Narrative", 1)
        narr_lines = [l for l in narrative.splitlines() if l.strip()]
        if not narr_lines or narr_lines[0].strip() != NARRATIVE_MARKER:
            errors.append("one-pager: g — narrative must start with the model-written marker")
            prose = narr_lines
        else:
            prose = narr_lines[1:]
        if len(prose) > NARRATIVE_MAX_LINES:
            errors.append(f"one-pager: g — narrative is {len(prose)} lines, limit {NARRATIVE_MAX_LINES}")
        for line in prose:
            for pattern in FACT_TOKEN_RES:
                for token in pattern.findall(line):
                    if token not in above:
                        errors.append(f"one-pager: g — narrative states a fact absent above: {token}")

    for line in body:
        for hit in ABS_PATH_RE.findall(line):
            if hit and hit != "<path>":
                errors.append(f"one-pager: j — absolute path in output: {hit[:40]}")

    if companion is not None:
        try:
            rendered = render_markdown(companion)
        except (KeyError, TypeError, IndexError):
            errors.append("one-pager: h — companion JSON does not render")
        else:
            facts_part = text.split("\n## Narrative", 1)[0].rstrip("\n") + "\n"
            if rendered != facts_part:
                errors.append("one-pager: h — companion JSON does not match the Markdown")
    return errors


def validate_json(obj):
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
        return [f"one-pager: i — schema must be {SCHEMA}"]
    try:
        text = render_markdown(obj)
    except (KeyError, TypeError, IndexError) as exc:
        return [f"one-pager: i — facts do not render: {exc}"]
    return validate_text(text, companion=obj)


# ---------------------------------------------------------------------------
# commands


def cmd_generate(args):
    if args.repos:
        mode = "all"
        repos = [repo_root(p) for p in args.repos]
    else:
        mode = "repo"
        repos = [repo_root(args.repo or ".")]

    previous_path = args.previous
    if previous_path is None:
        if mode == "repo":
            folder = repos[0] / "thoughts" / "shared" / ONE_PAGER_ROOT
            pattern = f"*-{slugify(repos[0].name)}.md"
        else:
            folder = rpa_home() / ONE_PAGER_ROOT
            pattern = "*-all.md"
        if folder.is_dir():
            pages = sorted(folder.glob(pattern))
            previous_path = pages[-1] if pages else None
    previous = read_previous(previous_path)
    known = (previous or {}).get("repos", {})

    entries = [
        collect_repo_facts(repo, args.since, known.get(slugify(repo.name)))
        for repo in repos
    ]
    facts = {"schema": SCHEMA, "mode": mode, "generated_at": PLACEHOLDER, "repos": entries}

    text = allocate_and_bound(facts)
    stamp = preserved_generated_at(previous, text) or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    facts["generated_at"] = stamp
    text = text.replace(PLACEHOLDER, stamp)

    date = head_date(repos[0]) if mode == "repo" else max(head_date(r) for r in repos)
    out = Path(args.out).expanduser().absolute() if args.out else None
    if out is None and args.write:
        out = default_out(mode, repos, date)
    if out is not None:
        if mode == "repo":
            if not _inside(out.parent, repos[0]):
                raise UsageError(f"--out must resolve inside the repository: {out.name}")
        else:
            for repo in repos:
                if _inside(out.parent, repo):
                    raise UsageError(f"--out must resolve outside every listed repository: {out.name}")
        _atomic_write(out, text)
        if args.json:
            _atomic_write(out.with_suffix(".json"), facts_json(facts) + "\n")
        print(out)
        return 0

    sys.stdout.write(facts_json(facts) + "\n" if args.json else text)
    return 0


def cmd_validate(args):
    path = Path(args.file)
    if not path.is_file():
        raise UsageError(f"not a file: {path}")
    if path.suffix == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"one-pager: i — invalid JSON: {exc}")
            return 1
        errors = validate_json(obj)
    else:
        companion = None
        extra = []
        sibling = path.with_suffix(".json")
        if sibling.is_file():
            try:
                companion = json.loads(sibling.read_text(encoding="utf-8"))
            except ValueError as exc:
                companion = None
                extra.append(f"one-pager: h — companion JSON is not valid JSON: {exc}")
        errors = extra + validate_text(
            path.read_text(encoding="utf-8", errors="replace"), companion
        )
    for error in errors:
        print(error)
    return 1 if errors else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="onepager.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="render a digest")
    gen.add_argument("--repo", help="repository path (default: cwd)")
    gen.add_argument("--repos", nargs="+", help="cross-repository mode")
    gen.add_argument("--since", help="ISO date, git ref, or 'last' (default)")
    gen.add_argument("--json", action="store_true", help="canonical JSON")
    gen.add_argument("--write", action="store_true", help="write the default path")
    gen.add_argument("--out", help="write exactly this path")
    gen.add_argument("--previous", help="previous digest for the fixed point")
    gen.set_defaults(func=cmd_generate)

    val = sub.add_parser("validate", help="check a digest against the contract")
    val.add_argument("file")
    val.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as exc:
        print(f"one-pager: usage — {exc}", file=sys.stderr)
        return 2
    except GenerateError as exc:
        print(f"one-pager: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
