#!/usr/bin/env bash
set -euo pipefail

# hacky script that is referenced by global research commands

# Collect metadata
# %z (numeric ISO offset) rather than %Z: zone NAMES can themselves be
# numeric ("+03", "+1245") on some hosts, which downstream consumers
# cannot distinguish from malformed offsets.
DATETIME_TZ=$(date '+%Y-%m-%d %H:%M:%S %z')
FILENAME_TS=$(date '+%Y-%m-%d_%H-%M-%S')

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
 REPO_ROOT=$(git rev-parse --show-toplevel)
 REPO_NAME=$(basename "$REPO_ROOT")
 # In detached HEAD `--show-current` SUCCEEDS while printing nothing
 # (so a `||` fallback never fires); eval runs execute in detached
 # worktrees, and the research artifact contract requires a non-empty
 # branch value.
 GIT_BRANCH=$(git branch --show-current 2>/dev/null)
 if [ -z "$GIT_BRANCH" ]; then
  GIT_BRANCH="detached@$(git rev-parse --short HEAD)"
 fi
 GIT_COMMIT=$(git rev-parse HEAD)
else
 REPO_ROOT=""
 REPO_NAME=""
 GIT_BRANCH=""
 GIT_COMMIT=""
fi

# Print similar to the individual command outputs
echo "Current Date/Time (TZ): $DATETIME_TZ"
[ -n "$GIT_COMMIT" ] && echo "Current Git Commit Hash: $GIT_COMMIT"
[ -n "$GIT_BRANCH" ] && echo "Current Branch Name: $GIT_BRANCH"
[ -n "$REPO_NAME" ] && echo "Repository Name: $REPO_NAME"
echo "Timestamp For Filename: $FILENAME_TS"
