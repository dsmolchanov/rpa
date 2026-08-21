#!/usr/bin/env python3
"""TDD evidence kernel: predict -> run -> grade -> persist.

Stdlib only; imports nothing outside this directory. The grammar, record
model, lease/repair protocol, phase machine, and export schema are defined
once in ../references/evidence-contract.md — this file implements them.

Subcommands: begin, run, status, checkpoint, export.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fnmatch
import glob as _glob
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = 1
WORKFLOW_DEFAULT = "tdd"
RUN_ID_RE = re.compile(r"^tdd-\d{8}-\d{6}-[0-9a-f]{8}-[0-9a-f]{6}$")
REF_RE = re.compile(r"^(tdd-\d{8}-\d{6}-[0-9a-f]{8}-[0-9a-f]{6})#([1-9]\d*)$")
PHASES = ("baseline", "red", "green", "refactor", "final")
PHASE_RANK = {p: i for i, p in enumerate(PHASES)}
CASE_PHASES = ("red", "green", "refactor")
ACHIEVED_VALUES = ("red", "green", "refactored-green", "blocked")
OUTCOMES = ("PASS", "PENDING", "SURPRISE", "STALE", "ERROR", "TIMEOUT", "INTERRUPTED")
OUTCOME_RANK = {o: i for i, o in enumerate(OUTCOMES)}
EXIT_FOR_OUTCOME = {"PASS": 0, "PENDING": 0, "SURPRISE": 1, "ERROR": 2,
                    "STALE": 3, "TIMEOUT": 4, "INTERRUPTED": 130}
DEFAULT_TAIL_BYTES = 8192
DEFAULT_TIMEOUT = 900
LEASE_GRACE_SECONDS = 60
CAPSULE_MAX_LINES = 120
CAPSULE_MAX_BYTES = 16 * 1024
REPORT_TOKEN = "{report}"

# --------------------------------------------------------------------------
# errors / output helpers


class UsageError(Exception):
    """Exit 2: usage, containment, store, or state error. Nothing was written."""


def _eprint(msg: str) -> None:
    print(f"evidence: {msg}", file=sys.stderr)


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def receipt_of(record: dict) -> str:
    stripped = {k: v for k, v in record.items() if k != "receipt"}
    return sha256_bytes(canonical_json(stripped).encode("utf-8"))[:12]


def ledger_digest(records: list, through_n: int) -> str:
    h = hashlib.sha256()
    for rec in records:
        if rec.get("n", 0) <= through_n:
            h.update(canonical_json(rec).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


# --------------------------------------------------------------------------
# sanitisation (applied BEFORE any persistence)

_SECRET_KEYS = r"(?:api[_-]?key|token|secret|password|passwd|pwd)"
_REDACT_PATTERNS = [
    re.compile(r"(?i)" + _SECRET_KEYS + r"\s*[=:]\s*\S+"),
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
_SPLIT_FLAG_RE = re.compile(r"(?i)^--?" + _SECRET_KEYS + r"$")
_SPLIT_INLINE_RE = re.compile(r"(?i)(--?" + _SECRET_KEYS + r")\s+\S+")
REDACTED = "[REDACTED]"


def redact(text) -> str:
    if text is None:
        return text
    out = str(text)
    out = _SPLIT_INLINE_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", out)
    for pat in _REDACT_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def redact_argv(argv: list) -> list:
    out = []
    redact_next = False
    for item in argv:
        if redact_next:
            out.append(REDACTED)
            redact_next = False
            continue
        if _SPLIT_FLAG_RE.match(item):
            out.append(item)
            redact_next = True
            continue
        out.append(redact(item))
    return out


# --------------------------------------------------------------------------
# git / repo helpers


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, check=check)


_REPO_ROOT: Path | None = None


def repo_root() -> Path:
    global _REPO_ROOT
    if _REPO_ROOT is None:
        try:
            out = _git("rev-parse", "--show-toplevel").stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise UsageError("not inside a git repository")
        _REPO_ROOT = Path(os.path.realpath(out))
    return _REPO_ROOT


def git_head() -> str:
    res = _git("rev-parse", "HEAD", cwd=repo_root(), check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def git_branch() -> str:
    res = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root(), check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def contained(path_str: str, what: str = "path") -> Path:
    """Resolve a repo path (relative to the repo root) and require containment."""
    root = repo_root()
    p = Path(path_str)
    candidate = p if p.is_absolute() else root / p
    real = Path(os.path.realpath(candidate))
    if not _is_relative_to(real, root):
        raise UsageError(f"{what} escapes the repository: {path_str}")
    return real


def rel_to_root(path: Path) -> str:
    return Path(os.path.realpath(path)).relative_to(repo_root()).as_posix()


# --------------------------------------------------------------------------
# store layout


def store_root() -> Path:
    root = repo_root()
    override = os.environ.get("RPA_EVIDENCE_DIR")
    if override:
        real = Path(os.path.realpath(override))
        if real == root or _is_relative_to(real, root) or _is_relative_to(root, real):
            raise UsageError(
                "RPA_EVIDENCE_DIR must resolve outside the repository "
                "(not the root, an ancestor, or a descendant)")
        return real
    return root / ".rpa" / "evidence"


def ensure_store_ignored() -> Path:
    store = store_root()
    store.mkdir(parents=True, exist_ok=True)
    (store / "runs").mkdir(exist_ok=True)
    ignore = store / ".gitignore"
    if ignore.exists():
        if ignore.read_text(encoding="utf-8") != "*\n":
            raise UsageError(f"{ignore} exists with foreign content; refusing to overwrite")
    else:
        ignore.write_text("*\n", encoding="utf-8")
    return store


def valid_run_id(s: str) -> bool:
    return bool(s) and bool(RUN_ID_RE.match(s))


def store_paths(run_id: str) -> dict:
    if not valid_run_id(run_id):
        raise UsageError(f"invalid run id: {run_id!r}")
    store = store_root()
    run_dir = store / "runs" / run_id
    real = Path(os.path.realpath(run_dir))
    if not _is_relative_to(real, Path(os.path.realpath(store))):
        raise UsageError("run path escapes the store")
    return {
        "store": store,
        "run": run_dir,
        "events": run_dir / "events.jsonl",
        "index": run_dir / "run.json",
        "meta": run_dir / "run.meta.json",
        "reports": run_dir / "reports",
        "capsules": run_dir / "capsules",
        "lease": store / "active.json",
        "lock": store / "lock",
        "current": store / "current",
    }


def current_run_id() -> str:
    cur = store_root() / "current"
    if not cur.is_file():
        raise UsageError("no current run; use `begin --plan <path>` or `--run <id>`")
    value = cur.read_text(encoding="utf-8").strip()
    if not valid_run_id(value):
        raise UsageError(f"`current` holds an invalid run id: {value!r}")
    return value


@contextlib.contextmanager
def store_lock():
    path = store_root() / "lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        if os.name == "nt":  # pragma: no cover - exercised only on Windows
            import msvcrt
            fh.seek(0)
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":  # pragma: no cover
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# ledger


def load_records(run_id: str) -> tuple[list, str | None]:
    paths = store_paths(run_id)
    if not paths["events"].is_file():
        return [], None
    raw = paths["events"].read_bytes()
    records, partial = [], None
    lines = raw.split(b"\n")
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            if idx == len(lines) - 1 or all(not l.strip() for l in lines[idx + 1:]):
                partial = line.decode("utf-8", "replace")
            else:
                raise UsageError(f"corrupt ledger line {idx + 1} in {paths['events']}")
    return records, partial


def append_record(run_id: str, record: dict) -> None:
    paths = store_paths(run_id)
    paths["run"].mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    with open(paths["events"], "ab") as fh:
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def _truncate_partial(run_id: str) -> None:
    paths = store_paths(run_id)
    if not paths["events"].is_file():
        return
    raw = paths["events"].read_bytes()
    if not raw or raw.endswith(b"\n"):
        return
    cut = raw.rfind(b"\n")
    with open(paths["events"], "wb") as fh:
        fh.write(raw[:cut + 1] if cut >= 0 else b"")
        fh.flush()
        os.fsync(fh.fileno())


def pair_records(records: list) -> dict:
    """n -> {"checkpoint": rec} | {"intent": rec, "terminal": rec|None}."""
    out: dict = {}
    for rec in records:
        n = rec.get("n")
        kind = rec.get("kind")
        slot = out.setdefault(n, {})
        if kind == "checkpoint":
            slot["checkpoint"] = rec
        elif kind == "started":
            slot["intent"] = rec
        else:
            slot["terminal"] = rec
    return out


def next_n(records: list) -> int:
    return max((r.get("n", 0) for r in records), default=0) + 1


def last_checkpoint(records: list) -> dict | None:
    cps = [r for r in records if r.get("kind") == "checkpoint"]
    return cps[-1] if cps else None


def phase_state(records: list) -> str:
    cp = last_checkpoint(records)
    return cp["phase"] if cp else "none"


def terminal_records(records: list) -> list:
    return [r for r in records if r.get("kind") in ("finished", "error", "interrupted", "timeout")]


def find_record(records: list, ref: str) -> dict | None:
    for rec in terminal_records(records):
        if rec.get("ref") == ref:
            return rec
    return None


# --------------------------------------------------------------------------
# run meta / derived index


def load_meta(run_id: str) -> dict:
    paths = store_paths(run_id)
    if not paths["meta"].is_file():
        raise UsageError(f"unknown run {run_id} (no run.meta.json)")
    return json.loads(paths["meta"].read_text(encoding="utf-8"))


def derive_index(meta: dict, records: list) -> dict:
    final = None
    for rec in records:
        if rec.get("kind") == "checkpoint" and rec.get("phase") == "final":
            final = rec
    reports = sorted({r.get("report_path") for r in terminal_records(records)
                      if r.get("report_path")})
    return {
        **meta,
        "reports": reports,
        "state": "sealed" if final else "open",
        "achieved": final.get("achieved") if final else None,
        "sealed_at": final.get("at_utc") if final else None,
        "phase": phase_state(records),
        "records": len(records),
    }


def rebuild_index(run_id: str, records: list | None = None) -> dict:
    paths = store_paths(run_id)
    meta = load_meta(run_id)
    if records is None:
        records, _ = load_records(run_id)
    index = derive_index(meta, records)
    _atomic_write(paths["index"], canonical_json(index) + "\n")
    return index


# --------------------------------------------------------------------------
# lease


def read_lease() -> dict | None:
    lease = store_root() / "active.json"
    if not lease.is_file():
        return None
    try:
        return json.loads(lease.read_text(encoding="utf-8"))
    except ValueError:
        return {"corrupt": True}


def write_lease(lease: dict) -> None:
    _atomic_write(store_root() / "active.json", canonical_json(lease) + "\n")


def clear_lease() -> None:
    with contextlib.suppress(FileNotFoundError):
        (store_root() / "active.json").unlink()


def controller_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_group(pid) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        if os.name == "nt":  # pragma: no cover
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
            return
        os.killpg(pid, signal.SIGTERM)
        time.sleep(0.2)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# --------------------------------------------------------------------------
# repair (idempotent; under the lock)


def _interrupted_record(intent: dict, command: str) -> dict:
    rec = dict(intent)
    rec.update({
        "kind": "interrupted",
        "at_utc": now_utc(),
        "controller_pid": None,
        "child_pid": None,
        "exit": None,
        "started_at": intent.get("at_utc"),
        "finished_at": None,
        "stdout_sha256": None, "stdout_bytes": 0, "stdout_tail": "",
        "stderr_sha256": None, "stderr_bytes": 0, "stderr_tail": "",
        "report_sha256": None,
        "post_at": None,
        "claims": [{"text": c["text"], "kind": c.get("kind"), "outcome": "INTERRUPTED",
                    "detail": "recovered by repair"} for c in intent.get("claims", [])],
        "outcome": "INTERRUPTED",
        "recovered_by": {"command": command, "at_utc": now_utc()},
    })
    rec["receipt"] = receipt_of(rec)
    return rec


def repair(run_id: str, command: str) -> dict:
    """Reconcile the store. Raises UsageError when a live lease exists."""
    report = {"recovered": [], "lease_cleared": False, "snapshots_removed": [],
              "partial_truncated": False}
    paths = store_paths(run_id)
    lease = read_lease()
    if lease is not None:
        if lease.get("corrupt"):
            clear_lease()
            report["lease_cleared"] = True
            lease = None
        elif controller_alive(lease.get("controller_pid")):
            raise UsageError(f"execution in progress: {lease.get('ref')}")
    _, partial = load_records(run_id)
    if partial is not None:
        _truncate_partial(run_id)
        report["partial_truncated"] = True
    records, _ = load_records(run_id)
    pairs = pair_records(records)
    # Dead lease for this run, or for another run in the same store.
    if lease is not None:
        lease_run = lease.get("run_id")
        lease_ref = lease.get("ref")
        if lease_run == run_id:
            m = REF_RE.match(lease_ref or "")
            n = int(m.group(2)) if m else None
            slot = pairs.get(n, {})
            if slot.get("intent") and not slot.get("terminal"):
                _kill_group(lease.get("child_pid"))
                rec = _interrupted_record(slot["intent"], command)
                append_record(run_id, rec)
                report["recovered"].append(rec["ref"])
            clear_lease()
            report["lease_cleared"] = True
        elif valid_run_id(lease_run or "") and (store_paths(lease_run)["events"]).is_file():
            other, _ = load_records(lease_run)
            o_pairs = pair_records(other)
            m = REF_RE.match(lease_ref or "")
            n = int(m.group(2)) if m else None
            slot = o_pairs.get(n, {})
            if slot.get("intent") and not slot.get("terminal"):
                _kill_group(lease.get("child_pid"))
                rec = _interrupted_record(slot["intent"], command)
                append_record(lease_run, rec)
                report["recovered"].append(rec["ref"])
                with contextlib.suppress(UsageError):
                    rebuild_index(lease_run)
            clear_lease()
            report["lease_cleared"] = True
        else:
            clear_lease()
            report["lease_cleared"] = True
        records, _ = load_records(run_id)
        pairs = pair_records(records)
    # Dangling intents without a lease.
    for n in sorted(k for k in pairs if k is not None):
        slot = pairs[n]
        if slot.get("intent") and not slot.get("terminal") and "checkpoint" not in slot:
            rec = _interrupted_record(slot["intent"], command)
            append_record(run_id, rec)
            report["recovered"].append(rec["ref"])
    records, _ = load_records(run_id)
    # Orphan snapshots.
    named = {r.get("capsule_path") for r in records if r.get("kind") == "checkpoint"}
    if paths["capsules"].is_dir():
        for snap in sorted(paths["capsules"].glob("*.md")):
            if snap.name == "current.md":
                continue
            if snap.name not in named:
                snap.unlink()
                report["snapshots_removed"].append(snap.name)
        for tmp in paths["capsules"].glob("*.tmp"):
            tmp.unlink()
    rebuild_index(run_id, records)
    _regenerate_current(run_id, records)
    return report


def _regenerate_current(run_id: str, records: list) -> None:
    paths = store_paths(run_id)
    cp = last_checkpoint(records)
    paths["capsules"].mkdir(parents=True, exist_ok=True)
    current = paths["capsules"] / "current.md"
    if cp is None:
        with contextlib.suppress(FileNotFoundError):
            current.unlink()
        return
    snap = paths["capsules"] / cp["capsule_path"]
    if snap.is_file():
        _atomic_write(current, snap.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# worktree snapshots / scopes / envelope


def _status_paths() -> list:
    root = repo_root()
    res = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=root)
    items = res.stdout.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(items):
        entry = items[i]
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        paths.append(path)
        if code[0] in "RC" and i < len(items):
            paths.append(items[i])  # original path of a rename/copy
            i += 1
    return paths


def _under_store(rel: str) -> bool:
    store = store_root()
    root = repo_root()
    if not _is_relative_to(store, root):
        return False
    prefix = store.relative_to(root).as_posix().rstrip("/") + "/"
    return rel.startswith(prefix) or rel == prefix.rstrip("/")


def worktree_snapshot() -> dict:
    root = repo_root()
    snap: dict[str, str] = {}
    for rel in _status_paths():
        if _under_store(rel):
            continue
        p = root / rel
        if p.is_file():
            snap[rel] = sha256_file(p)
        elif p.is_symlink():
            snap[rel] = "symlink:" + sha256_bytes(os.readlink(p).encode())
        else:
            snap[rel] = "deleted"
    return snap


def worktree_digest(snap: dict) -> str:
    h = hashlib.sha256()
    for rel in sorted(snap):
        h.update(f"{rel}\0{snap[rel]}\n".encode("utf-8"))
    return h.hexdigest()


def normalize_globs(spec: str) -> list:
    globs = sorted({g.strip() for g in spec.split(",") if g.strip()})
    for g in globs:
        if os.path.isabs(g) or ".." in Path(g).parts:
            raise UsageError(f"scope glob must be repo-relative without '..': {g}")
    return globs


def scope_digest(globs: list) -> tuple[list, str]:
    root = repo_root()
    matched: set[str] = set()
    for g in globs:
        for hit in _glob.glob(str(root / g), recursive=True):
            hp = Path(hit)
            if hp.is_file():
                real = Path(os.path.realpath(hp))
                if not _is_relative_to(real, root):
                    raise UsageError(f"scope match escapes the repository: {hit}")
                rel = hp.relative_to(root).as_posix()
                if not _under_store(rel):
                    matched.add(rel)
    paths = sorted(matched)
    h = hashlib.sha256()
    for rel in paths:
        h.update(f"{rel}\0{sha256_file(root / rel)}\n".encode("utf-8"))
    return paths, h.hexdigest()


def compute_scopes(scope_args: list) -> dict:
    scopes: dict = {}
    for item in scope_args or []:
        if "=" not in item:
            raise UsageError(f"--scope needs name=glob[,glob]: {item}")
        name, spec = item.split("=", 1)
        name = name.strip()
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            raise UsageError(f"invalid scope name: {name!r}")
        globs = normalize_globs(spec)
        if not globs:
            raise UsageError(f"empty scope: {item}")
        paths, digest = scope_digest(globs)
        if not paths:
            raise UsageError(f"scope {name!r} matched no files: {','.join(globs)}")
        scopes[name] = {"globs": globs, "paths": len(paths), "digest": digest}
    return scopes


def current_state_triplet(meta: dict) -> dict:
    plan_path = repo_root() / meta["plan_path"]
    return {
        "head": git_head(),
        "branch": git_branch(),
        "plan_sha256": sha256_file(plan_path) if plan_path.is_file() else None,
    }


def envelope_of(own_scopes: dict, required: dict | None) -> dict:
    """Own scopes ∪ the required record's stored envelope (never narrowed)."""
    env = {"scopes": dict(own_scopes)}
    if required is not None:
        inherited = (required.get("envelope") or {}).get("scopes", {})
        for name, spec in inherited.items():
            key = name
            if key in env["scopes"] and env["scopes"][key].get("globs") != spec.get("globs"):
                key = f"{name}@{required['ref']}"
            env["scopes"].setdefault(key, spec)
        env["head"] = (required.get("envelope") or {}).get("head", required.get("at", {}).get("head"))
        env["branch"] = (required.get("envelope") or {}).get("branch", required.get("at", {}).get("branch"))
        env["plan_sha256"] = (required.get("envelope") or {}).get(
            "plan_sha256", required.get("at", {}).get("plan_sha256"))
    return env


def check_envelope(envelope: dict, meta: dict) -> list:
    """Recompute the envelope against the tree; return a list of drift strings."""
    drift = []
    cur = current_state_triplet(meta)
    for key in ("head", "branch", "plan_sha256"):
        if envelope.get(key) is not None and envelope.get(key) != cur[key]:
            drift.append(f"{key} changed")
    for name, spec in (envelope.get("scopes") or {}).items():
        paths, digest = scope_digest(spec["globs"])
        if digest != spec.get("digest"):
            drift.append(f"scope {name} changed ({len(paths)} files)")
    return drift


# --------------------------------------------------------------------------
# claims


class Claim:
    __slots__ = ("text", "kind", "arg", "value")

    def __init__(self, text, kind, arg=None, value=None):
        self.text, self.kind, self.arg, self.value = text, kind, arg, value

    def machine_checkable(self) -> bool:
        return self.kind != "manual"


_QUOTED = r'"((?:[^"\\]|\\.)*)"'


def _unq(s: str) -> str:
    return bytes(s, "utf-8").decode("unicode_escape") if "\\" in s else s


def parse_claim(text: str) -> Claim:
    t = text.strip()
    m = re.fullmatch(r"exit\s*==\s*(\d+)", t)
    if m:
        return Claim(t, "exit_eq", value=int(m.group(1)))
    if re.fullmatch(r"exit\s*!=\s*0", t):
        return Claim(t, "exit_ne0")
    m = re.fullmatch(r"(stdout|stderr)\s+contains\s+" + _QUOTED, t)
    if m:
        return Claim(t, "contains", arg=m.group(1), value=_unq(m.group(2)))
    if re.fullmatch(r"diff\s+none", t):
        return Claim(t, "diff_none")
    m = re.fullmatch(r"diff\s+within\s+(\S+)", t)
    if m:
        return Claim(t, "diff_within", value=normalize_globs(m.group(1)))
    m = re.fullmatch(r"path\s+(\S+)\s+(unchanged|created|absent)", t)
    if m:
        if os.path.isabs(m.group(1)) or ".." in Path(m.group(1)).parts:
            raise UsageError(f"path claim must be repo-relative without '..': {t}")
        return Claim(t, "path", arg=m.group(1), value=m.group(2))
    m = re.fullmatch(r"test\s+(\S+)\s+pass", t)
    if m:
        return Claim(t, "test_pass", arg=m.group(1))
    m = re.fullmatch(r"test\s+(\S+)\s+fail-with\s+" + _QUOTED, t)
    if m:
        return Claim(t, "test_fail_with", arg=m.group(1), value=_unq(m.group(2)))
    m = re.fullmatch(r"manual\s+" + _QUOTED, t)
    if m:
        return Claim(t, "manual", value=_unq(m.group(1)))
    raise UsageError(f"unparseable claim: {text!r}")


def parse_junit(path: Path) -> list:
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise UsageError(f"cannot parse JUnit report {path}: {exc}")
    cases = []
    for tc in tree.getroot().iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        full = f"{classname}.{name}" if classname else name
        status = "pass"
        message = ""
        for tag in ("failure", "error", "skipped"):
            child = tc.find(tag)
            if child is not None:
                status = tag
                message = (child.get("message") or "") + "\n" + (child.text or "")
                break
        cases.append({"id": full, "status": status, "message": message})
    return cases


def grade(claim: Claim, ctx: dict) -> tuple[str, str]:
    k = claim.kind
    if k == "manual":
        return "PENDING", claim.value
    if k == "exit_eq":
        ok = ctx["exit"] == claim.value
        return ("PASS" if ok else "SURPRISE"), f"exit={ctx['exit']}"
    if k == "exit_ne0":
        ok = ctx["exit"] is not None and ctx["exit"] != 0
        return ("PASS" if ok else "SURPRISE"), f"exit={ctx['exit']}"
    if k == "contains":
        found = ctx["contains"].get((claim.arg, claim.value), False)
        return ("PASS" if found else "SURPRISE"), f"{claim.arg} {'contains' if found else 'lacks'} literal"
    if k in ("diff_none", "diff_within"):
        changed = ctx["changed_paths"]
        if k == "diff_none":
            ok = not changed
            return ("PASS" if ok else "SURPRISE"), ("no changes" if ok else "changed: " + ", ".join(changed[:20]))
        outside = [p for p in changed if not any(fnmatch.fnmatch(p, g) for g in claim.value)]
        ok = not outside
        return ("PASS" if ok else "SURPRISE"), ("within scope" if ok else "outside: " + ", ".join(outside[:20]))
    if k == "path":
        before = ctx["path_before"].get(claim.arg)
        after = ctx["path_after"].get(claim.arg)
        if claim.value == "unchanged":
            ok = before is not None and before == after
        elif claim.value == "created":
            ok = before is None and after is not None
        else:
            ok = after is None
        return ("PASS" if ok else "SURPRISE"), f"before={'present' if before else 'absent'} after={'present' if after else 'absent'}"
    if k in ("test_pass", "test_fail_with"):
        if ctx.get("report_error"):
            return "ERROR", ctx["report_error"]
        matches = [c for c in ctx["junit"] if claim.arg in c["id"]]
        if len(matches) != 1:
            return "ERROR", f"selector matched {len(matches)} testcases" + (
                ": " + ", ".join(c["id"] for c in matches[:5]) if matches else "")
        tc = matches[0]
        if k == "test_pass":
            ok = ctx["exit"] == 0 and tc["status"] == "pass"
            return ("PASS" if ok else "SURPRISE"), f"exit={ctx['exit']} testcase={tc['status']}"
        ok = (ctx["exit"] is not None and ctx["exit"] != 0 and tc["status"] == "failure"
              and claim.value in tc["message"])
        return ("PASS" if ok else "SURPRISE"), f"exit={ctx['exit']} testcase={tc['status']}" + (
            "" if claim.value in tc["message"] else " literal absent")
    return "ERROR", f"unknown claim kind {k}"


# --------------------------------------------------------------------------
# execution


class StreamReader(threading.Thread):
    def __init__(self, stream, literals: list, tail_bytes: int):
        super().__init__(daemon=True)
        self.stream = stream
        self.hash = hashlib.sha256()
        self.count = 0
        self.tail = bytearray()
        self.tail_bytes = tail_bytes
        self.literals = {lit: {"bytes": lit.encode("utf-8"), "found": False, "carry": b""}
                         for lit in literals}

    def run(self):
        while True:
            chunk = self.stream.read(65536)
            if not chunk:
                break
            self.hash.update(chunk)
            self.count += len(chunk)
            self.tail.extend(chunk)
            if len(self.tail) > self.tail_bytes:
                del self.tail[:-self.tail_bytes]
            for state in self.literals.values():
                if state["found"]:
                    continue
                window = state["carry"] + chunk
                if state["bytes"] in window:
                    state["found"] = True
                keep = len(state["bytes"]) - 1
                state["carry"] = window[-keep:] if keep > 0 else b""
        self.stream.close()

    def tail_text(self) -> str:
        return bytes(self.tail).decode("utf-8", "replace")


class ExecResult:
    def __init__(self):
        self.exit = None
        self.pid = None
        self.started_at = None
        self.finished_at = None
        self.timed_out = False
        self.interrupted = False
        self.out = None
        self.err = None
        self.start_error = None


def execute(argv: list, timeout: int, tail_bytes: int, literals: dict, lease: dict) -> ExecResult:
    res = ExecResult()
    res.started_at = now_utc()
    popen_kwargs = dict(cwd=str(repo_root()), env=os.environ.copy(), stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **popen_kwargs)
    except (OSError, ValueError) as exc:
        res.start_error = str(exc)
        res.finished_at = now_utc()
        return res
    res.pid = proc.pid
    lease["child_pid"] = proc.pid
    write_lease(lease)
    res.out = StreamReader(proc.stdout, literals.get("stdout", []), tail_bytes)
    res.err = StreamReader(proc.stderr, literals.get("stderr", []), tail_bytes)
    res.out.start()
    res.err.start()
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            res.timed_out = True
            _terminate(proc)
    except KeyboardInterrupt:
        res.interrupted = True
        _terminate(proc)
    res.out.join()
    res.err.join()
    res.exit = proc.returncode
    res.finished_at = now_utc()
    return res


def _terminate(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":  # pragma: no cover
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
    except (ProcessLookupError, PermissionError):
        pass
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


# --------------------------------------------------------------------------
# reports


def resolve_report(arg: str | None, run_id: str, index: dict) -> tuple[Path | None, bool]:
    """Returns (path, run_owned)."""
    if arg is None:
        return None, False
    paths = store_paths(run_id)
    if "/" not in arg and os.sep not in arg and arg not in ("", ".", ".."):
        return paths["reports"] / arg, True
    real = contained(arg, "--report")
    rel = rel_to_root(real)
    tracked = _git("ls-files", "--error-unmatch", "--", rel, cwd=repo_root(), check=False)
    if tracked.returncode == 0:
        raise UsageError(f"--report refuses a git-tracked file: {rel}")
    if real.exists() and rel not in (index.get("reports") or []) \
            and not _is_relative_to(real, Path(os.path.realpath(paths["reports"]))):
        raise UsageError(f"--report target exists and is not owned by this run: {rel}")
    return real, True


def substitute_report(argv: list, report: Path | None) -> list:
    if report is None:
        return list(argv)
    return [a.replace(REPORT_TOKEN, str(report)) for a in argv]


# --------------------------------------------------------------------------
# phase machine


_ADMITTED_RUN = {
    "none": {"baseline"},
    "baseline": {"baseline", "red"},
    "red": {"red", "green", "final"},
    "green": {"green", "refactor", "final"},
    "refactor": {"refactor", "final"},
    "final": set(),
}


def admitted_phase(state: str, phase: str) -> bool:
    return phase in _ADMITTED_RUN.get(state, set())


def admitted_checkpoint(state: str, phase: str) -> bool:
    if state == "final":
        return False
    if phase == "final":
        return state != "none"
    if state == "none":
        return phase == "baseline"
    return PHASE_RANK[phase] in (PHASE_RANK[state], PHASE_RANK[state] + 1) and phase != "final"


def unclosed_phases(records: list, checkpoint_phase: str) -> list:
    """Phases (other than the one being checkpointed) whose last attempt is
    newer than their last checkpoint. For a non-final checkpoint only earlier
    phases are considered; `checkpoint final` considers every other phase."""
    last_cp: dict = {}
    last_attempt: dict = {}
    for rec in records:
        if rec.get("kind") == "checkpoint":
            last_cp[rec["phase"]] = rec["n"]
        elif rec.get("kind") in ("finished", "error", "interrupted", "timeout"):
            last_attempt[rec["phase"]] = rec["n"]
    out = []
    for phase, n in last_attempt.items():
        if phase == checkpoint_phase:
            continue
        if checkpoint_phase != "final" and PHASE_RANK[phase] > PHASE_RANK[checkpoint_phase]:
            continue
        if last_cp.get(phase, -1) < n:
            out.append(phase)
    return sorted(out, key=lambda p: PHASE_RANK[p])


# --------------------------------------------------------------------------
# capsule


def _fresh(rec: dict, meta: dict) -> bool:
    env = rec.get("envelope") or {}
    if not env.get("scopes") and env.get("head") is None:
        return False
    return not check_envelope(env, meta)


def build_capsule(records: list, meta: dict, extras: dict | None = None) -> str:
    extras = extras or {}
    cur = current_state_triplet(meta)
    terminals = terminal_records(records)
    state = phase_state(records)
    head_n = next_n(records) - 1
    lines = []
    lines.append(f"# Capsule {meta['id']}")
    lines.append("")
    lines.append("## Run/Phase")
    lines.append(f"- run: {meta['id']}")
    lines.append(f"- state: {state}")
    lines.append(f"- branch: {cur['branch']} (begin: {meta['branch']})")
    lines.append(f"- head: {cur['head'][:12]} (begin: {meta['head'][:12]})")
    lines.append(f"- ledger_head: {head_n}")
    lines.append(f"- ledger_sha256: {ledger_digest(records, head_n)}")
    verified, open_items, blocked, surprises = [], [], [], []
    last_by_case: dict = {}
    for rec in terminals:
        if rec.get("phase") in ("red", "green", "refactor", "final"):
            last_by_case[(rec.get("case"), rec.get("phase"))] = rec
    for rec in terminals:
        label = f"{rec['ref']} receipt {rec.get('receipt')} {rec.get('phase')}/{rec.get('case') or '-'}"
        if rec.get("outcome") == "PASS":
            if _fresh(rec, meta):
                verified.append(f"- {label}: " + "; ".join(c['text'] for c in rec.get('claims', []) if c.get('outcome') == 'PASS'))
            else:
                open_items.append(f"- {label}: stale envelope (re-verify)")
            for c in rec.get("claims", []):
                if c.get("outcome") == "PENDING":
                    open_items.append(f"- {label}: pending manual: {c['text']}")
        elif rec.get("outcome") == "SURPRISE":
            surprises.append(f"- {label}: " + "; ".join(
                f"{c['text']} -> {c['outcome']} ({c.get('detail','')})" for c in rec.get("claims", [])
                if c.get("outcome") == "SURPRISE"))
        elif rec.get("outcome") == "STALE":
            open_items.append(f"- {label}: STALE — " + "; ".join(
                c.get("detail", "") for c in rec.get("claims", [])[:1]) )
    for (case, phase), rec in last_by_case.items():
        if rec.get("outcome") in ("ERROR", "TIMEOUT", "INTERRUPTED"):
            blocked.append(f"- {rec['ref']} {phase}/{case or '-'}: last attempt {rec['outcome']}")
    for item in extras.get("open", []) or []:
        open_items.append(f"- {redact(item)}")
    for item in extras.get("blocked", []) or []:
        blocked.append(f"- {redact(item)}")
    na = [f"- {redact(i)}" for i in (extras.get("not_applicable", []) or [])]
    lines += ["", "## Verified"] + (verified or ["- none"])
    lines += ["", "## Open"] + (open_items or ["- none"])
    lines += ["", "## Blocked"] + (blocked or ["- none"])
    lines += ["", "## Not applicable"] + (na or ["- none"])
    lines += ["", "## Surprises"] + (surprises or ["- none"])
    drift = []
    if cur["head"] != meta["head"]:
        drift.append(f"- HEAD moved since begin: {meta['head'][:12]} -> {cur['head'][:12]}")
    if cur["branch"] != meta["branch"]:
        drift.append(f"- branch changed: {meta['branch']} -> {cur['branch']}")
    if cur["plan_sha256"] != meta["plan_sha256"]:
        drift.append("- plan changed since begin")
    dirty = sorted(worktree_snapshot())
    if dirty:
        drift.append(f"- dirty paths ({len(dirty)}): " + ", ".join(dirty[:15]) + (" …" if len(dirty) > 15 else ""))
    lines += ["", "## State drift"] + (drift or ["- none"])
    nxt = extras.get("next")
    if not nxt:
        nxt = _derive_next(records, meta, state)
    lines += ["", "## Next", f"- {redact(nxt)}"]
    return _bound_capsule(lines)


def _derive_next(records: list, meta: dict, state: str) -> str:
    terminals = terminal_records(records)
    reds = {r["case"]: r for r in terminals if r.get("phase") == "red" and r.get("outcome") == "PASS"}
    greens = {r["case"]: r for r in terminals if r.get("phase") == "green" and r.get("outcome") == "PASS"}
    for case, rec in reds.items():
        if not _fresh(rec, meta):
            return f"re-run Red for {case} (envelope stale)"
    for case in reds:
        if case not in greens:
            return f"run Green for {case}"
    if state == "none":
        return "checkpoint baseline"
    if state == "baseline":
        return "run Red for the first planned case"
    if state == "green":
        return "refactor or checkpoint final"
    if state == "final":
        return "run is sealed; export"
    return "continue the current phase"


def _bound_capsule(lines: list) -> str:
    # Truncate oldest-first inside sections: drop the earliest bullet lines of
    # the longest sections until within bounds.
    def size(ls):
        return len(ls), len("\n".join(ls).encode("utf-8"))
    n, b = size(lines)
    while n > CAPSULE_MAX_LINES or b > CAPSULE_MAX_BYTES:
        # find section with most bullets
        sections: dict = {}
        current = None
        for idx, line in enumerate(lines):
            if line.startswith("## "):
                current = idx
                sections[current] = []
            elif current is not None and line.startswith("- ") and not line.startswith("- [+"):
                sections[current].append(idx)
        if not sections:
            break
        target = max(sections, key=lambda k: len(sections[k]))
        bullets = sections[target]
        if len(bullets) <= 1:
            break
        drop = bullets[0]
        marker_idx = drop
        if lines[drop + 1].startswith("- [+") if drop + 1 < len(lines) else False:
            pass
        # merge with existing marker
        if marker_idx + 1 < len(lines) and lines[marker_idx + 1].startswith("- [+"):
            m = re.match(r"- \[\+(\d+) older\]", lines[marker_idx + 1])
            count = int(m.group(1)) + 1 if m else 1
            lines[marker_idx + 1] = f"- [+{count} older]"
            del lines[marker_idx]
        else:
            lines[marker_idx] = "- [+1 older]"
        n, b = size(lines)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# commands


def cmd_begin(args) -> int:
    root = repo_root()
    store = ensure_store_ignored()
    if args.resume:
        run_id = args.resume
        if not valid_run_id(run_id):
            raise UsageError(f"invalid run id: {run_id!r}")
        with store_lock():
            meta = load_meta(run_id)
            records, _ = load_records(run_id)
            index = derive_index(meta, records)
            if index["state"] != "open":
                raise UsageError(f"run {run_id} is sealed")
            cur = current_state_triplet(meta)
            if cur["plan_sha256"] != meta["plan_sha256"]:
                raise UsageError("plan changed since the run began; begin a new run")
            if cur["branch"] != meta["branch"]:
                raise UsageError(f"run {run_id} belongs to branch {meta['branch']!r}, current is {cur['branch']!r}")
            _atomic_write(store / "current", run_id + "\n")
            rebuild_index(run_id, records)
        print(f"run={run_id} resumed state={index['phase']}")
        return 0
    if not args.plan:
        raise UsageError("begin needs --plan <path> or --resume <run-id>")
    plan = contained(args.plan, "--plan")
    if not plan.is_file():
        raise UsageError(f"plan not found: {args.plan}")
    plan_sha = sha256_file(plan)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"tdd-{stamp}-{plan_sha[:8]}-{secrets.token_hex(3)}"
    meta = {
        "id": run_id,
        "nonce": run_id.rsplit("-", 1)[1],
        "plan_path": rel_to_root(plan),
        "plan_sha256": plan_sha,
        "branch": git_branch(),
        "head": git_head(),
        "started_at": now_utc(),
        "workflow": WORKFLOW_DEFAULT,
    }
    with store_lock():
        paths = store_paths(run_id)
        paths["run"].mkdir(parents=True, exist_ok=False)
        paths["reports"].mkdir(exist_ok=True)
        paths["capsules"].mkdir(exist_ok=True)
        _atomic_write(paths["meta"], canonical_json(meta) + "\n")
        paths["events"].touch()
        rebuild_index(run_id, [])
        _atomic_write(store / "current", run_id + "\n")
    print(f"run={run_id} plan={meta['plan_path']} head={meta['head'][:12]} branch={meta['branch']}")
    return 0


def _resolve_run(args) -> str:
    run_id = getattr(args, "run", None) or current_run_id()
    if not valid_run_id(run_id):
        raise UsageError(f"invalid run id: {run_id!r}")
    return run_id


def cmd_run(args) -> int:
    if not args.argv:
        raise UsageError("run needs a command after `--`")
    argv_raw = list(args.argv)
    if argv_raw and argv_raw[0] == "--":
        argv_raw = argv_raw[1:]
    if not argv_raw:
        raise UsageError("run needs a command after `--`")
    phase = args.phase
    if phase not in PHASES:
        raise UsageError(f"--phase must be one of {PHASES}")
    case = args.case
    if phase in CASE_PHASES and not case:
        raise UsageError(f"--case is required for --phase {phase}")
    if case and not re.match(r"^[A-Za-z0-9_.-]+$", case):
        raise UsageError(f"invalid --case: {case!r}")
    claims = [parse_claim(c) for c in (args.expect or [])]
    if not any(c.machine_checkable() for c in claims):
        raise UsageError("at least one machine-checkable --expect is required")
    run_id = _resolve_run(args)
    meta = load_meta(run_id)
    own_scopes = compute_scopes(args.scope)
    if phase == "red":
        for required_scope in ("red_inputs", "plan"):
            if required_scope not in own_scopes:
                raise UsageError(f"--phase red requires --scope {required_scope}=…")
    if args.requires and not REF_RE.match(args.requires):
        raise UsageError(f"invalid --requires ref: {args.requires!r}")
    if args.requires and not args.requires.startswith(run_id + "#"):
        raise UsageError("--requires must reference an event of the same run")
    timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT
    if timeout <= 0:
        raise UsageError("--timeout must be positive")
    tail_bytes = args.tail_bytes if args.tail_bytes is not None else DEFAULT_TAIL_BYTES
    risk = args.risk or "local_verify"
    if risk not in ("local_verify", "local_mutate"):
        raise UsageError("--risk must be local_verify or local_mutate")
    for c in claims:
        if c.kind == "path":
            contained(c.arg, "path claim")
    if any(c.kind in ("test_pass", "test_fail_with") for c in claims) and not args.report:
        raise UsageError("test claims require --report")
    # Sanitised intent payload (raw argv is kept in memory only).
    sanitized_argv = redact_argv(argv_raw)
    because = redact(args.because or "")
    claim_texts = [{"text": redact(c.text), "kind": c.kind} for c in claims]

    with store_lock():
        repair(run_id, "run")
        records, _ = load_records(run_id)
        index = rebuild_index(run_id, records)
        if index["state"] != "open":
            raise UsageError(f"run {run_id} is sealed")
        state = index["phase"]
        if not admitted_phase(state, phase):
            raise UsageError(f"phase {phase!r} is not admitted in state {state!r}")
        cur = current_state_triplet(meta)
        if cur["branch"] != meta["branch"]:
            raise UsageError(f"branch changed: run belongs to {meta['branch']!r}, current is {cur['branch']!r}")
        if cur["plan_sha256"] != meta["plan_sha256"]:
            raise UsageError("plan changed since the run began; begin a new run")
        required = None
        if args.requires:
            required = validate_requires(records, args.requires, phase, case)
        report_path, report_owned = resolve_report(args.report, run_id, index)
        envelope = envelope_of(own_scopes, required)
        if required is None:
            envelope["head"], envelope["branch"], envelope["plan_sha256"] = cur["head"], cur["branch"], cur["plan_sha256"]
        n = next_n(records)
        ref = f"{run_id}#{n}"
        start_token = secrets.token_hex(8)
        intent = {
            "ref": ref, "n": n, "run": run_id, "kind": "started", "at_utc": now_utc(),
            "workflow": args.workflow or meta.get("workflow", WORKFLOW_DEFAULT),
            "phase": phase, "case": case, "because": because, "risk": risk,
            "argv": sanitized_argv, "cwd": ".",
            "claims": claim_texts, "scopes": own_scopes, "envelope": envelope,
            "requires": args.requires, "report_path": (rel_to_root(report_path) if report_path and _is_relative_to(Path(os.path.realpath(report_path)), repo_root()) else (str(report_path) if report_path else None)),
            "timeout": timeout, "start_token": start_token,
            "at": {**cur, "worktree_digest": None},
        }
        # pre-run envelope check (inherited parts)
        drift = check_envelope({k: v for k, v in envelope.items() if k != "scopes"} | {"scopes": {
            k: v for k, v in envelope["scopes"].items() if k not in own_scopes}}, meta) if required else []
        if drift:
            pre_snap = worktree_snapshot()
            intent["at"]["worktree_digest"] = worktree_digest(pre_snap)
            append_record(run_id, intent)
            term = _stale_terminal(intent, drift, "stale before execution")
            append_record(run_id, term)
            rebuild_index(run_id)
            _print_result(term)
            return 3
        pre_snap = worktree_snapshot()
        intent["at"]["worktree_digest"] = worktree_digest(pre_snap)
        path_before = {c.arg: (sha256_file(repo_root() / c.arg) if (repo_root() / c.arg).is_file() else None)
                       for c in claims if c.kind == "path"}
        if report_path is not None and report_owned and report_path.exists():
            report_path.unlink()
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
        append_record(run_id, intent)
        lease = {"run_id": run_id, "ref": ref, "controller_pid": os.getpid(),
                 "start_token": start_token, "started_at_utc": now_utc(), "child_pid": None}
        write_lease(lease)

    argv_exec = substitute_report(argv_raw, report_path)
    literals = {"stdout": [c.value for c in claims if c.kind == "contains" and c.arg == "stdout"],
                "stderr": [c.value for c in claims if c.kind == "contains" and c.arg == "stderr"]}
    result = execute(argv_exec, timeout, tail_bytes, literals, lease)

    post_snap = worktree_snapshot()
    post_cur = current_state_triplet(meta)
    post_drift = check_envelope(envelope, meta)
    path_after = {c.arg: (sha256_file(repo_root() / c.arg) if (repo_root() / c.arg).is_file() else None)
                  for c in claims if c.kind == "path"}
    changed = sorted(p for p in set(pre_snap) | set(post_snap) if pre_snap.get(p) != post_snap.get(p))
    junit, report_error, report_sha = [], None, None
    if report_path is not None:
        if report_path.is_file():
            report_sha = sha256_file(report_path)
            try:
                junit = parse_junit(report_path)
            except UsageError as exc:
                report_error = str(exc)
        else:
            report_error = "report not produced by this run"
    ctx = {
        "exit": result.exit,
        "contains": {("stdout", lit): st["found"] for lit, st in (result.out.literals.items() if result.out else [])}
        | {("stderr", lit): st["found"] for lit, st in (result.err.literals.items() if result.err else [])},
        "changed_paths": changed, "path_before": path_before, "path_after": path_after,
        "junit": junit, "report_error": report_error,
    }
    graded = []
    if result.start_error:
        outcome = "ERROR"
        graded = [{"text": c.text, "kind": c.kind, "outcome": "ERROR", "detail": f"command could not start: {result.start_error}"} for c in claims]
        kind = "error"
    elif result.timed_out:
        outcome, kind = "TIMEOUT", "timeout"
        graded = [{"text": c.text, "kind": c.kind, "outcome": "TIMEOUT", "detail": "not graded"} for c in claims]
    elif result.interrupted:
        outcome, kind = "INTERRUPTED", "interrupted"
        graded = [{"text": c.text, "kind": c.kind, "outcome": "INTERRUPTED", "detail": "not graded"} for c in claims]
    else:
        kind = "finished"
        for c in claims:
            o, d = grade(c, ctx)
            graded.append({"text": c.text, "kind": c.kind, "outcome": o, "detail": redact(d)})
        machine = [g["outcome"] for g in graded if g["kind"] != "manual"]
        outcome = max(machine, key=lambda o: OUTCOME_RANK[o], default="ERROR")
        # PENDING (manual) claims never degrade a run whose machine-checkable
        # claims all PASS; they are carried as open items in the capsule.
        if post_drift:
            outcome = "STALE"
            kind = "finished"
            graded.append({"text": "<envelope>", "kind": "envelope", "outcome": "STALE",
                           "detail": "drift during execution: " + "; ".join(post_drift)})
    terminal = dict(intent)
    terminal.update({
        "kind": kind, "at_utc": now_utc(),
        "controller_pid": os.getpid(), "child_pid": result.pid,
        "exit": result.exit, "started_at": result.started_at, "finished_at": result.finished_at,
        "stdout_sha256": result.out.hash.hexdigest() if result.out else None,
        "stdout_bytes": result.out.count if result.out else 0,
        "stdout_tail": redact(result.out.tail_text()) if result.out else "",
        "stderr_sha256": result.err.hash.hexdigest() if result.err else None,
        "stderr_bytes": result.err.count if result.err else 0,
        "stderr_tail": redact(result.err.tail_text()) if result.err else "",
        "report_sha256": report_sha,
        "post_at": {**post_cur, "worktree_digest": worktree_digest(post_snap)},
        "claims": [{**g, "text": redact(g["text"])} for g in graded],
        "outcome": outcome,
    })
    terminal["receipt"] = receipt_of(terminal)
    with store_lock():
        append_record(run_id, terminal)
        clear_lease()
        rebuild_index(run_id)
    _print_result(terminal)
    return EXIT_FOR_OUTCOME[outcome]


def _stale_terminal(intent: dict, drift: list, why: str) -> dict:
    term = dict(intent)
    term.update({
        "kind": "finished", "at_utc": now_utc(), "controller_pid": os.getpid(), "child_pid": None,
        "exit": None, "started_at": None, "finished_at": None,
        "stdout_sha256": None, "stdout_bytes": 0, "stdout_tail": "",
        "stderr_sha256": None, "stderr_bytes": 0, "stderr_tail": "",
        "report_sha256": None, "post_at": None,
        "claims": [{"text": c["text"], "kind": c.get("kind"), "outcome": "STALE",
                    "detail": f"{why}: " + "; ".join(drift)} for c in intent.get("claims", [])],
        "outcome": "STALE",
    })
    term["receipt"] = receipt_of(term)
    return term


def validate_requires(records: list, ref: str, phase: str, case: str | None) -> dict:
    target = find_record(records, ref)
    if target is None:
        raise UsageError(f"--requires target not found or not terminal: {ref}")
    m = REF_RE.match(ref)
    if int(m.group(2)) >= next_n(records):
        raise UsageError("--requires target must precede this run")
    if target.get("outcome") != "PASS":
        raise UsageError(f"--requires target outcome is {target.get('outcome')}, need PASS")
    if target.get("case") != case:
        raise UsageError(f"--requires target case {target.get('case')!r} != {case!r}")
    expected = {"green": {"red"}, "refactor": {"green", "refactor"}}.get(phase)
    if expected is None or target.get("phase") not in expected:
        raise UsageError(f"--requires: phase {phase!r} cannot require a {target.get('phase')!r} record")
    return target


def _print_result(term: dict) -> None:
    for c in term.get("claims", []):
        print(f"  {c.get('outcome','?'):11} {c.get('text')}  {c.get('detail','')}")
    print(f"event={term['ref']} receipt={term.get('receipt')} outcome={term.get('outcome')}")


def cmd_status(args) -> int:
    run_id = _resolve_run(args)
    meta = load_meta(run_id)
    records, partial = load_records(run_id)
    paths = store_paths(run_id)
    print(build_capsule(records, meta), end="")
    print("## Ledger (last {})".format(args.last))
    for rec in records[-args.last:]:
        kind = rec.get("kind")
        print(f"- {rec['ref']}  {kind:11} {rec.get('outcome') or rec.get('phase'):10} "
              f"{rec.get('phase','')}/{rec.get('case') or '-'}  {rec.get('because','')[:60]}")
    pairs = pair_records(records)
    open_intents = [str(n) for n, s in pairs.items() if s.get("intent") and not s.get("terminal")]
    if open_intents:
        print(f"- open intents (unrecovered): {', '.join(open_intents)}")
    lease = read_lease()
    if lease:
        alive = controller_alive(lease.get("controller_pid"))
        print(f"- lease: {lease.get('ref')} controller={lease.get('controller_pid')} {'live' if alive else 'dead'}")
    if partial is not None:
        print("- ignored partial record at ledger tail (1)")
    cp = last_checkpoint(records)
    current = paths["capsules"] / "current.md"
    if cp and (not current.is_file() or sha256_file(current) != cp.get("capsule_sha256")):
        print("- capsule mismatch: current.md does not match the last checkpoint")
    if paths["index"].is_file():
        try:
            stored = json.loads(paths["index"].read_text(encoding="utf-8"))
        except ValueError:
            stored = None
        if stored != derive_index(meta, records):
            print("- index mismatch: run.json disagrees with the ledger")
    else:
        print("- index missing: run.json absent")
    if paths["capsules"].is_dir():
        named = {r.get("capsule_path") for r in records if r.get("kind") == "checkpoint"}
        orphans = [p.name for p in paths["capsules"].glob("*.md") if p.name != "current.md" and p.name not in named]
        if orphans:
            print(f"- orphan snapshots: {', '.join(orphans)}")
    return 0


def cmd_checkpoint(args) -> int:
    phase = args.phase
    if phase not in PHASES:
        raise UsageError(f"phase must be one of {PHASES}")
    if phase == "final" and args.achieved not in ACHIEVED_VALUES:
        raise UsageError(f"checkpoint final requires --achieved one of {ACHIEVED_VALUES}")
    if phase != "final" and args.achieved:
        raise UsageError("--achieved is only valid for checkpoint final")
    run_id = _resolve_run(args)
    meta = load_meta(run_id)
    with store_lock():
        repair(run_id, "checkpoint")
        records, _ = load_records(run_id)
        index = rebuild_index(run_id, records)
        if index["state"] != "open":
            raise UsageError(f"run {run_id} is sealed")
        cur = current_state_triplet(meta)
        if cur["branch"] != meta["branch"]:
            raise UsageError(f"branch changed: run belongs to {meta['branch']!r}")
        if cur["plan_sha256"] != meta["plan_sha256"]:
            raise UsageError("plan changed since the run began; begin a new run")
        state = index["phase"]
        if not admitted_checkpoint(state, phase):
            raise UsageError(f"checkpoint {phase!r} is not admitted in state {state!r}")
        unclosed = unclosed_phases(records, phase)
        if unclosed:
            raise UsageError("phases with attempts newer than their checkpoint: " + ", ".join(unclosed))
        if phase == "final":
            ach = args.achieved
            need = {"red": "red", "green": "green", "refactored-green": "refactor"}.get(ach)
            if need and PHASE_RANK[state] < PHASE_RANK[need]:
                raise UsageError(f"--achieved {ach} requires state >= {need}, state is {state}")
        extras = {"next": args.next, "open": args.open, "blocked": args.blocked,
                  "not_applicable": args.not_applicable}
        text = build_capsule(records, meta, extras)
        n = next_n(records)
        paths = store_paths(run_id)
        paths["capsules"].mkdir(parents=True, exist_ok=True)
        snap_name = f"{n:04d}-{phase}.md"
        snap = paths["capsules"] / snap_name
        tmp = paths["capsules"] / (snap_name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, snap)
        head_n = n - 1
        rec = {
            "ref": f"{run_id}#{n}", "n": n, "run": run_id, "kind": "checkpoint", "at_utc": now_utc(),
            "phase": phase, "achieved": args.achieved if phase == "final" else None,
            "at": {**cur, "worktree_digest": worktree_digest(worktree_snapshot())},
            "ledger_head": head_n, "ledger_sha256": ledger_digest(records, head_n),
            "capsule_path": snap_name, "capsule_sha256": sha256_bytes(text.encode("utf-8")),
            "verified": [l[2:] for l in _section(text, "Verified")],
            "open": [l[2:] for l in _section(text, "Open")],
            "blocked": [l[2:] for l in _section(text, "Blocked")],
            "not_applicable": [l[2:] for l in _section(text, "Not applicable")],
            "next": (_section(text, "Next") or ["- "])[0][2:],
        }
        rec["receipt"] = receipt_of(rec)
        append_record(run_id, rec)
        records.append(rec)
        rebuild_index(run_id, records)
        _regenerate_current(run_id, records)
    print(f"checkpoint={phase} event={rec['ref']} receipt={rec['receipt']} capsule={snap_name}")
    return 0


def _section(text: str, title: str) -> list:
    out, active = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            active = line[3:].strip() == title
            continue
        if active and line.startswith("- "):
            out.append(line)
    return out


def cmd_export(args) -> int:
    run_id = _resolve_run(args)
    meta = load_meta(run_id)
    if args.out:
        out = contained(args.out, "--out")
    else:
        out = repo_root() / "thoughts" / "shared" / "tests" / "receipts" / f"{run_id}.json"
    with store_lock():
        repair(run_id, "export")
        records, _ = load_records(run_id)
        index = rebuild_index(run_id, records)
        cur = current_state_triplet(meta)
        if cur["branch"] != meta["branch"]:
            raise UsageError(f"branch changed: run belongs to {meta['branch']!r}")
        if cur["plan_sha256"] != meta["plan_sha256"]:
            raise UsageError("plan changed since the run began")
        paths = store_paths(run_id)
        capsules = []
        for rec in records:
            if rec.get("kind") == "checkpoint":
                snap = paths["capsules"] / rec["capsule_path"]
                text = snap.read_text(encoding="utf-8") if snap.is_file() else ""
                capsules.append({"phase": rec["phase"], "path": rec["capsule_path"],
                                 "text": text, "sha256": sha256_bytes(text.encode("utf-8"))})
        payload = {
            "schema": SCHEMA, "run": index, "exported_at": now_utc(),
            "records_through": next_n(records) - 1, "events": records, "capsules": capsules,
        }
        new_text = canonical_json(payload) + "\n"
        if out.exists():
            try:
                old = json.loads(out.read_text(encoding="utf-8"))
            except ValueError:
                raise UsageError(f"existing export is not valid JSON: {out}")
            old_events = old.get("events") or []
            old_caps = old.get("capsules") or []
            if old_events != records[:len(old_events)] or old_caps != capsules[:len(old_caps)]:
                raise UsageError(f"existing export is not a prefix of the current ledger: {out}")
            if len(old_events) == len(records) and len(old_caps) == len(capsules) \
                    and old.get("run") == index:
                print(f"export={rel_to_root(out)} unchanged")
                return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out, new_text)
    print(f"export={rel_to_root(out)} records={payload['records_through']} state={index['state']}")
    return 0


# --------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evidence.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("begin", help="start a new run or resume an open one")
    b.add_argument("--plan", help="test plan path (repo-relative)")
    b.add_argument("--resume", metavar="RUN_ID", help="resume an open run of the same plan and branch")
    b.set_defaults(func=cmd_begin)

    r = sub.add_parser("run", help="predict, execute, grade, persist")
    r.add_argument("--run", help="run id (default: current)")
    r.add_argument("--phase", required=True, choices=PHASES)
    r.add_argument("--case")
    r.add_argument("--workflow", default=WORKFLOW_DEFAULT)
    r.add_argument("--because", default="")
    r.add_argument("--risk", default="local_verify")
    r.add_argument("--expect", action="append", default=[])
    r.add_argument("--scope", action="append", default=[])
    r.add_argument("--requires")
    r.add_argument("--report")
    r.add_argument("--timeout", type=int)
    r.add_argument("--tail-bytes", type=int, dest="tail_bytes")
    r.add_argument("argv", nargs=argparse.REMAINDER)
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("status", help="print the recovery capsule (read-only)")
    s.add_argument("--run")
    s.add_argument("--last", type=int, default=8)
    s.set_defaults(func=cmd_status)

    c = sub.add_parser("checkpoint", help="record a phase boundary")
    c.add_argument("phase", choices=PHASES)
    c.add_argument("--run")
    c.add_argument("--achieved", choices=ACHIEVED_VALUES)
    c.add_argument("--next")
    c.add_argument("--open", action="append", default=[])
    c.add_argument("--blocked", action="append", default=[])
    c.add_argument("--not-applicable", action="append", default=[], dest="not_applicable")
    c.set_defaults(func=cmd_checkpoint)

    e = sub.add_parser("export", help="write the canonical receipt file")
    e.add_argument("--run")
    e.add_argument("--out")
    e.set_defaults(func=cmd_export)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as exc:
        _eprint(str(exc))
        return 2
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
