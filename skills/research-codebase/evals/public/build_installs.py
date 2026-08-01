#!/usr/bin/env python3
"""Deterministic builder for the pilot's three arm installation artifacts.

Candidate freeze record (pilot plan, Sequence step 4): the three
installations are derived ONLY from pinned git trees plus the two
recorded overlay steps, so rebuilding at any time reproduces the exact
registered tree hashes the eval-runner verifies before every run.

Arms:
  baseline   — frozen legacy tree at BASELINE_SHA, plus the common
               overlay (recorded in the plan): (1) the identical
               one-line `@AGENTS.md` import prepended to CLAUDE.md
               (the frozen tree predates the import; instruction
               LOADING must not be an arm difference), (2) the
               CANDIDATE_SHA `scripts/spec_metadata.sh` (shared
               metadata infrastructure the artifact gate depends on —
               detached-HEAD branch fallback, numeric %z offset).
               Everything else stays frozen, including AGENTS.md.
  candidate  — the frozen candidate tree at CANDIDATE_SHA, verbatim.
  ablation   — the candidate tree minus the fleet: all six
               `agents/research-v2-*.md` adapters and
               `skills/research-codebase/references/fleet-routing.md`
               removed; nothing else differs (pre-registered
               no-subagent policy is enforced by the runner via
               `forbid_subagents`).

Each installation carries the plugin content plus CLAUDE.md/AGENTS.md
(instruction surface): .claude-plugin, agents, commands, hooks,
scripts, and (where present) skills.

Usage: build_installs.py --repo /path/to/rpa-clone --out DIR
Prints the runner-verified hash_tree for every arm.
"""

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

import runner

BASELINE_SHA = "a7de5f6000225b57eeee1a5c6c0131fb02656d4d"
CANDIDATE_SHA = "b731f06cdff5f38c0fa4c5aa64f93277d69e741d"
INSTALL_PATHS = [".claude-plugin", "agents", "commands", "hooks",
                 "scripts", "skills", "CLAUDE.md", "AGENTS.md"]
IMPORT_LINE = "@AGENTS.md"


def safe_extract_git_archive(archive, dest):
    """Extract the trusted ``git archive`` without version-specific APIs.

    Python 3.12 added ``TarFile.extractall(filter="data")``, while the
    pinned operator image intentionally remains on Python 3.11.  Validate
    every member ourselves so compatibility does not reintroduce traversal,
    links, device nodes, or overwrite behavior.
    """
    directories = []
    for member in archive.getmembers():
        name = member.name.rstrip("/")
        relative = PurePosixPath(name)
        if (not name or "\\" in name or relative.is_absolute()
                or any(part in ("", ".", "..") for part in relative.parts)
                or relative.as_posix() != name):
            raise RuntimeError(f"unsafe git-archive member path: {member.name!r}")
        target = dest.joinpath(*relative.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            # `git archive` uses group-writable tar modes (0775/0664),
            # while TarFile extraction applies the process umask.  The
            # registered installation hashes were built under umask 022;
            # normalize explicitly so host/container umask cannot drift
            # the artifact.
            directories.append((target, 0o755))
            continue
        if not member.isfile():
            raise RuntimeError(
                f"unsupported git-archive member type: {member.name!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError(f"cannot read git-archive member: {member.name!r}")
        with source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
        target.chmod(0o755 if member.mode & 0o111 else 0o644)
    for directory, mode in reversed(directories):
        directory.chmod(mode)


def extract(repo, sha, dest):
    """git-archive the pinned INSTALL_PATHS of `sha` into `dest`."""
    present = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "--name-only", sha],
        capture_output=True, text=True, check=True).stdout.split()
    paths = [p for p in INSTALL_PATHS if p in present]
    tar_bytes = subprocess.run(
        ["git", "-C", str(repo), "archive", sha, "--"] + paths,
        capture_output=True, check=True).stdout
    dest.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        safe_extract_git_archive(tf, dest)


def build(repo, out):
    # `out` is recreated with rmtree: refuse any overlap with the source
    # clone — an --out equal to, containing, or inside --repo would
    # delete or pollute the clone (git objects included) before the
    # pinned trees are archived.
    repo_r = Path(repo).resolve()
    out_r = Path(out).resolve()
    if repo_r == out_r or repo_r in out_r.parents or out_r in repo_r.parents:
        raise SystemExit(
            f"refusing to build: --out {out_r} overlaps --repo {repo_r}")
    out = out_r
    if out.exists():
        shutil.rmtree(out)

    candidate = out / "candidate"
    extract(repo, CANDIDATE_SHA, candidate)

    baseline = out / "baseline"
    extract(repo, BASELINE_SHA, baseline)
    claude_md = baseline / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    if IMPORT_LINE not in text.splitlines():
        claude_md.write_text(IMPORT_LINE + "\n\n" + text, encoding="utf-8")
    shutil.copyfile(candidate / "scripts" / "spec_metadata.sh",
                    baseline / "scripts" / "spec_metadata.sh")

    ablation = out / "ablation"
    shutil.copytree(candidate, ablation)
    for adapter in sorted((ablation / "agents").glob("research-v2-*.md")):
        adapter.unlink()
    (ablation / "skills" / "research-codebase" / "references"
     / "fleet-routing.md").unlink()

    hashes = {}
    for arm in ("baseline", "candidate", "ablation"):
        hashes[arm] = runner.hash_tree(out / arm)
        print(f"{arm}: {hashes[arm]}")
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True,
                        help="path to an rpa clone containing both "
                             "pinned commits")
    parser.add_argument("--out", required=True,
                        help="output directory (recreated)")
    args = parser.parse_args()
    build(Path(args.repo), Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
