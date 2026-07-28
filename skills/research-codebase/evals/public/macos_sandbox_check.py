#!/usr/bin/env python3
"""Operator-host validation for the macOS sandbox wrapper.

The registered macOS amendment permits scored runs on a macOS host
ONLY after this check passes there — the Linux implementation context
cannot execute `sandbox-exec`, so the proof lives on the operator
machine. Run it from the eval checkout on the Mac that will execute
Sequence step 5; every probe must PASS, and the full output is
recorded with the results.

Probes (mirroring the Linux wrapper's validated properties):
  1. writes inside the worktree and profile succeed
  2. a write outside the two rw surfaces is denied
  3. a stand-in "sealed" file outside the allowlist is UNREADABLE
  4. the operator's HOME is not the session's HOME (fresh private HOME)
  5. git works in a pinned worktree: rev-parse == pin, clean status,
     and a commit newer than the pin resolves to `bad object`
  6. the backend CLI starts (`claude --version`) under the wrapper

Usage: macos_sandbox_check.py --repo /path/to/rpa-clone
       --newer <sha> [--pin <sha>]
`--pin` defaults to the frozen candidate SHA; `--newer` is REQUIRED —
a commit present in the clone but NOT an ancestor of the pin (e.g. a
later master commit). The registered protocol demands the
newer-commit confinement probe before any macOS scored run, so the
check cannot pass without it.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
WRAPPER = HERE / "macos_sandbox.py"
FROZEN_CANDIDATE = "b731f06cdff5f38c0fa4c5aa64f93277d69e741d"

RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append(passed)
    mark = "PASS" if passed else "FAIL"
    print(f"macos-sandbox-check: {name:56s} {mark}"
          + (f"  ({detail})" if detail else ""))
    return passed


def wrapped(workdir, profile, shell_cmd):
    return subprocess.run(
        [sys.executable, str(WRAPPER), "--confine-to", str(workdir),
         "--profile", str(profile), "--", "sh", "-c", shell_cmd],
        capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pin", default=FROZEN_CANDIDATE)
    parser.add_argument("--newer", required=True,
                        help="commit in the clone that is NOT an "
                             "ancestor of --pin; the newer-commit "
                             "confinement probe is mandatory")
    args = parser.parse_args()
    if sys.platform != "darwin":
        sys.exit("macos-sandbox-check must run on the macOS operator "
                 "host — this is not a Mac")

    # Validate --newer OUTSIDE the sandbox first: a mistyped SHA would
    # also print `bad object` inside and prove nothing. It must be a
    # real commit of the clone and must NOT be an ancestor of the pin
    # (an ancestor is part of the pinned closure and legitimately
    # readable).
    r = subprocess.run(["git", "-C", args.repo, "rev-parse",
                        "--verify", args.newer + "^{commit}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"--newer {args.newer!r} is not a commit in "
                 f"{args.repo} — the newer-commit probe needs a real "
                 f"post-pin commit")
    newer_sha = r.stdout.strip()
    anc = subprocess.run(["git", "-C", args.repo, "merge-base",
                          "--is-ancestor", newer_sha, args.pin],
                         capture_output=True)
    if anc.returncode == 0:
        sys.exit(f"--newer {args.newer} is an ancestor of the pin — "
                 f"it is part of the pinned closure and proves "
                 f"nothing; supply a post-pin commit")
    if anc.returncode != 1:
        sys.exit(f"cannot establish ancestry of --newer against the "
                 f"pin: {anc.stderr.decode(errors='replace').strip()}")
    args.newer = newer_sha

    ws = Path(tempfile.mkdtemp(prefix="macsbx-check-"))
    profile = ws / "prof"
    profile.mkdir()
    sealed = ws / "sealed-standin.txt"
    sealed.write_text("sealed\n", encoding="utf-8")

    wt = ws / "worktrees" / uuid.uuid4().hex[:12] / "repo"
    wt.parent.mkdir(parents=True)
    subprocess.run(["git", "-C", args.repo, "worktree", "add",
                    "--detach", str(wt), args.pin],
                   check=True, capture_output=True)
    try:
        r = wrapped(wt, profile,
                    f"echo x > {wt}/probe && echo x > {profile}/probe "
                    f"&& echo RW_OK")
        check("rw surfaces writable", "RW_OK" in r.stdout)
        r = wrapped(wt, profile, f"echo evil > {ws}/outside 2>&1 "
                                 f"|| echo DENIED")
        check("write outside denied",
              "DENIED" in r.stdout and not (ws / "outside").exists())
        r = wrapped(wt, profile, f"cat {sealed} 2>/dev/null "
                                 f"&& echo LEAK || echo UNREADABLE")
        check("sealed stand-in unreadable", "UNREADABLE" in r.stdout
              and "LEAK" not in r.stdout)
        real_home = os.path.expanduser("~")
        r = wrapped(wt, profile, "echo $HOME")
        check("fresh private HOME",
              r.stdout.strip() not in ("", real_home))
        r = wrapped(wt, profile,
                    f"cd {wt} && git rev-parse HEAD "
                    f"&& git status --short | wc -l")
        out_lines = r.stdout.split()
        git_ok = (r.returncode == 0 and len(out_lines) >= 2
                  and out_lines[0] == args.pin
                  and out_lines[-1] == "0")
        check("git pinned worktree works (clean status)", git_ok,
              detail=(r.stdout + r.stderr).strip()[:80])
        r = wrapped(wt, profile,
                    f"cd {wt} && git show {args.newer} --oneline "
                    f"2>&1 | head -1")
        check("newer-than-pin commit unreadable",
              "bad object" in r.stdout + r.stderr)
        r = wrapped(wt, profile, "claude --version")
        check("backend CLI starts under the wrapper",
              r.returncode == 0, detail=r.stdout.strip()[:40])
    finally:
        subprocess.run(["git", "-C", args.repo, "worktree", "remove",
                        "--force", str(wt)], capture_output=True)

    if all(RESULTS):
        print(f"macos-sandbox-check OK: {len(RESULTS)}/{len(RESULTS)} "
              f"probes")
        return 0
    print("macos-sandbox-check FAILED — scored runs on this host are "
          "not permitted until every probe passes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
