#!/usr/bin/env python3
"""Portable, fail-visible Claude Code hook gates for the RPA plugin."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


MAX_INPUT_BYTES = 1_048_576
PRETTIER_SUFFIXES = {
    ".css", ".graphql", ".html", ".js", ".json", ".jsx", ".md",
    ".mdx", ".mjs", ".scss", ".ts", ".tsx", ".vue", ".yaml", ".yml",
}


def report(gate: str, outcome: str, reason: str, *, blocking: bool = False) -> int:
    line = f"gate={gate} outcome={outcome} reason={reason}"
    print(line, file=sys.stderr if blocking else sys.stdout)
    return 2 if blocking else 0


def read_hook_input() -> dict:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("hook input exceeds 1 MiB")
    if not raw.strip():
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("hook input must be a JSON object")
    return value


def git_root() -> Path | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return Path(value).resolve() if value else None


def package_data(root: Path) -> dict | None:
    path = root / "package.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def local_prettier(root: Path) -> Path | None:
    name = "prettier.cmd" if sys.platform == "win32" else "prettier"
    candidate = root / "node_modules" / ".bin" / name
    return candidate if candidate.is_file() else None


def run_format(payload: dict) -> int:
    tool_input = payload.get("tool_input")
    raw_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(raw_path, str) or not raw_path.strip():
        return report("format", "not_applicable", "hook input has no file_path")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if path.suffix.lower() not in PRETTIER_SUFFIXES:
        return report("format", "not_applicable", "file type is not Prettier-managed")
    if not path.is_file():
        return report("format", "failed", "edited file does not exist", blocking=True)
    root = git_root() or Path.cwd().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return report("format", "not_applicable", "edited file is outside the checkout")
    prettier = local_prettier(root)
    if prettier is None:
        return report("format", "not_applicable", "local Prettier is not installed")
    completed = subprocess.run(
        [str(prettier), "--write", "--", str(path)], cwd=root, check=False
    )
    if completed.returncode != 0:
        return report(
            "format", "failed", f"Prettier exited {completed.returncode}", blocking=True
        )
    return report("format", "passed", path.name)


def run_lint() -> int:
    root = git_root()
    if root is None:
        return report("lint", "not_applicable", "working directory is not a git checkout")
    try:
        package = package_data(root)
    except ValueError as exc:
        return report("lint", "failed", str(exc), blocking=True)
    if package is None:
        return report("lint", "not_applicable", "package.json is absent")
    scripts = package.get("scripts")
    if not isinstance(scripts, dict) or not isinstance(scripts.get("lint"), str):
        return report("lint", "not_applicable", "package.json has no lint script")
    npm = shutil.which("npm")
    if npm is None:
        return report("lint", "failed", "npm is unavailable", blocking=True)
    completed = subprocess.run([npm, "run", "lint", "--silent"], cwd=root, check=False)
    if completed.returncode != 0:
        return report("lint", "failed", f"lint exited {completed.returncode}", blocking=True)
    return report("lint", "passed", "npm run lint")


def changed_files(root: Path) -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD", "--"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    names: set[str] = set()
    for command in commands:
        completed = subprocess.run(
            command, cwd=root, capture_output=True, text=True, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{' '.join(command[:2])} exited {completed.returncode}")
        names.update(line for line in completed.stdout.splitlines() if line)
    return sorted(name for name in names if (root / name).is_file())


def run_related_tests() -> int:
    root = git_root()
    if root is None:
        return report(
            "related-tests", "not_applicable", "working directory is not a git checkout"
        )
    try:
        package = package_data(root)
    except ValueError as exc:
        return report("related-tests", "failed", str(exc), blocking=True)
    if package is None:
        return report("related-tests", "not_applicable", "package.json is absent")
    scripts = package.get("scripts")
    test_script = scripts.get("test") if isinstance(scripts, dict) else None
    dependency_names = {
        key
        for field in ("dependencies", "devDependencies")
        for key in (
            package.get(field, {}).keys()
            if isinstance(package.get(field), dict)
            else ()
        )
    }
    if not isinstance(test_script, str) or (
        "jest" not in test_script.lower() and "jest" not in dependency_names
    ):
        return report(
            "related-tests", "not_applicable", "no Jest-backed test script is registered"
        )
    try:
        files = changed_files(root)
    except RuntimeError as exc:
        return report("related-tests", "failed", str(exc), blocking=True)
    if not files:
        return report("related-tests", "not_applicable", "no changed files")
    npm = shutil.which("npm")
    if npm is None:
        return report("related-tests", "failed", "npm is unavailable", blocking=True)
    completed = subprocess.run(
        [npm, "test", "--", "--bail", "--findRelatedTests", "--", *files],
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        return report(
            "related-tests",
            "failed",
            f"related tests exited {completed.returncode}",
            blocking=True,
        )
    return report("related-tests", "passed", f"{len(files)} changed file(s)")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"format", "lint", "related-tests"}:
        print("usage: run_gate.py {format|lint|related-tests}", file=sys.stderr)
        return 2
    gate = argv[1]
    try:
        payload = read_hook_input()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return report(gate, "failed", f"invalid hook input: {exc}", blocking=True)
    if gate == "format":
        return run_format(payload)
    if gate == "lint":
        return run_lint()
    return run_related_tests()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
