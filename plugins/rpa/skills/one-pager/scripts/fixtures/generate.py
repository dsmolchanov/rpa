#!/usr/bin/env python3
"""Regenerate the one-pager validator fixtures.

Every `valid*` fixture is produced by onepager.py itself in a throwaway git
repository (never hand-edited); every invalid case is derived from a valid one
by exactly one mutation, listed in MUTATIONS below. `generated_at` is pinned
after generation so regenerating the fixtures is a no-op.

Usage: generate.py [--out <dir>] [--docs-positive <root>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "onepager.py"
PINNED_AT = "2026-08-22T09:00:00Z"
NO_GH = "no-gh-on-path"


def run(cmd, cwd=None, env=None):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise SystemExit(f"{cmd} failed ({res.returncode}):\n{res.stdout}{res.stderr}")
    return res


def gitless_env(tmp):
    """PATH holding git but not gh, so the fixtures never depend on a login."""
    bindir = Path(tmp) / NO_GH
    bindir.mkdir(exist_ok=True)
    git = shutil.which("git")
    target = bindir / "git"
    if not target.exists():
        os.symlink(git, target)
    env = dict(os.environ, PATH=str(bindir), TZ="UTC")
    env.pop("RPA_HOME", None)
    return env


def seed_repo(root, name):
    root.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "-b", "master", str(root)])
    run(["git", "config", "user.email", "fixtures@example.invalid"], cwd=root)
    run(["git", "config", "user.name", "Fixtures"], cwd=root)
    plans = root / "thoughts" / "shared" / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-08-08-demo.md").write_text(
        "# Demo Plan\n\n"
        "## Phase 1\n\n"
        "### Success Criteria\n\n"
        "#### Automated Verification\n\n"
        "- [x] `demo test` exits 0.\n"
        "- [ ] `demo lint` exits 0.\n\n"
        "#### Manual Verification\n\n"
        "- [ ] Not applicable — every outcome is a command exit.\n\n"
        "## Enhancement History\n\n"
        "### 2026-08-10 Enhancement\n\nRecorded.\n",
        encoding="utf-8",
    )
    run(["git", "add", "-A"], cwd=root)
    env = dict(
        os.environ,
        GIT_AUTHOR_DATE="2026-08-08T00:00:00+00:00",
        GIT_COMMITTER_DATE="2026-08-08T00:00:00+00:00",
    )
    run(["git", "commit", "-q", "-m", f"seed {name}"], cwd=root, env=env)
    return root


def generate(repo, out_md, env, extra=()):
    """Generate inside the repository (containment forbids writing outside it),
    then copy the artifact into the fixture tree."""
    staged = repo / "thoughts" / "shared" / "one-pagers" / "one-pager.md"
    run(
        [sys.executable, str(SCRIPT), "generate", "--repo", str(repo), "--since",
         "2026-08-01", "--out", str(staged), *extra],
        env=env,
    )
    out_md.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(staged, out_md)
    if "--json" in extra:
        shutil.copy(staged.with_suffix(".json"), out_md.with_suffix(".json"))


def pin(path):
    text = path.read_text(encoding="utf-8")
    path.write_text(
        re.sub(r"(?m)^generated_at: .*$", f"generated_at: {PINNED_AT}", text, count=1),
        encoding="utf-8",
    )


def pin_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_at"] = PINNED_AT
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


NARRATIVE = (
    "\n## Narrative\n\n"
    "_Model-written summary of the facts above; not a source._\n\n"
    "One plan is in flight and nothing is waiting on review.\n"
)


def mutate_heading_order(text):
    return text.replace("## Landed", "\x00").replace("## Open", "## Landed").replace("\x00", "## Open")


def mutate_oversized(text):
    filler = "\n".join(f"- unattributed 000000{i:01d} filler subject (2026-08-08)" for i in range(70))
    return text.replace("## Landed\n\n", f"## Landed\n\n{filler}\n")


def mutate_narrative_unmarked(text):
    return text.rstrip("\n") + "\n\n## Narrative\n\nA summary without the marker.\n"


def mutate_narrative_invents(text):
    return text.rstrip("\n") + (
        "\n\n## Narrative\n\n"
        "_Model-written summary of the facts above; not a source._\n\n"
        "Shipped #4242 and closed 9 criteria this week.\n"
    )


def mutate_receipt_token(text):
    return text.replace("## Artifacts\n\n", "## Artifacts\n\n- see receipt a1b2c3d4e5f6 for proof\n")


def mutate_sources_bad_outcome(text):
    return text.replace("| git | passed |", "| git | green |", 1)


def mutate_missing_window(text):
    return re.sub(r"(?m)^window\.since: .*\n", "", text, count=1)


def mutate_next_bad_shape(text):
    return re.sub(r"(?m)^- \d+ open in \S+$", "- fix the flaky thing", text, count=1)


def mutate_absolute_path(text):
    return text.replace(
        "## Artifacts\n\n", "## Artifacts\n\n- plans /home/agent/thoughts/shared/plans/x.md — present\n"
    )


MUTATIONS = {
    "heading-order": mutate_heading_order,
    "oversized": mutate_oversized,
    "narrative-unmarked": mutate_narrative_unmarked,
    "narrative-invents-facts": mutate_narrative_invents,
    "receipt-token": mutate_receipt_token,
    "sources-bad-outcome": mutate_sources_bad_outcome,
    "missing-window": mutate_missing_window,
    "next-bad-shape": mutate_next_bad_shape,
    "absolute-path": mutate_absolute_path,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(HERE))
    parser.add_argument("--docs-positive")
    args = parser.parse_args()
    out = Path(args.out).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        env = gitless_env(tmp)
        repo = seed_repo(Path(tmp) / "demo", "demo")
        other = seed_repo(Path(tmp) / "other", "other")

        for case in ("valid", "valid-with-narrative", "valid-json", *MUTATIONS):
            (out / case).mkdir(parents=True, exist_ok=True)

        base = out / "valid" / "one-pager.md"
        generate(repo, base, env)
        pin(base)
        text = base.read_text(encoding="utf-8")

        narrated = out / "valid-with-narrative" / "one-pager.md"
        narrated.write_text(text.rstrip("\n") + "\n" + NARRATIVE, encoding="utf-8")

        pair = out / "valid-json" / "one-pager.md"
        generate(repo, pair, env, extra=["--json"])
        pin(pair)
        pin_json(pair.with_suffix(".json"))

        parity = out / "json-parity-mismatch"
        parity.mkdir(parents=True, exist_ok=True)
        shutil.copy(pair, parity / "one-pager.md")
        data = json.loads(pair.with_suffix(".json").read_text(encoding="utf-8"))
        data["repos"][0]["window"]["commits"] += 41
        (parity / "one-pager.json").write_text(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        cross = out / "valid-all" / "one-pager.md"
        cross.parent.mkdir(parents=True, exist_ok=True)
        run(
            [sys.executable, str(SCRIPT), "generate", "--repos", str(repo), str(other),
             "--since", "2026-08-01", "--out", str(cross)],
            env=env,
        )
        pin(cross)

        caps = out / "mode-caps"
        caps.mkdir(parents=True, exist_ok=True)
        cross_text = cross.read_text(encoding="utf-8")
        filler = "\n".join(f"- unattributed 000000{i:01d} filler subject (2026-08-08)" for i in range(160))
        (caps / "one-pager.md").write_text(
            cross_text.replace("### Landed\n\n", f"### Landed\n\n{filler}\n", 1), encoding="utf-8"
        )

        for case, mutate in MUTATIONS.items():
            (out / case / "one-pager.md").write_text(mutate(text), encoding="utf-8")

        if args.docs_positive:
            root = Path(args.docs_positive) / "thoughts" / "shared" / "one-pagers"
            root.mkdir(parents=True, exist_ok=True)
            (root / "2026-08-08-demo.md").write_text(text, encoding="utf-8")

    print(f"fixtures written under {out}")


if __name__ == "__main__":
    main()
