# RPA hooks

`hooks.json` registers three deterministic Claude Code gates implemented by
`run_gate.py`:

| Gate | Event | Applicability | Failure behavior |
|---|---|---|---|
| `format` | `PostToolUse` after `Edit` or `Write` | Prettier-managed file and local `node_modules/.bin/prettier` | exit 2 |
| `lint` | `Stop` | root `package.json` has a `lint` script | exit 2 |
| `related-tests` | `Stop` | root test script is Jest-backed and changed files exist | exit 2 |

Every invocation prints one machine-readable outcome: `passed`, `failed`, or
`not_applicable` with a reason. Missing applicability is not treated as a
pass, and applicable failures are never hidden.

Plugin installs discover `hooks/hooks.json` automatically and set
`CLAUDE_PLUGIN_ROOT`. For a manual install:

```bash
mkdir -p ~/.claude/hooks
cp hooks/run_gate.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/run_gate.py
# Merge the "hooks" object from hooks/hooks.json into
# ~/.claude/settings.json or the project's .claude/settings.json.
```

The manifest falls back to `$HOME/.claude/hooks/run_gate.py` when
`CLAUDE_PLUGIN_ROOT` is absent.

Hooks run with the user's environment and can execute project commands.
Review them before enabling. Sensitive-path protection belongs in Claude
Code `permissions.deny`, not in a post-hoc hook.

Run the focused smoke tests with:

```bash
python3 hooks/test_run_gate.py
```
