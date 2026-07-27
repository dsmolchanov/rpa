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


# Mounted INSIDE the worktree: the backend CLI restricts file access to
# the session's allowed working directories, so a git directory outside
# them (e.g. /sealed-git) gets its git calls blocked by the permission
# layer. The mountpoint directory is created through the worktree bind
# (worktrees are disposable; the empty dir vanishes with the worktree).
PINNED_GIT_NAME = ".pinned-git"


def build_pinned_gitdir(workdir, common):
    """A PRIVATE git directory restricted to the pinned commit's
    closure. Binding the operator clone's common directory would expose
    every ref, reflog, and object in it (`git log --all`,
    `git cat-file --batch-all-objects`) — including history newer or
    more private than the sealed target-sha. Instead: fetch exactly the
    worktree's HEAD commit from the clone into a fresh bare repository
    (objects = the pinned closure, no refs beyond the fetched one,
    empty reflogs), detach its HEAD at the pin, and mark it non-bare so
    a `gitdir:` file in the worktree turns it into that worktree's
    repository."""
    head = subprocess.run(
        ["git", "-C", workdir, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    private = tempfile.mkdtemp(prefix="pinned-git-", dir="/dev/shm")
    run_quiet = dict(check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", "--quiet", private],
                   **run_quiet)
    subprocess.run(["git", "-C", private,
                    "-c", "uploadpack.allowAnySHA1InWant=true",
                    "fetch", "--quiet", "--no-tags", common, head],
                   **run_quiet)
    for ref in ("FETCH_HEAD", "ORIG_HEAD"):
        path = os.path.join(private, ref)
        if os.path.exists(path):
            os.unlink(path)
    with open(os.path.join(private, "HEAD"), "w",
              encoding="utf-8") as fh:
        fh.write(head + "\n")
    subprocess.run(["git", "-C", private, "config", "core.bare",
                    "false"], **run_quiet)
    # Populate the index from the pinned tree so `git status` inside the
    # session reads clean instead of showing every checked-out file as a
    # pending change against an empty index; exclude the in-worktree
    # mountpoint of this directory from status output.
    subprocess.run(["git", "-C", private, "read-tree", head],
                   **run_quiet)
    info_dir = os.path.join(private, "info")
    os.makedirs(info_dir, exist_ok=True)
    with open(os.path.join(info_dir, "exclude"), "a",
              encoding="utf-8") as fh:
        fh.write("/" + PINNED_GIT_NAME + "/\n")
    return private, head


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
        # -p/-f: a private PID namespace (with the fork PID 1 requires),
        # so the session's /proc cannot enumerate host processes — a
        # sibling orchestrator's cmdline carries private eval paths.
        # --kill-child ties the inner tree to the wrapper's lifetime for
        # the runner's timeout process-tree kill.
        os.execvpe("unshare",
                   ["unshare", "-rmpf", "--kill-child", "--",
                    sys.executable, os.path.abspath(__file__),
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
        # FAIL CLOSED: a bind of the outer /proc would re-expose the
        # host PID namespace this wrapper just left — sibling process
        # cmdlines can carry private eval paths.
        sys.exit("ns_sandbox: cannot mount a private /proc for the new "
                 "PID namespace: "
                 + fresh_proc.stderr.decode(errors="replace").strip())

    os.makedirs(newroot + "/tmp", exist_ok=True)
    mount("-t", "tmpfs", "tmpfs", newroot + "/tmp")

    home = os.environ.get("HOME") or "/root"
    home = os.path.realpath(home)
    os.makedirs(newroot + home, exist_ok=True)
    mount("-t", "tmpfs", "tmpfs", newroot + home)
    ccr = os.path.join(home, ".ccr")
    if os.path.isdir(ccr):
        bind_ro(ccr, newroot)

    # The backend CLI's credential files (the token file named by
    # CLAUDE_SESSION_INGRESS_TOKEN_FILE plus its .oauth_token sibling)
    # are part of the minimal runtime surface: the wrapped process
    # cannot authenticate without them. They are bound FILE by FILE —
    # a directory bind would re-expose arbitrary siblings (and could
    # even shadow the private /tmp when the token lives there). Hosts
    # that authenticate via environment variables alone have nothing to
    # bind here.
    ingress = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if ingress and os.path.isfile(ingress):
        ingress = os.path.realpath(ingress)
        cred_files = [ingress,
                      os.path.join(os.path.dirname(ingress),
                                   ".oauth_token")]
        for cred in cred_files:
            if not os.path.isfile(cred):
                continue
            dest = newroot + cred
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "w").close()
            mount("--bind", cred, dest)
            mount("--bind", "-o", "remount,ro", dest)

    common = git_common_dir(workdir)
    pinned_git = None
    if common and os.path.isdir(common):
        pinned_git, _ = build_pinned_gitdir(workdir, common)

    for rw_path in (workdir, profile):
        dest = newroot + rw_path
        os.makedirs(dest, exist_ok=True)
        mount("--rbind", rw_path, dest)

    if pinned_git is not None:
        # Mount the pinned-closure git directory read-only INSIDE the
        # worktree and rewire the worktree's `.git` file to it — a FILE
        # bind inside this mount namespace only, so the operator's
        # worktree wiring outside the sandbox is untouched.
        pinned_mount = workdir + "/" + PINNED_GIT_NAME
        bind_ro_dest = newroot + pinned_mount
        os.makedirs(bind_ro_dest, exist_ok=True)
        mount("--rbind", pinned_git, bind_ro_dest)
        mount("--bind", "-o", "remount,ro", bind_ro_dest)
        gitfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".gitfile", delete=False,
            dir="/dev/shm", encoding="utf-8")
        gitfile.write(f"gitdir: {pinned_mount}\n")
        gitfile.close()
        mount("--bind", gitfile.name, newroot + workdir + "/.git")

    cwd = os.getcwd()
    os.chroot(newroot)
    os.chdir(cwd if os.path.isdir(cwd) else "/")
    exe = shutil.which(cmd[0]) or cmd[0]
    os.execv(exe, cmd)


if __name__ == "__main__":
    main()
