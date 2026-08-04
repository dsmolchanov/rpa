# Tech-debt quality gates

The RPA plugin binds formatting, lint, and related-test requirements through
[`hooks.json`](hooks.json) and the portable [`run_gate.py`](run_gate.py)
runner. The runner reports explicit gate outcomes and blocks applicable
failures with exit code 2.

## Outcomes

- `passed`: the applicable command completed successfully.
- `failed`: the gate was applicable but its input, runner, or command failed;
  Claude receives the failure and must address it before stopping.
- `not_applicable`: the repository/file does not register that gate; the
  reason is printed. This is distinct from a pass.

The built-in profile is deliberately narrow:

- Prettier only when a project-local binary exists and the edited suffix is
  supported. It never downloads a formatter through `npx`.
- Lint only when the root `package.json` defines `scripts.lint`.
- Related tests only for a Jest-backed root test script. All tracked and
  untracked changed files are passed as separate argv elements; filenames are
  never interpolated into a shell command.

Projects using Python, Go, Rust, monorepo package routing, or other test
runners should replace or extend `run_gate.py` with repository-owned gates
that preserve the same three-outcome contract.

## Sensitive files

Use Claude Code permissions for proactive protection:

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

Hooks execute with the user's environment credentials. Review the manifest
and runner before enabling them.
