#!/usr/bin/env python3
"""Real filesystem sandbox for evaluated and judge sessions.

Confinement contract (pilot plan, candidate-freeze record): the wrapped
session runs in a chroot built from an ALLOWLIST — nothing of the host
is visible except what the session needs:

  read-write: the run's working directory and its clean profile
              (re-created at their real paths), a fresh private /tmp
              (tmpfs), a fresh private HOME (tmpfs)
  read-only:  the OS/toolchain surface (/usr /bin /sbin /lib* /etc
              /opt), the git common directory backing the working
              directory's worktree (derived from `workdir/.git`, needed
              for the metadata script's git calls), and, when present,
              HOME/.ccr (the environment's TLS proxy CA bundle)
  inherited:  /dev (device nodes), /proc (fresh mount when the kernel
              allows, host bind otherwise); network is untouched

Everything else — other checkouts, sealed packages, ground truth,
manifests, prior run outputs — is simply ABSENT from the mount tree,
not merely unwritable. Implemented with util-linux `unshare` (user +
mount namespaces) and a chroot assembled on a private tmpfs; no
dependencies beyond util-linux, so the registered wrapper runs on any
Linux with unprivileged user namespaces.

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
RO_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64",
            "/libx32", "/etc", "/opt")


def mount(*args):
    subprocess.run(["mount", *args], check=True)


def bind_ro(src, newroot):
    """Recursively read-only bind: --rbind carries every submount (e.g.
    the /etc/hosts and /etc/resolv.conf file mounts of container
    hosts), and a plain remount,ro covers only the top mount — each
    child mount must be remounted read-only itself, or the registered
    read-only surface silently carries writable holes."""
    dest = newroot + src
    os.makedirs(dest, exist_ok=True)
    mount("--rbind", src, dest)
    mount("--bind", "-o", "remount,ro", dest)
    for child in _mounts_under(dest):
        mount("-o", "remount,bind,ro", child)


def _mounts_under(dest):
    """Mount points strictly below `dest`, deepest first, from
    /proc/self/mountinfo (field 5; octal escapes decoded)."""
    prefix = dest.rstrip("/") + "/"
    points = []
    with open("/proc/self/mountinfo", encoding="utf-8") as fh:
        for line in fh:
            mp = line.split()[4]
            mp = mp.encode("ascii").decode("unicode_escape")
            if mp.startswith(prefix):
                points.append(mp)
    return sorted(points, key=len, reverse=True)


def git_common_dir(workdir):
    """The git directory backing a linked worktree: `workdir/.git` is a
    file `gitdir: <repo>/.git/worktrees/<name>`; the common directory
    two levels up carries the objects and refs the session's git calls
    read. A full clone (`.git` directory) needs nothing extra."""
    dotgit = os.path.join(workdir, ".git")
    if not os.path.isfile(dotgit):
        return None
    with open(dotgit, encoding="utf-8") as fh:
        line = fh.read().strip()
    if not line.startswith("gitdir:"):
        return None
    gitdir = os.path.realpath(line.split(":", 1)[1].strip())
    commondir_file = os.path.join(gitdir, "commondir")
    if os.path.isfile(commondir_file):
        with open(commondir_file, encoding="utf-8") as fh:
            rel = fh.read().strip()
        return os.path.realpath(os.path.join(gitdir, rel))
    return gitdir


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

    # Stage 2, inside the namespaces: assemble the allowlist chroot on
    # a private tmpfs — host paths outside the allowlist do not exist
    # in the session's mount tree at all.
    os.environ.pop(STAGE2_MARK, None)
    mount("--make-rprivate", "/")
    newroot = tempfile.mkdtemp(prefix="nsroot-", dir="/dev/shm")
    mount("-t", "tmpfs", "tmpfs", newroot)

    for ro_path in RO_PATHS:
        if os.path.isdir(ro_path) and not os.path.islink(ro_path):
            bind_ro(ro_path, newroot)
        elif os.path.islink(ro_path):
            os.symlink(os.readlink(ro_path), newroot + ro_path)

    os.makedirs(newroot + "/dev", exist_ok=True)
    mount("--rbind", "/dev", newroot + "/dev")
    # Host /dev/shm is a regular shared tmpfs, not device nodes: files
    # staged there by other processes must not be visible. A fresh
    # private tmpfs gives the session working POSIX shared memory while
    # hiding the host's (and this wrapper's own chroot scaffolding).
    shm = newroot + "/dev/shm"
    if os.path.isdir(shm):
        mount("-t", "tmpfs", "tmpfs", shm)
    os.makedirs(newroot + "/proc", exist_ok=True)
    fresh_proc = subprocess.run(
        ["mount", "-t", "proc", "proc", newroot + "/proc"],
        capture_output=True)
    if fresh_proc.returncode != 0:
        # Container kernels commonly refuse a fresh proc mount inside
        # an unprivileged userns (masked /proc paths); the host bind
        # carries the same view the session already had.
        mount("--rbind", "/proc", newroot + "/proc")

    os.makedirs(newroot + "/tmp", exist_ok=True)
    mount("-t", "tmpfs", "tmpfs", newroot + "/tmp")

    home = os.environ.get("HOME") or "/root"
    home = os.path.realpath(home)
    os.makedirs(newroot + home, exist_ok=True)
    mount("-t", "tmpfs", "tmpfs", newroot + home)
    ccr = os.path.join(home, ".ccr")
    if os.path.isdir(ccr):
        bind_ro(ccr, newroot)

    # The backend CLI's own credential directory (pointed to by
    # CLAUDE_SESSION_INGRESS_TOKEN_FILE in managed environments) is part
    # of the minimal runtime surface: the wrapped process cannot
    # authenticate without it. Hosts that authenticate via environment
    # variables alone have nothing to bind here.
    ingress = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if ingress and os.path.isfile(ingress):
        bind_ro(os.path.dirname(os.path.realpath(ingress)), newroot)

    common = git_common_dir(workdir)
    if common and os.path.isdir(common):
        bind_ro(common, newroot)

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
