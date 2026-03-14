#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap_aidlc_project.sh [--force-overlay] [--force-claude] <project-path>

Initializes a target repository for the RPA AI-DLC compatibility workflow.

What it does:
- creates the canonical aidlc-docs/ directory structure
- seeds starter files such as aidlc-state.md, audit.md, and execution-plan.md
- copies .aidlc-rule-details/ and optional helper READMEs on first run
- writes thoughts/shared/steering-rules/default.yaml with detected commands
- copies or appends the AI-DLC bootstrap to CLAUDE.md

Options:
- --force-overlay  Rewrite thoughts/shared/steering-rules/default.yaml
- --force-claude   Replace CLAUDE.md instead of appending/skipping
- -h, --help       Show this help text
EOF
}

log() {
  printf '[bootstrap-aidlc] %s\n' "$1"
}

copy_if_missing() {
  local src="$1"
  local dest="$2"
  if [ ! -e "$dest" ]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
  fi
}

copy_tree_if_missing() {
  local src="$1"
  local dest="$2"
  if [ ! -e "$dest" ]; then
    mkdir -p "$dest"
    cp -R "$src"/. "$dest"/
  fi
}

append_claude_bootstrap() {
  local src="$1"
  local dest="$2"

  if [ ! -e "$dest" ]; then
    cp "$src" "$dest"
    log "Created CLAUDE.md"
    return
  fi

  if grep -q "AI-DLC Compatibility Bootstrap" "$dest"; then
    log "CLAUDE.md already contains the AI-DLC bootstrap"
    return
  fi

  {
    printf '\n\n'
    cat "$src"
  } >>"$dest"
  log "Appended the AI-DLC bootstrap to existing CLAUDE.md"
}

FORCE_OVERLAY=0
FORCE_CLAUDE=0
TARGET_PATH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --force-overlay)
      FORCE_OVERLAY=1
      shift
      ;;
    --force-claude)
      FORCE_CLAUDE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [ -n "$TARGET_PATH" ]; then
        printf 'Only one project path may be provided.\n\n' >&2
        usage >&2
        exit 1
      fi
      TARGET_PATH="$1"
      shift
      ;;
  esac
done

if [ -z "$TARGET_PATH" ]; then
  usage >&2
  exit 1
fi

if [ ! -d "$TARGET_PATH" ]; then
  printf 'Project path does not exist: %s\n' "$TARGET_PATH" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

if git -C "$TARGET_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  PROJECT_ROOT=$(git -C "$TARGET_PATH" rev-parse --show-toplevel)
else
  PROJECT_ROOT=$(cd "$TARGET_PATH" && pwd)
fi

log "Bootstrapping $PROJECT_ROOT"

mkdir -p \
  "$PROJECT_ROOT/aidlc-docs/inception/plans" \
  "$PROJECT_ROOT/aidlc-docs/inception/questions" \
  "$PROJECT_ROOT/aidlc-docs/inception/requirements" \
  "$PROJECT_ROOT/aidlc-docs/inception/reverse-engineering" \
  "$PROJECT_ROOT/aidlc-docs/inception/user-stories" \
  "$PROJECT_ROOT/aidlc-docs/inception/application-design" \
  "$PROJECT_ROOT/aidlc-docs/inception/units" \
  "$PROJECT_ROOT/aidlc-docs/construction/units" \
  "$PROJECT_ROOT/aidlc-docs/construction/build-and-test" \
  "$PROJECT_ROOT/aidlc-docs/operations" \
  "$PROJECT_ROOT/thoughts/shared/steering-rules" \
  "$PROJECT_ROOT/thoughts/shared/aidlc" \
  "$PROJECT_ROOT/extensions"

touch \
  "$PROJECT_ROOT/aidlc-docs/inception/questions/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/inception/requirements/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/inception/reverse-engineering/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/inception/user-stories/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/inception/application-design/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/inception/units/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/construction/units/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/construction/build-and-test/.gitkeep" \
  "$PROJECT_ROOT/aidlc-docs/operations/.gitkeep"

copy_tree_if_missing "$SOURCE_ROOT/.aidlc-rule-details" "$PROJECT_ROOT/.aidlc-rule-details"
copy_if_missing "$SOURCE_ROOT/aidlc-docs/aidlc-state.md" "$PROJECT_ROOT/aidlc-docs/aidlc-state.md"
copy_if_missing "$SOURCE_ROOT/aidlc-docs/audit.md" "$PROJECT_ROOT/aidlc-docs/audit.md"
copy_if_missing "$SOURCE_ROOT/aidlc-docs/inception/plans/execution-plan.md" \
  "$PROJECT_ROOT/aidlc-docs/inception/plans/execution-plan.md"
copy_if_missing "$SOURCE_ROOT/extensions/README.md" "$PROJECT_ROOT/extensions/README.md"
copy_if_missing "$SOURCE_ROOT/thoughts/shared/aidlc/README.md" "$PROJECT_ROOT/thoughts/shared/aidlc/README.md"

OVERLAY_PATH="$PROJECT_ROOT/thoughts/shared/steering-rules/default.yaml"

if [ "$FORCE_OVERLAY" -eq 1 ] || [ ! -e "$OVERLAY_PATH" ]; then
  python3 - "$PROJECT_ROOT" "$OVERLAY_PATH" <<'PY'
import json
import sys
from pathlib import Path


def yaml_scalar(value):
    if value is None:
        return "null"
    return "'" + value.replace("'", "''") + "'"


def package_runner(pkg):
    manager = str(pkg.get("packageManager", "")).split("@", 1)[0]
    if manager in {"pnpm", "yarn", "bun"}:
        return manager
    return "npm"


def script_cmd(runner, script_name):
    if runner == "npm":
        if script_name == "test":
            return "npm test"
        return f"npm run {script_name}"
    if runner == "bun":
        return f"bun run {script_name}"
    return f"{runner} {script_name}"


def first_script(scripts, names, runner):
    for name in names:
        if name in scripts:
            return script_cmd(runner, name)
    return None


project_root = Path(sys.argv[1]).resolve()
overlay_path = Path(sys.argv[2]).resolve()

lint = None
typecheck = None
unit_tests = None
integration_tests = None
build = None
notes = []

package_json = project_root / "package.json"
if package_json.exists():
    pkg = json.loads(package_json.read_text())
    scripts = pkg.get("scripts", {})
    runner = package_runner(pkg)
    lint = first_script(scripts, ["lint"], runner)
    typecheck = first_script(scripts, ["typecheck", "type-check"], runner)
    unit_tests = first_script(scripts, ["test", "test:unit"], runner)
    integration_tests = first_script(
        scripts,
        ["test:all", "test:integration", "test:e2e", "test:db", "test:ux"],
        runner,
    )
    build = first_script(scripts, ["build"], runner)
    notes.append(f"Detected root package manager: {runner}")

backend_pyproject = project_root / "backend" / "pyproject.toml"
if backend_pyproject.exists():
    pyproject_text = backend_pyproject.read_text()

    if "ruff" in pyproject_text:
        backend_lint = "cd backend && python -m ruff check ."
        lint = f"{lint} && ({backend_lint})" if lint else backend_lint

    if "pytest" in pyproject_text:
        backend_tests = "cd backend && python -m pytest"
        unit_tests = f"{unit_tests} && ({backend_tests})" if unit_tests else backend_tests

    notes.append("Detected backend/pyproject.toml and merged backend lint/test defaults")

makefile = project_root / "Makefile"
if makefile.exists():
    contents = makefile.read_text()
    if lint is None and "\nlint:" in contents:
        lint = "make lint"
    if typecheck is None and "\ntypecheck:" in contents:
        typecheck = "make typecheck"
    if unit_tests is None and "\ntest:" in contents:
        unit_tests = "make test"
    if integration_tests is None and "\ntest-integration:" in contents:
        integration_tests = "make test-integration"
    if build is None and "\nbuild:" in contents:
        build = "make build"
    notes.append("Detected Makefile fallbacks for missing commands")

overlay = f"""# Generated by scripts/bootstrap_aidlc_project.sh
# Review the default_commands section before the first /aidlc_build_test run.
version: "1.0"
upstream_compatibility:
  pinned_release: "v0.1.6"
  canonical_artifact_root: "aidlc-docs"
  state_file: "aidlc-docs/aidlc-state.md"
  audit_file: "aidlc-docs/audit.md"

change_types:
  hotfix:
    indicators: ["bug fix", "hotfix", "critical", "production issue"]
    default_depth: minimal
  feature:
    indicators: ["feature", "enhancement", "new", "add"]
    default_depth: standard
  refactor:
    indicators: ["refactor", "cleanup", "restructure", "technical debt"]
    default_depth: standard
  migration:
    indicators: ["migration", "schema change", "data transform", "upgrade"]
    default_depth: comprehensive

plugin_conventions:
  commit_style: conventional
  branch_naming: "feature/{{ticket}}-{{description}}"
  test_naming: "{{module}}.test.{{ext}}"
  max_unit_size: "~200 lines changed"
  experimental_extensions:
    operations: true
    feedback: true

default_commands:
  lint: {yaml_scalar(lint)}
  typecheck: {yaml_scalar(typecheck)}
  unit_tests: {yaml_scalar(unit_tests)}
  integration_tests: {yaml_scalar(integration_tests)}
  build: {yaml_scalar(build)}
"""

overlay_path.write_text(overlay)

summary = [
    f"overlay={overlay_path}",
    f"lint={lint or 'null'}",
    f"typecheck={typecheck or 'null'}",
    f"unit_tests={unit_tests or 'null'}",
    f"integration_tests={integration_tests or 'null'}",
    f"build={build or 'null'}",
]
if notes:
    summary.append("notes=" + " | ".join(notes))

print("\n".join(summary))
PY
else
  log "Preserved existing overlay at thoughts/shared/steering-rules/default.yaml"
fi

if [ "$FORCE_CLAUDE" -eq 1 ]; then
  cp "$SOURCE_ROOT/CLAUDE.md" "$PROJECT_ROOT/CLAUDE.md"
  log "Replaced CLAUDE.md"
else
  append_claude_bootstrap "$SOURCE_ROOT/CLAUDE.md" "$PROJECT_ROOT/CLAUDE.md"
fi

log "Bootstrap complete"
printf '\nNext steps:\n'
printf '1. Review %s\n' "$OVERLAY_PATH"
printf '2. Open the repo in Claude Code from %s\n' "$PROJECT_ROOT"
printf '3. Run /aidlc_start "<ticket or request>"\n'
