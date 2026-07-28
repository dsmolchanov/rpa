#!/usr/bin/env python3
"""macOS sandbox wrapper for evaluated and judge sessions.

Registered amendment (owner decision «поправка для мак», 2026-07-28,
recorded before unsealing): scored runs may execute on the operator's
macOS host through this wrapper. Same CLI contract and confinement
goals as the registered Linux wrapper (`ns_sandbox.py`):

  read-write: the run's working directory, its clean profile, a fresh
              private TMPDIR and HOME (created per session)
  read-only:  the OS/toolchain surface and the backend CLI's install
              location; the credential file named by
              CLAUDE_SESSION_INGRESS_TOKEN_FILE when the host
              authenticates by file (env-var auth needs nothing)
  denied:     everything else — `(deny default)` SBPL, so other
              checkouts, sealed packages, ground truth, and prior run
              outputs are unreadable, not merely unwritable

Git confinement matches the Linux wrapper: a PRIVATE pinned-closure
store is built inside the worktree (`.pinned-git`, via the shared
builder in `ns_sandbox.py`) and the worktree's `.git` file is pointed
at it for the session's duration. macOS has no mount namespaces, so
the rewiring is a real file edit restored after the session exits (the
wrapper waits on the child instead of exec-ing it); the operator clone
itself is DENIED by the profile, so `git log --all`-style access to
unpinned history is closed the same way.

VALIDATION BOUNDARY: the Linux implementation context cannot execute
`sandbox-exec`. Before any scored run, `macos_sandbox_check.py` MUST
pass on the operator host; its PASS output is recorded with the
results. This file carries the registered mechanism; the operator
check carries the proof.

Usage (the shape registered as `sandbox_cmd` on macOS hosts):

  macos_sandbox.py --confine-to {workdir} --profile {profile} -- CMD [ARG...]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import ns_sandbox

RO_SUBPATHS = ["/usr", "/bin", "/sbin", "/System", "/Library", "/opt",
               "/etc", "/private/etc", "/var/db/timezone",
               "/private/var/db/timezone", "/dev"]

SBPL_TEMPLATE = """(version 1)
(deny default)
(allow process-exec*)
(allow process-fork)
(allow process-info*)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup)
(allow mach-register)
(allow mach-priv-task-port)
(allow ipc-posix*)
(allow system-socket)
(allow network*)
(allow file-read-metadata)
(allow file-ioctl (subpath "/dev"))
(allow file-write-data (literal "/dev/null") (literal "/dev/dtracehelper"))
(allow file-read*
{ro_paths})
(allow file-read* file-write*
{rw_paths})
"""


def sbpl_subpath(path):
    return f'  (subpath "{os.path.realpath(path)}")'


def sbpl_literal(path):
    return f'  (literal "{os.path.realpath(path)}")'


def build_profile(workdir, profile, extra_ro, rw_paths):
    ro = [sbpl_subpath(p) for p in RO_SUBPATHS if os.path.exists(p)]
    ro += extra_ro
    rw = [sbpl_subpath(p) for p in rw_paths]
    return SBPL_TEMPLATE.format(ro_paths="\n".join(ro),
                                rw_paths="\n".join(rw))


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
        sys.exit("macos_sandbox: no command to run")
    workdir = os.path.realpath(args.workdir)
    profile = os.path.realpath(args.profile)
    for path in (workdir, profile):
        if not os.path.isdir(path):
            sys.exit(f"macos_sandbox: not a directory: {path}")

    # Toolchain: the backend binary's install prefix must be readable
    # (e.g. a Homebrew or nvm tree outside the system paths).
    exe = shutil.which(cmd[0]) or cmd[0]
    exe_prefix = os.path.dirname(os.path.dirname(os.path.realpath(exe)))
    extra_ro = [sbpl_subpath(exe_prefix)]

    # Credential file (file-authenticating hosts only): the named file
    # and its .oauth_token sibling, as literals — never the parent
    # directory. Env-var auth passes through the environment untouched.
    ingress = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if ingress and os.path.isfile(ingress):
        for base in (ingress, os.path.realpath(ingress)):
            extra_ro.append(sbpl_literal(base))
            sibling = os.path.join(os.path.dirname(base), ".oauth_token")
            if os.path.isfile(sibling):
                extra_ro.append(sbpl_literal(sibling))

    # Fresh private TMPDIR and HOME: the session must not read the
    # operator's real home (Keychain, dotfiles, other checkouts).
    scratch = tempfile.mkdtemp(prefix="macsbx-")
    fake_home = os.path.join(scratch, "home")
    fake_tmp = os.path.join(scratch, "tmp")
    os.makedirs(fake_home)
    os.makedirs(fake_tmp)

    # Pinned-closure git store, shared builder with the Linux wrapper.
    # No mount namespaces here: the worktree's `.git` file is really
    # rewritten and restored after the session exits.
    dotgit = os.path.join(workdir, ".git")
    original_gitfile = None
    common = ns_sandbox.git_common_dir(workdir)
    if common and os.path.isdir(common):
        pinned, _ = ns_sandbox.build_pinned_gitdir(workdir, common)
        with open(dotgit, encoding="utf-8") as fh:
            original_gitfile = fh.read()
        with open(dotgit, "w", encoding="utf-8") as fh:
            fh.write(f"gitdir: {pinned}\n")

    profile_text = build_profile(
        workdir, profile, extra_ro,
        rw_paths=[workdir, profile, fake_tmp, fake_home])
    sbpl_path = os.path.join(scratch, "session.sb")
    with open(sbpl_path, "w", encoding="utf-8") as fh:
        fh.write(profile_text)

    env = dict(os.environ)
    env["TMPDIR"] = fake_tmp
    env["HOME"] = fake_home
    try:
        result = subprocess.run(
            ["sandbox-exec", "-f", sbpl_path, exe] + cmd[1:], env=env)
        code = result.returncode
    finally:
        if original_gitfile is not None:
            with open(dotgit, "w", encoding="utf-8") as fh:
                fh.write(original_gitfile)
        shutil.rmtree(scratch, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
