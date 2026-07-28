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
builder in `ns_sandbox.py`). macOS has no mount namespaces, so instead
of rewiring the worktree's `.git` file (a real edit could not be
restored if the runner's timeout SIGKILLs the wrapper's process
group), the session is pointed at the store through GIT_DIR and
GIT_WORK_TREE in its environment — nothing on disk changes, so there
is nothing to restore and the operator clone's worktree bookkeeping
stays intact on every exit path. The clone itself is DENIED by the
profile, so even a session that clears those variables cannot reach
unpinned history through the untouched `.git` file; the store is
write-DENIED by an explicit rule, matching the Linux wrapper's
read-only bind.

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

# The pilot's registered backend CLI: MACOS_SANDBOX_CLI_ROOT must
# provably be its install subtree (or the wrapped command's).
BACKEND_CLI = "claude"

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
(deny file-write*
{deny_writes})
"""


def sbpl_subpath(path):
    return f'  (subpath "{os.path.realpath(path)}")'


def sbpl_literal(path):
    return f'  (literal "{os.path.realpath(path)}")'


def build_profile(workdir, profile, extra_ro, rw_paths, deny_writes):
    ro = [sbpl_subpath(p) for p in RO_SUBPATHS if os.path.exists(p)]
    ro += extra_ro
    rw = [sbpl_subpath(p) for p in rw_paths]
    # SBPL: the last matching rule wins, so the write-deny block after
    # the rw allowances carves the pinned store (and the worktree's
    # `.git` file) OUT of the writable worktree.
    deny = deny_writes or ['  (literal "/nonexistent-deny-anchor")']
    return SBPL_TEMPLATE.format(ro_paths="\n".join(ro),
                                rw_paths="\n".join(rw),
                                deny_writes="\n".join(deny))


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

    # Toolchain: the backend binary's install location must be readable
    # when it is not already covered by the system allowlist (e.g. a
    # Homebrew or nvm tree). The surface is the NARROWEST useful one —
    # the binary's own directory subtree — and never a directory that
    # would expose operator identity wholesale: if the CLI resolves
    # directly inside HOME or ~/.claude (real settings, transcripts,
    # auth material live there), the operator must point
    # MACOS_SANDBOX_CLI_ROOT at a dedicated install subtree instead of
    # the wrapper guessing wider. The mandatory operator check's
    # CLI-start probe verifies whichever surface results.
    exe = shutil.which(cmd[0]) or cmd[0]
    exe_real = os.path.realpath(exe)
    exe_dir = os.path.dirname(exe_real)
    covered = any(
        exe_real.startswith(os.path.realpath(p) + "/")
        for p in RO_SUBPATHS if os.path.exists(p))
    extra_ro = []
    if not covered:
        home_real = os.path.realpath(os.path.expanduser("~"))
        claude_real = os.path.realpath(
            os.path.join(home_real, ".claude"))

        def contains(root, path):
            root = root.rstrip("/") or "/"
            return path == root or path.startswith(root + "/")

        def unsafe_root(root):
            # Unsafe is STRUCTURAL, not an exact-path blacklist: any
            # root that contains the operator's HOME (so /, /Users,
            # /System/Volumes/Data, HOME itself) or the real ~/.claude
            # would make identity material readable. A subtree INSIDE
            # them (e.g. ~/.claude/local) is fine — it does not
            # contain them.
            return (root == "/" or contains(root, home_real)
                    or contains(root, claude_real))

        if not unsafe_root(exe_dir):
            extra_ro.append(sbpl_subpath(exe_dir))
        elif not os.environ.get("MACOS_SANDBOX_CLI_ROOT"):
            sys.exit(f"macos_sandbox: the command resolves inside "
                     f"{exe_dir}, which would expose the operator's "
                     f"config tree — set MACOS_SANDBOX_CLI_ROOT to a "
                     f"dedicated install subtree")

    # The explicit CLI root applies WHENEVER it is set, independent of
    # what cmd[0] happens to be: probes and sessions that reach the
    # backend CLI through a shell (`sh -c "... claude ..."`) must get
    # the same install subtree the direct invocation would.
    override = os.environ.get("MACOS_SANDBOX_CLI_ROOT")
    if override:
        home_real = os.path.realpath(os.path.expanduser("~"))
        claude_real = os.path.realpath(
            os.path.join(home_real, ".claude"))
        root = os.path.realpath(override)
        root_clean = root.rstrip("/") or "/"
        if (root == "/"
                or home_real == root_clean
                or home_real.startswith(root_clean + "/")
                or claude_real == root_clean
                or claude_real.startswith(root_clean + "/")):
            sys.exit("macos_sandbox: MACOS_SANDBOX_CLI_ROOT may not "
                     "be / or any tree containing HOME or ~/.claude — "
                     "use a dedicated install subtree")
        if not os.path.isdir(root):
            sys.exit(f"macos_sandbox: MACOS_SANDBOX_CLI_ROOT is not a "
                     f"directory: {root}")
        # The root must PROVABLY be a CLI install subtree — it has to
        # contain the wrapped command's executable or the resolved
        # backend CLI (registered backend: `claude`). Without this, a
        # mis-set value (another eval volume, a data directory) would
        # become readable to every evaluated and judge session.
        def in_root(path):
            return (path == root_clean
                    or path.startswith(root_clean + "/"))

        backend = shutil.which(BACKEND_CLI)
        backend_real = os.path.realpath(backend) if backend else None
        if not (in_root(exe_real)
                or (backend_real is not None
                    and in_root(backend_real))):
            sys.exit("macos_sandbox: MACOS_SANDBOX_CLI_ROOT must be a "
                     "subtree containing the wrapped command's "
                     f"executable ({exe_real}) or the resolved "
                     f"backend CLI (`{BACKEND_CLI}`)")
        extra_ro.append(sbpl_subpath(root))

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
    # The worktree's `.git` file is left UNTOUCHED (a real rewrite
    # could not be restored if the runner's timeout SIGKILLs the
    # process group): the session reaches the store through
    # GIT_DIR/GIT_WORK_TREE instead, and the clone the `.git` file
    # points at is denied by the profile anyway.
    pinned = None
    common = ns_sandbox.git_common_dir(workdir)
    if common and os.path.isdir(common):
        pinned, _ = ns_sandbox.build_pinned_gitdir(workdir, common)

    deny_writes = []
    if pinned is not None:
        deny_writes.append(sbpl_subpath(pinned))
        deny_writes.append(sbpl_literal(os.path.join(workdir, ".git")))

    profile_text = build_profile(
        workdir, profile, extra_ro,
        rw_paths=[workdir, profile, fake_tmp, fake_home],
        deny_writes=deny_writes)
    sbpl_path = os.path.join(scratch, "session.sb")
    with open(sbpl_path, "w", encoding="utf-8") as fh:
        fh.write(profile_text)

    env = dict(os.environ)
    env["TMPDIR"] = fake_tmp
    env["HOME"] = fake_home
    if pinned is not None:
        env["GIT_DIR"] = pinned
        env["GIT_WORK_TREE"] = workdir
    try:
        result = subprocess.run(
            ["sandbox-exec", "-f", sbpl_path, exe] + cmd[1:], env=env)
        code = result.returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
