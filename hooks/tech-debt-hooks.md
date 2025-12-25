# Tech Debt Hooks

Deterministic quality gates for tech debt management workflows.

## Overview

These hooks ensure quality checks run automatically and deterministically, preventing agents from "forgetting" to run verification steps.

## Installation

Hooks are configured in `.claude/settings.json` under the `hooks` key. Add the following configuration:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": {
          "tool_name": "Edit"
        },
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'FILE=$(cat | jq -r \".tool_input.file_path\"); command -v prettier >/dev/null 2>&1 && npx prettier --write \"$FILE\" 2>/dev/null || true'"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'command -v npm >/dev/null 2>&1 && npm run lint --silent 2>/dev/null || echo \"Lint: npm not found or no lint script\"'"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'MODIFIED=$(git diff --name-only 2>/dev/null | head -5); if [ -n \"$MODIFIED\" ]; then command -v npm >/dev/null 2>&1 && npm test -- --bail --findRelatedTests $MODIFIED 2>/dev/null || echo \"Tests: npm not found\"; fi'"
          }
        ]
      }
    ]
  }
}
```

## Sensitive File Protection

Instead of using hooks to block edits, use `permissions.deny` in your settings:

```json
{
  "permissions": {
    "deny": [
      "**/.env",
      "**/.env.*",
      "**/credentials*",
      "**/secrets*",
      "**/*.pem",
      "**/*.key"
    ]
  }
}
```

This is more reliable than hook-based blocking.

## Hooks Included

| Event | Purpose | When It Runs |
|-------|---------|--------------|
| PostToolUse (Edit) | Auto-format files after edits | After every Edit tool use |
| Stop | Run lint when Claude finishes | After Claude stops responding |
| Stop | Run related tests for modified files | After Claude stops responding |

## How Hooks Work

### PostToolUse Hooks
Receive tool input as JSON on stdin. Extract file path with:
```bash
FILE=$(cat | jq -r '.tool_input.file_path')
```

### Stop Hooks
Run when Claude finishes responding. No modified files list is provided directly, so use:
```bash
MODIFIED=$(git diff --name-only 2>/dev/null | head -5)
```

## Cross-Platform Compatibility

All hook commands use `command -v` to check if tools exist before running:
```bash
command -v prettier >/dev/null 2>&1 && npx prettier --write "$FILE" || true
```

**Windows Note**: These hooks are designed for Unix-like environments (Linux, macOS, WSL). Windows users may need to adjust command syntax or run in Git Bash.

## Customization

Adjust commands for your project:

| Default | Replace With |
|---------|--------------|
| `prettier` | Your formatter (black, gofmt, etc.) |
| `npm run lint` | Your linter (pylint, eslint, etc.) |
| `npm test` | Your test command (pytest, go test, etc.) |

### Example: Python Project
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": { "tool_name": "Edit" },
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'FILE=$(cat | jq -r \".tool_input.file_path\"); if [[ \"$FILE\" == *.py ]]; then command -v black >/dev/null 2>&1 && black \"$FILE\" 2>/dev/null || true; fi'"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "bash -c 'command -v pylint >/dev/null 2>&1 && pylint **/*.py --exit-zero 2>/dev/null || true'" }
        ]
      }
    ]
  }
}
```

## Security Considerations

- Hooks run automatically with your environment credentials
- Review hook commands before adding them to settings
- Be cautious with hooks that execute external commands
- Use `--silent` or `2>/dev/null` to suppress verbose output

## Debugging

Enable verbose output to debug hooks:
```bash
# Remove 2>/dev/null from commands temporarily
# Or add set -x to bash -c commands
bash -c 'set -x; FILE=$(cat | jq -r ".tool_input.file_path"); ...'
```

## Integration with Tech Debt Sweep

The hooks complement `/tech_debt_sweep` by:
1. **Preventing new debt** - Auto-format and lint catches issues early
2. **Ensuring quality** - Tests run for modified files
3. **Protecting secrets** - Deny rules prevent accidental credential edits

Together, they create a continuous quality improvement loop:
- `/tech_debt_sweep` finds existing debt
- Hooks prevent new debt from accumulating
