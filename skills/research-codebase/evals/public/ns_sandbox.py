#!/usr/bin/env python3
"""Real filesystem sandbox for evaluated and judge sessions.

Confinement contract (pilot plan, candidate-freeze record): the wrapped
session sees the host filesystem READ-ONLY except (1) the run's working
directory, (2) its clean profile, and (3) a fresh private /tmp (tmpfs)
that hides the host's /tmp — the two writable surfaces are re-mounted
read-write at their real paths. /proc, /sys and /dev are inherited from
the host. Network is untouched (only user + mount namespaces are
unshared).

Implemented with plain util-linux `unshare` plus a chroot into a
read-only rbind of `/` — no dependencies beyond util-linux, so the same
registered wrapper runs on any Linux with unprivileged user namespaces
(validated once at the formal real-backend preflight, then verified
implicitly by every sandboxed run).

Usage (the shape registered as `sandbox_cmd`; the runner appends the
backend command after `--`):

  ns_sandbox.py --confine-to {workdir} --profile {profile} -- CMD [ARG...]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

STAGE2_MARK = "NS_SANDBOX_STAGE2"


def mount(*args):
    subprocess.run(["mount", *args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confine-to", required=True, dest="workdir")
    parser.add_argument("--profile", required=True)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        sys.exit("ns_sandbox: no command to run")
    workdir = os.path.realpath(args.workdir)
    profile = os.path.realpath(args.profile)
    for path in (workdir, profile):
        if not os.path.isdir(path):
            sys.exit(f"ns_sandbox: not a directory: {path}")

    if os.environ.get(STAGE2_MARK) != "1":
        # Stage 1: enter user + mount namespaces (uid 0 mapped inside),
        # then re-run this script for the mount work.
        env = dict(os.environ)
        env[STAGE2_MARK] = "1"
        os.execvpe("unshare",
                   ["unshare", "-rm", "--", sys.executable,
                    os.path.abspath(__file__),
                    "--confine-to", workdir, "--profile", profile,
                    "--"] + cmd,
                   env)

    # Stage 2, inside the namespaces.
    os.environ.pop(STAGE2_MARK, None)
    mount("--make-rprivate", "/")
    newroot = tempfile.mkdtemp(prefix="nsroot-", dir="/dev/shm")
    mount("--rbind", "/", newroot)
    # Top-level read-only remount: the container root is a single
    # filesystem, so this covers every regular path; kernel-owned
    # pseudo-filesystems (/proc, /sys, /dev) keep their own semantics.
    mount("--bind", "-o", "remount,ro", newroot)
    # Fresh private /tmp: hides the host's; the writable surfaces are
    # re-created inside it when they live under /tmp, or bound over
    # their (read-only) mirror otherwise.
    mount("-t", "tmpfs", "tmpfs", newroot + "/tmp")
    for rw_path in (workdir, profile):
        dest = newroot + rw_path
        os.makedirs(dest, exist_ok=True)
        mount("--rbind", rw_path, dest)

    cwd = os.getcwd()
    os.chroot(newroot)
    os.chdir(cwd if os.path.isdir(cwd) else "/")
    exe = shutil.which(cmd[0]) or cmd[0]
    os.execv(exe, cmd)


if __name__ == "__main__":
    main()
