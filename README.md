# RPA - Research, Plan, Act

A collection of Claude Code slash commands for structured software development workflows. These commands help you systematically research codebases, create implementation plans, and execute them with proper verification.

## Philosophy

The RPA workflow encourages a methodical approach to software development:

1. **Research** - Understand the codebase before making changes
2. **Plan** - Create detailed, phased implementation plans with clear success criteria
3. **Act** - Implement the plan with continuous verification

This approach reduces errors, improves code quality, and creates documentation that helps with future maintenance.

## Commands Overview

| Command | Description |
|---------|-------------|
| `/research-codebase` | Document and explain the codebase as it exists |
| `/create-plan` | Create detailed implementation plans through interactive iteration |
| `/implement_plan` | Execute approved plans with verification at each phase |
| `/iterate-plan` | Update existing plans based on feedback |
| `/enhance-plan` | Synthesize multiple opinions into plan improvements |
| `/enhance-research` | Improve research documents with additional findings |
| `/validate_plan` | Verify that a plan was correctly implemented |
| `/create_handoff` | Create handoff documents to transfer work between sessions |
| `/resume_handoff` | Resume work from a handoff document |
| `/one-pager` | Digest the last work in a repository — what landed, what is open, what is next |
| `/commit` | Create well-structured git commits for session changes |
| `/debug` | Investigate problems via logs, DB state, and git history without editing files |
| `/create-test-plan` | Create comprehensive test plans and TDD strategies |
| `/tdd` | Execute full TDD cycle with Red/Green/Refactor verification |
| `/test_suite` | Create, update, and maintain test suites (audit, init, update, gaps, run, ci, standardize) |
| `/refactor_candidates` | Discover and index God-like modules as refactoring candidates |
| `/refactor` | Refactor monolithic modules into focused, testable modules |
| `/tech-debt-sweep` | Scan codebase for technical debt and generate paydown plan |
| `/tech_debt_trends` | Analyze technical debt trends over time |

### One-pager and scheduling

`/rpa:one-pager` writes a bounded, deterministic digest of a repository's
recent work to `thoughts/shared/one-pagers/`. It is refreshed on **events**,
never per commit:

- **Session end** — the `tdd`, `create_handoff`, and `validate_plan`
  workflows refresh it after writing their own artifact, so the log, handoff,
  or report they just produced is visible even though it is still uncommitted.
- **Default-branch push** — `.github/workflows/one-pager.yml` in this
  repository regenerates the page and publishes it to the job summary, an
  artifact, and the unprotected `status/one-pager` branch. It does not commit
  to a protected default branch. Other repositories adopt it by copying that
  workflow; nothing else needs installing, because the script travels with the
  plugin.
- **Schedule (cross-repository)** — run
  `/rpa:one-pager --repos <path> <path>…` from a **local** Claude Desktop
  scheduled task. The page lands in `$RPA_HOME/one-pagers/` (default
  `~/.rpa/one-pagers/`) and is never committed.

  A cloud Claude Code routine can also produce it, with different
  constraints: routines run against fresh clones of *selected GitHub
  repositories*, so they cannot see local paths or `~/.rpa`. Such a routine
  must install the plugin itself and post the result somewhere durable —
  nothing it writes to disk survives the run.

Regeneration is idempotent: an unchanged repository rewrites the same bytes,
so refreshing costs nothing and never produces spurious diffs.

## When to Use Plugin vs Native Claude Code

Claude Code ships native skills and agents that partially overlap with this plugin. Use the right tool for the altitude of the task:

| Task | Use native | Use this plugin |
|------|-----------|-----------------|
| Clean up a diff (naming, dead code, small simplifications) | `/simplify` | — |
| Find bugs in a branch/PR diff | `/code-review` | — |
| Check an implementation against its plan and success criteria | — | `/validate_plan` (then follow up with `/code-review`) |
| Decompose a God module into focused modules (multi-phase, with API snapshots and rollback) | — | `/refactor`, `/refactor_candidates` |
| Ad-hoc "where is X / how does Y work" exploration | `Explore` agent | — |
| Durable research docs in `thoughts/shared/research/` | — | `/research-codebase` |
| Security audit of pending changes | `/security-review` | — |
| Find hardcoded config that should be externalized | — | `config-auditor` (via `/tech-debt-sweep`) |
| Deep multi-source web research report | `deep-research` | — |
| Targeted web lookups inside plan/research flows | — | `web-search-researcher` (spawned by `/create-plan`, `/research-codebase`) |

Rule of thumb: native skills work at the **diff level** on the current branch; this plugin works at the **workflow level** — persistent artifacts in `thoughts/`, multi-phase orchestration, and cross-session state.

## Installation

### Plugin Install (Recommended)

Install from the marketplace (adds the `rpa:` prefix to commands, updates via `claude plugin update rpa`):

```bash
claude plugin marketplace add dsmolchanov/rpa
claude plugin install rpa@dsmolchanov-rpa
```

Codex CLI is also supported:

```bash
codex plugin marketplace add dsmolchanov/rpa --ref master
codex plugin add rpa@dsmolchanov-rpa
```

To pick up a new release later: `claude plugin update rpa` in Claude Code; in Codex run
`codex plugin marketplace upgrade dsmolchanov-rpa` followed by `codex plugin add rpa@dsmolchanov-rpa`.

### Manual Copy Install (Alternative)

> **Do not combine this with the plugin install.** Copied files and the installed
> plugin both register the same commands, agents, and skills, so every one of
> them shows up twice. Pick one method; if you switch to the plugin later,
> delete the copies from `~/.claude/commands`, `~/.claude/agents`, and
> `~/.claude/skills` first.

Copy commands, agents, and scripts to your global Claude configuration:

```bash
# Create directories if they don't exist
mkdir -p ~/.claude/commands
mkdir -p ~/.claude/agents
mkdir -p ~/.claude/scripts
mkdir -p ~/.claude/skills
mkdir -p ~/.claude/hooks

# Copy commands
cp plugins/rpa/commands/*.md ~/.claude/commands/

# Copy agents (enables parallel sub-agents)
cp plugins/rpa/agents/*.md ~/.claude/agents/

# Copy workflow skill packages (kernels the commands delegate to)
cp -R plugins/rpa/skills/* ~/.claude/skills/

# Copy and make scripts executable
cp plugins/rpa/scripts/*.sh ~/.claude/scripts/
chmod +x ~/.claude/scripts/*.sh

# Optional: hooks for deterministic quality gates — merge the "hooks" object
# from plugins/rpa/hooks/hooks.json into ~/.claude/settings.json (hooks are read from
# settings, not from a standalone file; see "How Hooks Work" below)
cp plugins/rpa/hooks/run_gate.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/run_gate.py
```

### Verify Installation

After installation, start Claude Code and check that commands are available:

```bash
# In Claude Code, these commands should now be available
# (plugin installs expose them with the rpa: prefix, e.g. /rpa:create-plan)
/research-codebase
/create-plan
/implement_plan
```

## Directory Structure

After a manual copy install, your `~/.claude/` directory should look like:

```
~/.claude/
├── commands/
│   │                          # RPA core
│   ├── implement_plan.md
│   ├── validate_plan.md
│   ├── create_handoff.md
│   ├── resume_handoff.md
│   ├── commit.md
│   ├── debug.md
│   │                          # Testing
│   ├── test_suite.md
│   │                          # Refactoring & tech debt
│   ├── refactor_candidates.md
│   ├── refactor.md
│   └── tech_debt_trends.md
├── agents/
│   │                          # Codebase research
│   ├── codebase-locator.md
│   ├── codebase-analyzer.md
│   ├── codebase-pattern-finder.md
│   ├── code-analyzer.md
│   ├── file-analyzer.md
│   ├── thoughts-locator.md
│   ├── thoughts-analyzer.md
│   ├── web-search-researcher.md
│   ├── parallel-worker.md
│   │                          # Testing
│   ├── test-analyzer.md
│   ├── test-architect.md
│   ├── test-generator.md
│   ├── test-runner.md
│   ├── test-updater.md
│   ├── test-refactorer.md
│   ├── test-impact-mapper.md
│   ├── coverage-reporter.md
│   │                          # Refactoring
│   ├── god-module-finder.md
│   ├── api-snapshotter.md
│   ├── responsibility-decomposer.md
│   ├── coupling-analyzer.md
│   ├── consumer-mapper.md
│   ├── refactor-validator.md
│   │                          # Tech debt
│   ├── debt-scanner.md
│   ├── dependency-auditor.md
│   ├── architecture-guard.md
│   ├── docs-auditor.md
│   └── config-auditor.md
├── scripts/
│   └── spec_metadata.sh
├── skills/
│   ├── research-codebase/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── create-plan/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── iterate-plan/
│   │   └── SKILL.md
│   ├── enhance-plan/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── enhance-research/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── create-test-plan/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── tdd/
│   │   ├── SKILL.md
│   │   └── references/
│   └── tech-debt-sweep/
│       ├── SKILL.md
│       └── references/
├── hooks/
│   └── run_gate.py
└── settings.json              # optional: "hooks" object merged from plugins/rpa/hooks/hooks.json
```

## Project Setup

For each project using the RPA workflow, create a `thoughts/` directory structure:

```bash
mkdir -p thoughts/shared/{research,plans,implementations,handoffs,debt}
```

This creates:
- `thoughts/shared/research/` - Research documents
- `thoughts/shared/plans/` - Implementation plans
- `thoughts/shared/implementations/` - Validation reports
- `thoughts/shared/handoffs/` - Session handoff documents
- `thoughts/shared/debt/` - Technical debt reports and paydown plans

**Important**: Ensure `thoughts/shared/debt/` is tracked in git (not in `.gitignore`) for trend analysis to work.

## Technical Debt Management

The repo includes commands for periodic technical debt reduction.

### Philosophy

Tech debt work follows the same RPA pattern as feature work:
1. **Research** (scan) - Discover what debt exists
2. **Plan** (prioritize) - Create actionable paydown plan
3. **Act** (apply) - Fix safe issues, plan larger refactors

### /tech-debt-sweep

Performs a comprehensive technical debt scan and generates actionable artifacts.

**Usage:**
```bash
/tech-debt-sweep        # Scan and generate report + plan
/tech-debt-sweep apply  # Auto-fix safe issues
```

**What it scans:**
- Dependencies (security, outdated, unused)
- Code debt markers (TODO/FIXME, lint suppressions)
- Architecture (boundaries, cycles, god modules)
- Documentation (README accuracy, docstrings)
- Configuration (hardcoded values, credentials)

**Output:**
- `thoughts/shared/debt/YYYY-MM-DD-tech-debt-sweep.md` - Debt report
- `thoughts/shared/debt/YYYY-MM-DD-tech-debt-paydown.md` - Paydown plan

### /tech_debt_trends

Analyzes debt trajectory by comparing historical sweep reports.

**Usage:**
```bash
/tech_debt_trends      # Analyze last 4 weeks
/tech_debt_trends 8    # Analyze last 8 weeks
```

**Requires:** At least 2 previous debt sweeps

### New Agents

These specialized agents support the debt sweep:

| Agent | Purpose |
|-------|---------|
| `dependency-auditor` | Security vulnerabilities, outdated packages |
| `debt-scanner` | TODO/FIXME, lint suppressions, complexity |
| `architecture-guard` | Boundary violations, circular deps |
| `docs-auditor` | README accuracy, docstring coverage |
| `config-auditor` | Hardcoded values, credential detection |

### Recommended Schedule

- **Weekly**: Run `/tech-debt-sweep` every Friday
- **After sweep**: Review plan, run `/tech-debt-sweep apply`
- **Monthly**: Run `/tech_debt_trends` to track progress

### How Hooks Work

`plugins/rpa/hooks/hooks.json` defines three deterministic quality gates implemented by
`hooks/run_gate.py` — no model judgment involved:

1. **PostToolUse (`Edit|Write`)** — formats supported files with the
   project-local Prettier binary. It never downloads tooling through `npx`.
2. **Stop (lint)** — runs `npm run lint --silent` only when the root
   `package.json` registers a lint script.
3. **Stop (related tests)** — passes all tracked and untracked changed files
   as separate argv elements to a Jest-backed test script.

Every gate prints `passed`, `failed`, or `not_applicable` with a reason.
Applicable failures exit 2 and are not hidden; missing applicability is never
reported as a pass.

**Installation**: plugin installs pick up `hooks/hooks.json` automatically.
For a manual install, copy `hooks/run_gate.py` to `~/.claude/hooks/` and
merge the `"hooks"` object into `~/.claude/settings.json` (or the project's
`.claude/settings.json`).

**Caveats**: the bundled profile is npm/Jest-centric by design. Other
toolchains should extend the runner while preserving its three-outcome
contract. Hooks execute project commands with your environment credentials —
review before enabling.

### Whitelist for False Positives

Create `thoughts/shared/debt/.whitelist` to exclude files/patterns from scans:

```
# Exclude intentionally hardcoded config
src/config/defaults.ts

# Exclude legacy code that's being replaced
legacy/**

# Exclude specific TODO that's deferred
src/api/client.ts:45
```

Agents will check this file and skip whitelisted items.

## Usage Examples

### Research a Codebase

```
/research-codebase
> How does the authentication system work?
```

The command will:
1. Spawn parallel agents to explore the codebase
2. Find relevant files and patterns
3. Create a research document at `thoughts/shared/research/YYYY-MM-DD-authentication-flow.md`

### Create an Implementation Plan

```
/create-plan
> Add rate limiting to the API endpoints
```

The command will:
1. Research existing patterns in your codebase
2. Ask clarifying questions
3. Create a phased implementation plan
4. Save it to `thoughts/shared/plans/YYYY-MM-DD-rate-limiting.md`

### Implement a Plan

```
/implement_plan thoughts/shared/plans/2025-01-15-rate-limiting.md
```

The command will:
1. Read the plan and understand each phase
2. Implement changes for each phase
3. Run automated verification
4. Pause for manual verification before continuing
5. Update checkboxes in the plan as work completes

### Validate Implementation

```
/validate_plan thoughts/shared/plans/2025-01-15-rate-limiting.md
```

The command will:
1. Compare actual changes against the plan
2. Run all verification commands
3. Generate a validation report
4. List any deviations or issues found

## Best Practices

### Research Phase
- Always research before planning
- Document what EXISTS, not what SHOULD BE
- Include file:line references for easy navigation
- Create research documents for future reference

### Planning Phase
- Break work into small, testable phases
- Include both automated AND manual success criteria
- Define what's NOT in scope to prevent creep
- Get feedback on structure before writing details

### Implementation Phase
- Follow the plan's intent, adapt when reality differs
- Run verification after each phase
- Update plan checkboxes as you complete work
- Pause for manual verification before proceeding

### Handoffs
- Create handoffs at end of sessions or before context switches
- Include learnings and gotchas discovered
- Reference specific file:line for recent changes
- List explicit next steps for the resuming agent

## Command Details

### /research-codebase

Creates documentation of how the codebase currently works. Uses parallel agents to explore efficiently.

**Key principles:**
- Document what IS, not what SHOULD BE
- No recommendations unless explicitly asked
- Include specific file:line references
- Save research for future reference

### /create-plan

Creates a persistent, implementation-ready plan grounded in the current
checkout. The command is a thin Claude adapter over the shared
`skills/create-plan/` workflow kernel.

**Flow:**
1. Read any referenced files
2. Research the affected code and established patterns
3. Resolve only material scope or architecture decisions
4. Write dependency-ordered phases with exact success criteria
5. Iterate based on feedback

### /implement_plan

Executes an approved implementation plan.

**Flow:**
1. Read plan and identify starting point
2. Implement each phase
3. Run automated verification
4. Pause for manual verification
5. Continue to next phase

### /validate_plan

Verifies that an implementation matches its plan.

**Checks:**
- All phases marked complete are actually done
- Automated verification passes
- Code follows existing patterns
- No regressions introduced

## Customization

### Adding Custom Commands

Create new `.md` files in `~/.claude/commands/` following the existing patterns. Commands can:
- Inherit the active session model by default; add a model pin only for a
  documented, evaluated capability or cost requirement
- Include step-by-step instructions
- Reference other commands
- Use sub-agents for parallel work

### Modifying Existing Commands

Edit the command files directly. Key sections to customize:
- Initial response and prompts
- Success criteria templates
- Document output formats
- Directory paths for your project structure

## Troubleshooting

### Commands not appearing

1. Check files are in `~/.claude/commands/`
2. Verify file extension is `.md`
3. Restart Claude Code

### Scripts not running

1. Check scripts are in `~/.claude/scripts/`
2. Verify executable permissions: `chmod +x ~/.claude/scripts/*.sh`
3. Test script directly: `~/.claude/scripts/spec_metadata.sh`

### thoughts/ directory issues

1. Create the directory structure manually:
   ```bash
   mkdir -p thoughts/shared/{research,plans,implementations,handoffs}
   ```
2. Add to `.gitignore` if you don't want to commit these files

## License

MIT License - feel free to use, modify, and share these commands.

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with clear description of changes
