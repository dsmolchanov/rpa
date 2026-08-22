#!/usr/bin/env python3
"""Tests for onepager.py (OP-01…OP-17).

Every case builds throwaway git repositories in a temporary directory and
invokes the script as a subprocess. No network: `gh` is either absent from
PATH or the canned shim in fixtures/gh-shim/.

Usage: python3 test_onepager.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "onepager.py"
FIXTURES = HERE / "fixtures"
SHIM_DIR = FIXTURES / "gh-shim"
TDD_SESSION_FIXTURE = HERE.parent.parent / "tdd" / "scripts" / "fixtures" / "session-logs" / "valid"

PLAN = """# Demo Plan

## Phase 1

### Success Criteria

#### Automated Verification

- [x] `demo test` exits 0.
- [ ] `demo lint` exits 0.

#### Manual Verification

- [ ] Not applicable — every outcome is a command exit.
- [ ] N/A for this phase.

## Enhancement History

### 2026-08-10 Enhancement

Recorded.
"""

HANDOFF_BOLD = """# Handoff

**Artifacts**: one plan

**Action Items & Next Steps**:

- Wire the gate into CI
- Re-run the suite
- Ask for review
- A fourth item that must not appear

**Other Notes**: none
"""

HANDOFF_HEADING = """# Handoff

## Next Steps

- Only step here
"""

HANDOFF_NONE = """# Handoff

Some prose without a next-steps section.
"""

VALIDATION = """## Validation Report: Demo Plan

**Plan**: `thoughts/shared/plans/2026-08-08-demo.md`

### Status

Complete.
"""


def git(repo, *args, env=None):
    res = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env
    )
    if res.returncode != 0:
        raise AssertionError(f"git {args} failed: {res.stderr}")
    return res.stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="onepager-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bindir = self.tmp / "bin-no-gh"
        self.bindir.mkdir()
        for tool in ("git", "python3"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, self.bindir / tool)

    # -- helpers ---------------------------------------------------------
    def env(self, gh=None, sha=None, rpa_home=None):
        path = str(self.bindir)
        env = dict(os.environ, TZ="UTC")
        env.pop("RPA_HOME", None)
        if gh:
            path = f"{SHIM_DIR}:{path}"
            env["GH_SHIM_MODE"] = gh
            if sha:
                env["GH_SHIM_SHA"] = sha
        env["PATH"] = path
        if rpa_home:
            env["RPA_HOME"] = str(rpa_home)
        return env

    def repo(self, name="demo", remote=False):
        root = self.tmp / name
        root.mkdir(parents=True)
        git(root.parent, "init", "-q", "-b", "master", str(root))
        git(root, "config", "user.email", "t@example.invalid")
        git(root, "config", "user.name", "Tests")
        if remote:
            git(root, "remote", "add", "origin", "https://github.com/example/demo.git")
        self.write(root, "thoughts/shared/plans/2026-08-08-demo.md", PLAN)
        self.commit(root, "seed", date="2026-08-08T00:00:00+00:00")
        return root

    def write(self, root, rel, text):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, root, message, date="2026-08-20T00:00:00+00:00"):
        git(root, "add", "-A")
        env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        git(root, "commit", "-q", "-m", message, env=env)
        return git(root, "rev-parse", "HEAD")

    def invoke(self, *args, env=None, expect=0):
        res = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env or self.env(),
        )
        if expect is not None:
            self.assertEqual(
                res.returncode, expect, f"args={args}\nstdout={res.stdout}\nstderr={res.stderr}"
            )
        return res

    def generate(self, repo, *extra, env=None, expect=0):
        return self.invoke(
            "generate", "--repo", str(repo), "--since", "2026-08-01", *extra, env=env, expect=expect
        )

    def page(self, repo):
        folder = repo / "thoughts" / "shared" / "one-pagers"
        pages = sorted(folder.glob("*.md"))
        self.assertTrue(pages, "no digest written")
        return pages[-1]


class TestGenerate(Base):
    def test_op01_determinism_and_generated_at_preservation(self):
        repo = self.repo()
        self.generate(repo, "--write", "--json")
        page = self.page(repo)
        first = page.read_bytes()
        first_json = page.with_suffix(".json").read_bytes()
        self.generate(repo, "--write", "--json")
        self.assertEqual(first, page.read_bytes(), "consecutive runs must be byte-identical")
        self.assertEqual(first_json, page.with_suffix(".json").read_bytes())

    def test_op02_since_last_fixed_point(self):
        repo = self.repo()
        self.invoke("generate", "--repo", str(repo), "--since", "2026-08-01", "--write")
        page = self.page(repo)
        first_since = re.search(r"(?m)^window\.since: (.+)$", page.read_text()).group(1)
        head = git(repo, "rev-parse", "HEAD")

        # unchanged HEAD: `last` reuses the recorded window start, never H..H
        self.invoke("generate", "--repo", str(repo), "--since", "last", "--write")
        text = self.page(repo).read_text()
        self.assertEqual(re.search(r"(?m)^window\.since: (.+)$", text).group(1), first_since)
        self.assertIn("- commits: 1", text)

        # a new commit advances the window to the previous generated_from
        self.write(repo, "thoughts/shared/plans/2026-08-21-next.md", PLAN)
        self.commit(repo, "add a plan")
        self.invoke("generate", "--repo", str(repo), "--since", "last", "--write")
        text = self.page(repo).read_text()
        self.assertEqual(re.search(r"(?m)^window\.since: (.+)$", text).group(1), head)

    def test_op03_window_by_date_and_by_ref(self):
        repo = self.repo()
        base = git(repo, "rev-parse", "HEAD")
        self.write(repo, "thoughts/shared/plans/2026-08-21-next.md", PLAN)
        self.commit(repo, "second")
        by_ref = self.invoke("generate", "--repo", str(repo), "--since", base).stdout
        self.assertIn("- commits: 1", by_ref)
        by_date = self.invoke("generate", "--repo", str(repo), "--since", "2026-08-01").stdout
        self.assertIn("- commits: 2", by_date)
        self.invoke("generate", "--repo", str(repo), "--since", "not-a-ref", expect=2)

    def test_op04_gh_absent_is_not_applicable(self):
        repo = self.repo()
        out = self.generate(repo).stdout
        self.assertIn("| gh-prs | not_applicable | gh not found |", out)
        self.assertIn("| gh-checks | not_applicable | gh not found |", out)

    def test_op05_gh_success(self):
        repo = self.repo(remote=True)
        head = git(repo, "rev-parse", "HEAD")
        out = self.generate(repo, env=self.env(gh="ok", sha=head)).stdout
        self.assertIn("- #7 canned merged pull request — merged 2026-08-21 by octocat (2 files)", out)
        self.assertNotIn("unattributed", out, "a commit owned by a PR is not unattributed")
        self.assertIn("- #9 canned open pull request — open, checks fail, review REVIEW_REQUIRED", out)
        self.assertIn("- ci on master: success", out)
        self.assertIn("- #9 checks fail", out)
        self.assertIn("| gh-prs | passed |", out)

    def test_op05_unattributed_when_pr_does_not_own_the_commit(self):
        repo = self.repo(remote=True)
        out = self.generate(repo, env=self.env(gh="ok", sha="f" * 40)).stdout
        self.assertIn("- unattributed ", out)
        self.assertNotIn("- #7 ", out, "a PR outside the window is not listed as landed")

    def test_op06_gh_malformed_and_failing(self):
        repo = self.repo(remote=True)
        out = self.generate(repo, env=self.env(gh="malformed")).stdout
        self.assertIn("| gh-prs | failed | malformed json |", out)
        self.assertIn("# One-pager: demo", out, "the digest still renders")

        res = self.generate(repo, env=self.env(gh="fail"))
        self.assertIn("| gh-prs | failed |", res.stdout)
        self.assertEqual(res.returncode, 0, "a failed gh source does not fail the run")

        out = self.generate(repo, env=self.env(gh="auth")).stdout
        self.assertIn("| gh-prs | not_applicable | gh not authenticated |", out)

    def test_op07_plan_criterion_states(self):
        repo = self.repo()
        out = self.generate(repo).stdout
        self.assertIn("satisfied 1 / open 1 / not-applicable 2; enhanced 2026-08-10", out)
        self.assertIn("- 1 open in thoughts/shared/plans/2026-08-08-demo.md", out)
        self.assertNotIn("- 3 open in", out, "`Not applicable` boxes are not work")

    def test_op08_artifact_parsers(self):
        repo = self.repo()
        src = TDD_SESSION_FIXTURE / "thoughts" / "shared" / "tests"
        self.assertTrue(src.is_dir(), f"missing TDD fixture: {src}")
        shutil.copytree(src, repo / "thoughts" / "shared" / "tests")
        self.write(repo, "thoughts/shared/implementations/2026-08-08-demo-validation.md", VALIDATION)
        self.write(repo, "thoughts/shared/handoffs/ENG-1/2026-08-08_a.md", HANDOFF_BOLD)
        self.write(repo, "thoughts/shared/handoffs/ENG-2/2026-08-08_b.md", HANDOFF_HEADING)
        self.write(repo, "thoughts/shared/handoffs/ENG-3/2026-08-08_c.md", HANDOFF_NONE)
        self.commit(repo, "artifacts")
        out = self.generate(repo).stdout

        self.assertRegex(out, r"tests thoughts/shared/tests/\S+TDD-SESSION\S+ — Green; cycle complete; receipts \d+")
        self.assertRegex(out, r"tests thoughts/shared/tests/\S+TEST\S+ — \d+ cases")
        self.assertIn("implementations thoughts/shared/implementations/2026-08-08-demo-validation.md — present; plan thoughts/shared/plans/2026-08-08-demo.md", out)
        self.assertIn("Wire the gate into CI; Re-run the suite; Ask for review", out)
        self.assertNotIn("A fourth item", out, "only the first three next steps are shown")
        self.assertIn("handoffs thoughts/shared/handoffs/ENG-2/2026-08-08_b.md — Only step here", out)
        self.assertIn("no next-steps section", out)
        self.assertIn("- next: Wire the gate into CI (thoughts/shared/handoffs/ENG-1/2026-08-08_a.md)", out)

    def test_op09_unchanged_head_session_sees_uncommitted_artifacts(self):
        """The refresh at the end of a TDD session must list the log it just
        wrote, which is uncommitted (the TDD skill withholds commit authority)."""
        repo = self.repo()
        head_before = git(repo, "rev-parse", "HEAD")
        log = (
            "# TDD Session: demo\n\n"
            "**Achieved phase**: Red\n"
            "- **Cycle state**: `continuing`\n"
        )
        self.write(repo, "thoughts/shared/tests/2026-08-22-TDD-SESSION-demo.md", log)
        out = self.generate(repo).stdout
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head_before, "nothing was committed")
        self.assertIn("tests thoughts/shared/tests/2026-08-22-TDD-SESSION-demo.md — Red; cycle continuing", out)
        self.assertIn("- thoughts/shared/tests/2026-08-22-TDD-SESSION-demo.md — cycle continuing", out)

    def test_op10_next_scans_all_active_artifacts(self):
        repo = self.repo()
        # a plan far outside the window still contributes open criteria
        self.write(repo, "thoughts/shared/plans/2020-01-01-old.md", PLAN)
        self.commit(repo, "old plan", date="2020-01-01T00:00:00+00:00")
        out = self.invoke("generate", "--repo", str(repo), "--since", "2026-08-19").stdout
        self.assertNotIn("plans thoughts/shared/plans/2020-01-01-old.md —", out, "outside the window")
        self.assertIn("- 1 open in thoughts/shared/plans/2020-01-01-old.md", out, "still in Next")

    def test_op11_bounds_keep_newest_and_headings(self):
        repo = self.repo()
        for i in range(60):
            self.write(repo, f"thoughts/shared/plans/2026-08-2{i % 10}-p{i}.md", PLAN)
            self.commit(repo, f"commit number {i:02d} with a deliberately long subject line", date="2026-08-20T00:00:00+00:00")
        newest = git(repo, "rev-parse", "HEAD")[:7]
        out = self.generate(repo, "--write").stdout
        text = self.page(repo).read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 80)
        self.assertLessEqual(len(text.encode("utf-8")), 12 * 1024)
        for heading in ("## Window", "## Landed", "## Open", "## Artifacts", "## Health", "## Next", "## Sources"):
            self.assertIn(heading, text)
        self.assertIn(newest, text, "the newest item survives truncation")
        self.assertRegex(text, r"- \[\+\d+ more\]")
        for line in text.splitlines():
            if line.startswith("- "):
                self.assertLessEqual(len(line.encode("utf-8")), 200)

        narrative = (
            "\n## Narrative\n\n_Model-written summary of the facts above; not a source._\n\n"
            + "\n".join(f"Line {i} of prose about the work." for i in range(8))
            + "\n"
        )
        self.page(repo).write_text(text.rstrip("\n") + "\n" + narrative, encoding="utf-8")
        grown = self.page(repo).read_text(encoding="utf-8")
        self.assertLessEqual(len(grown.splitlines()), 80, "the reserve absorbs a full narrative")
        self.assertLessEqual(len(grown.encode("utf-8")), 12 * 1024)
        self.invoke("validate", str(self.page(repo)))

    def test_op12_atomic_write_symlink_refusal_and_overwrite(self):
        repo = self.repo()
        self.generate(repo, "--write")
        page = self.page(repo)
        self.assertFalse(list(page.parent.glob(".*tmp*")), "no temp files left behind")
        self.generate(repo, "--write")
        self.assertEqual(len(list(page.parent.glob("*.md"))), 1, "same day overwrites in place")

        target = repo / "thoughts" / "shared" / "one-pagers" / "linked.md"
        os.symlink(repo / "thoughts" / "shared" / "plans" / "2026-08-08-demo.md", target)
        res = self.generate(repo, "--out", str(target), expect=2)
        self.assertIn("refusing to replace a symlink", res.stderr)

    def test_op13_read_side_containment(self):
        repo = self.repo()
        tests = repo / "thoughts" / "shared" / "tests"
        tests.mkdir(parents=True)
        outside = self.tmp / "outside.md"
        outside.write_text("# TDD Session: outside\n", encoding="utf-8")
        os.symlink(outside, tests / "2026-08-22-TDD-SESSION-linked.md")
        typechange = tests / "2026-08-22-TEST-typechange.md"
        typechange.write_text("U-1 tracked case\n", encoding="utf-8")
        self.commit(repo, "track an artifact that later becomes a fifo")
        typechange.unlink()
        os.mkfifo(typechange)
        (tests / "2026-08-22-TEST-huge.md").write_text("U-1\n" + "x" * (1024 * 1024 + 10), encoding="utf-8")
        out = self.generate(repo).stdout
        self.assertNotIn("outside", out, "a symlinked artifact is never read")
        self.assertNotIn("TDD-SESSION-linked", out)
        self.assertNotIn("huge", out)
        self.assertNotIn("typechange", out, "a special file is never read")
        self.assertRegex(out, r"\| tests \| passed \| skipped: 3 [a-z/]+ \|")

    def test_op14_output_mode_matrix(self):
        repo = self.repo()
        markdown = self.invoke("generate", "--repo", str(repo), "--since", "2026-08-01").stdout
        self.assertTrue(markdown.startswith("# One-pager: demo"))
        as_json = self.invoke("generate", "--repo", str(repo), "--since", "2026-08-01", "--json").stdout
        facts = json.loads(as_json)
        self.assertEqual(facts["schema"], 1)
        self.assertEqual(facts["mode"], "repo")
        self.assertFalse(list((repo / "thoughts" / "shared").glob("one-pagers/*")), "stdout modes write nothing")

        self.generate(repo, "--write", "--json")
        page = self.page(repo)
        self.assertTrue(page.with_suffix(".json").is_file(), "--json --write writes the companion")

        out = repo / "thoughts" / "shared" / "one-pagers" / "custom.md"
        self.generate(repo, "--out", str(out))
        self.assertTrue(out.is_file())

        res = self.generate(repo, "--out", str(self.tmp / "escape.md"), expect=2)
        self.assertIn("must resolve inside the repository", res.stderr)

    def test_op15_cross_repo_mode(self):
        one, two = self.repo("demo"), self.repo("other")
        home = self.tmp / "rpa-home"
        res = self.invoke(
            "generate", "--repos", str(one), str(two), "--since", "2026-08-01", "--write",
            env=self.env(rpa_home=home),
        )
        page = Path(res.stdout.strip())
        self.assertTrue(str(page).startswith(str(home)), f"cross-repo page must live in RPA_HOME: {page}")
        text = page.read_text(encoding="utf-8")
        self.assertIn("# One-pager (all repos)", text)
        self.assertIn("mode: all", text)
        self.assertIn("## demo", text)
        self.assertIn("## other", text)
        self.assertIn("| demo: git | passed |", text)
        self.invoke("validate", str(page))

        res = self.invoke(
            "generate", "--repos", str(one), str(two), "--since", "2026-08-01",
            "--out", str(one / "thoughts" / "shared" / "one-pagers" / "no.md"),
            env=self.env(rpa_home=home), expect=2,
        )
        self.assertIn("outside every listed repository", res.stderr)

    def test_op16_fixtures_accept_and_reject(self):
        cases = sorted(p for p in FIXTURES.iterdir() if p.is_dir() and p.name != "gh-shim")
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            page = case / "one-pager.md"
            self.assertTrue(page.is_file(), f"fixture without a digest: {case.name}")
            res = self.invoke("validate", str(page), expect=None)
            if case.name.startswith("valid"):
                self.assertEqual(res.returncode, 0, f"{case.name} must validate:\n{res.stdout}")
            else:
                self.assertEqual(res.returncode, 1, f"{case.name} must be rejected")
                self.assertRegex(res.stdout, r"^one-pager: [a-j] — ", f"{case.name}: {res.stdout}")
        json_page = FIXTURES / "valid-json" / "one-pager.json"
        self.invoke("validate", str(json_page))

    def test_op16_json_schema_is_checked(self):
        broken = self.tmp / "broken.json"
        broken.write_text(json.dumps({"schema": 2, "mode": "repo", "repos": []}), encoding="utf-8")
        res = self.invoke("validate", str(broken), expect=1)
        self.assertIn("one-pager: i — schema must be 1", res.stdout)

    def test_op17_relocatable_package(self):
        elsewhere = self.tmp / "relocated"
        shutil.copytree(SCRIPT.parent, elsewhere)
        repo = self.repo()
        res = subprocess.run(
            [sys.executable, str(elsewhere / "onepager.py"), "generate", "--repo", str(repo),
             "--since", "2026-08-01"],
            capture_output=True, text=True, env=self.env(),
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("# One-pager: demo", res.stdout)

    def test_not_a_repository_fails(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        res = self.invoke("generate", "--repo", str(plain), expect=1)
        self.assertIn("not a git repository", res.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
