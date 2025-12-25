# Tech Debt Hooks

Deterministic quality gates for the RPA workflow.

## Installation

Copy to your Claude configuration:

```bash
cp hooks/*.md ~/.claude/hooks/
```

## Available Hooks

| Hook | Purpose |
|------|---------|
| [tech-debt-hooks.md](./tech-debt-hooks.md) | Quality gates for tech debt management |

## How It Works

Hooks are configured in `.claude/settings.json`. See [tech-debt-hooks.md](./tech-debt-hooks.md) for:
- Full configuration examples
- Hook event types (PostToolUse, Stop)
- Cross-platform compatibility notes
- Customization for different projects

## Security Note

Hooks run automatically with your environment credentials. Review before installing.
