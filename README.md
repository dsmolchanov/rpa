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
| `/research_codebase` | Document and explain the codebase as it exists |
| `/create_plan` | Create detailed implementation plans through interactive iteration |
| `/implement_plan` | Execute approved plans with verification at each phase |
| `/iterate_plan` | Update existing plans based on feedback |
| `/enhance_plan` | Synthesize multiple opinions into plan improvements |
| `/enhance_research` | Improve research documents with additional findings |
| `/validate_plan` | Verify that a plan was correctly implemented |
| `/create_handoff` | Create handoff documents to transfer work between sessions |
| `/resume_handoff` | Resume work from a handoff document |
| `/commit` | Create well-structured git commits for session changes |
| `/debug` | Investigate problems via logs, DB state, and git history without editing files |
| `/create_test_plan` | Create comprehensive test plans and TDD strategies |
| `/tdd` | Execute full TDD cycle with Red/Green/Refactor verification |
| `/test_suite` | Create, update, and maintain test suites (audit, init, update, gaps, run, ci, standardize) |
| `/refactor_candidates` | Discover and index God-like modules as refactoring candidates |
| `/refactor` | Refactor monolithic modules into focused, testable modules |
| `/tech_debt_sweep` | Scan codebase for technical debt and generate paydown plan |
| `/tech_debt_trends` | Analyze technical debt trends over time |
| `/aidlc_init` | Bootstrap the current repository for the AI-DLC compatibility workflow |
| `/aidlc_start` | Initialize or resume the AI-DLC compatibility workflow |
| `/aidlc_inception` | Execute approved inception stages and generate canonical artifacts |
| `/aidlc_bolt` | Execute one construction unit in the AI-DLC workflow |
| `/aidlc_build_test` | Run the global Build and Test stage |
| `/aidlc_operations` | Generate experimental operations artifacts |
| `/aidlc_feedback` | Capture experimental retrospective feedback |

## When to Use Plugin vs Native Claude Code

Claude Code ships native skills and agents that partially overlap with this plugin. Use the right tool for the altitude of the task:

| Task | Use native | Use this plugin |
|------|-----------|-----------------|
| Clean up a diff (naming, dead code, small simplifications) | `/simplify` | — |
| Find bugs in a branch/PR diff | `/code-review` | — |
| Check an implementation against its plan and success criteria | — | `/validate_plan` (then follow up with `/code-review`) |
| Decompose a God module into focused modules (multi-phase, with API snapshots and rollback) | — | `/refactor`, `/refactor_candidates` |
| Ad-hoc "where is X / how does Y work" exploration | `Explore` agent | — |
| Durable research docs in `thoughts/shared/research/` | — | `/research_codebase` |
| Security audit of pending changes | `/security-review` | — |
| Find hardcoded config that should be externalized | — | `config-auditor` (via `/tech_debt_sweep`) |
| Deep multi-source web research report | `deep-research` | — |
| Targeted web lookups inside plan/research flows | — | `web-search-researcher` (spawned by `/create_plan`, `/research_codebase`) |

Rule of thumb: native skills work at the **diff level** on the current branch; this plugin works at the **workflow level** — persistent artifacts in `thoughts/`, multi-phase orchestration, and cross-session state.

## Installation

### Quick Install (Recommended)

Copy commands, agents, and scripts to your global Claude configuration:

```bash
# Create directories if they don't exist
mkdir -p ~/.claude/commands
mkdir -p ~/.claude/agents
mkdir -p ~/.claude/scripts
mkdir -p ~/.claude/skills
mkdir -p ~/.claude/hooks

# Copy commands
cp commands/*.md ~/.claude/commands/

# Copy agents (enables parallel sub-agents)
cp agents/*.md ~/.claude/agents/

# Copy workflow skill packages (kernels the commands delegate to)
cp -R skills/* ~/.claude/skills/

# Optional: copy the compatibility bootstrap if using AI-DLC workflows
cp CLAUDE.md ~/.claude/CLAUDE-rpa-aidlc.md

# Copy and make scripts executable
cp scripts/*.sh ~/.claude/scripts/
chmod +x ~/.claude/scripts/*.sh

# Optional: hooks for deterministic quality gates — merge the "hooks" object
# from hooks/hooks.json into ~/.claude/settings.json (hooks are read from
# settings, not from a standalone file; see "How Hooks Work" below)
cp hooks/run_gate.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/run_gate.py
```

### Plugin Install (Alternative)

Install as a Claude Code plugin (adds `rpa:` prefix to commands):

```bash
git clone https://github.com/dsmolchanov/rpa.git
claude plugin install --plugin-dir ./rpa
```

### Verify Installation

After installation, start Claude Code and check that commands are available:

```bash
# In Claude Code, these commands should now be available
/research_codebase
/create_plan
/implement_plan
/aidlc_init
/aidlc_start
```

## Directory Structure

After installation, your `~/.claude/` directory should look like:

```
~/.claude/
├── commands/
│   │                          # RPA core
│   ├── research_codebase.md
│   ├── create_plan.md
│   ├── implement_plan.md
│   ├── iterate_plan.md
│   ├── enhance_plan.md
│   ├── enhance_research.md
│   ├── validate_plan.md
│   ├── create_handoff.md
│   ├── resume_handoff.md
│   ├── commit.md
│   ├── debug.md
│   │                          # Testing
│   ├── create_test_plan.md
│   ├── tdd.md
│   ├── test_suite.md
│   │                          # Refactoring & tech debt
│   ├── refactor_candidates.md
│   ├── refactor.md
│   ├── tech_debt_sweep.md
│   ├── tech_debt_trends.md
│   │                          # AI-DLC compatibility
│   ├── aidlc_init.md
│   ├── aidlc_start.md
│   ├── aidlc_inception.md
│   ├── aidlc_bolt.md
│   ├── aidlc_build_test.md
│   ├── aidlc_operations.md
│   └── aidlc_feedback.md
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
│   ├── config-auditor.md
│   │                          # AI-DLC
│   ├── uow-decomposer.md
│   ├── steering-rules-checker.md
│   ├── quality-gate-runner.md
│   ├── operations-planner.md
│   └── feedback-collector.md
├── scripts/
│   ├── bootstrap_aidlc_project.sh
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
│   └── enhance-research/
│       ├── SKILL.md
│       └── references/
├── hooks/
│   └── run_gate.py
└── settings.json              # optional: "hooks" object merged from hooks/hooks.json
```

## Project Setup

For each project using the legacy RPA workflow, create a `thoughts/` directory structure:

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

## AI-DLC Compatibility Layer

This repo also includes an AWS AI-DLC-compatible facade for teams that want plugin-native slash commands while staying close to the upstream AI-DLC artifact model.

### Philosophy Difference

| Aspect | RPA (Legacy) | AI-DLC Facade |
|--------|-------------|--------------|
| Cycle | Linear: research -> plan -> implement -> validate | Stage-based compatibility flow with canonical state |
| Canonical Artifacts | `thoughts/shared/*` | `aidlc-docs/*` |
| Adaptivity | Same depth for all work | Stage selection in execution plan + depth per executed stage |
| Operations | Not covered | Experimental extension beyond upstream core |
| Feedback | Not covered | Experimental extension beyond upstream core |

### AI-DLC Commands

| Command | Phase | Description |
|---------|-------|-------------|
| `/aidlc_init` | Bootstrap | Create or refresh the repo-local AI-DLC substrate |
| `/aidlc_start` | Entry | Initialize state, resolve rules, write execution plan |
| `/aidlc_inception` | Inception | Execute approved inception stages |
| `/aidlc_bolt` | Construction | Execute one approved construction unit |
| `/aidlc_build_test` | Construction | Run the global Build and Test stage |
| `/aidlc_operations` | Operations (Experimental) | Generate deployment and rollback artifacts |
| `/aidlc_feedback` | Feedback (Experimental) | Capture structured retrospective feedback |

### Canonical Artifacts

The AI-DLC facade writes canonical artifacts under:

- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/audit.md`
- `aidlc-docs/inception/...`
- `aidlc-docs/construction/...`
- `aidlc-docs/operations/...`

### Plugin Overlay

Plugin-local conventions live in:

- `thoughts/shared/steering-rules/default.yaml`

That overlay is secondary. It does not replace canonical state or execution planning.

### Question Files

Required clarifications for AI-DLC flows should be written to markdown files and answered via `[Answer]:` tags rather than being handled only in chat.

### Project Setup

If a repo will use the AI-DLC compatibility layer, create:

```bash
mkdir -p aidlc-docs/{inception,construction,operations}
mkdir -p thoughts/shared/steering-rules
```

If you installed commands by copying files into `~/.claude/commands/`, also copy the compatibility rule details into the working repository:

```bash
cp -R /path/to/rpa/.aidlc-rule-details .
cp /path/to/rpa/CLAUDE.md .
```

### Bootstrap Script

For a first-time project bootstrap, use the helper script instead of creating the structure manually:

```bash
/path/to/rpa/scripts/bootstrap_aidlc_project.sh /path/to/project
```

What it does:
- creates `aidlc-docs/` with starter templates and `.gitkeep` files
- copies `.aidlc-rule-details/`
- creates `thoughts/shared/steering-rules/default.yaml`
- detects package-manager and test/build commands for the overlay
- copies `CLAUDE.md` if missing, or appends the AI-DLC bootstrap section if the repo already has its own `CLAUDE.md`

Useful flags:

```bash
/path/to/rpa/scripts/bootstrap_aidlc_project.sh --force-overlay /path/to/project
/path/to/rpa/scripts/bootstrap_aidlc_project.sh --force-claude /path/to/project
```

Example:

```bash
/Users/dmitrymolchanov/Programs/rpa/scripts/bootstrap_aidlc_project.sh /Users/dmitrymolchanov/Programs/teaming
```

After the script runs, review `thoughts/shared/steering-rules/default.yaml` before the first `/aidlc_build_test` because multi-stack repos may need command adjustments.

### `/aidlc_init` Wrapper

If the RPA scripts were copied into `~/.claude/scripts/`, you can bootstrap directly from Claude Code with:

```text
/aidlc_init
```

Optional flags:

```text
/aidlc_init --force-overlay
/aidlc_init --force-claude
```

`/aidlc_init` is a thin wrapper over `~/.claude/scripts/bootstrap_aidlc_project.sh`. It bootstraps the current repository root, then tells you to review the generated overlay and proceed to `/aidlc_start`.

### Quick Start

1. Open the target repo in Claude Code
2. Run `/aidlc_init`
3. Review `thoughts/shared/steering-rules/default.yaml`
4. Start the workflow with `/aidlc_start "<full request>"`
5. Answer any generated question files under `aidlc-docs/inception/questions/`
6. Run `/aidlc_inception`
7. Execute units with `/aidlc_bolt`
8. Run `/aidlc_build_test`
9. Optionally use `/aidlc_operations` and `/aidlc_feedback`

## Technical Debt Management

The repo includes commands for periodic technical debt reduction.

### Philosophy

Tech debt work follows the same RPA pattern as feature work:
1. **Research** (scan) - Discover what debt exists
2. **Plan** (prioritize) - Create actionable paydown plan
3. **Act** (apply) - Fix safe issues, plan larger refactors

### /tech_debt_sweep

Performs a comprehensive technical debt scan and generates actionable artifacts.

**Usage:**
```bash
/tech_debt_sweep        # Scan and generate report + plan
/tech_debt_sweep apply  # Auto-fix safe issues
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

- **Weekly**: Run `/tech_debt_sweep` every Friday
- **After sweep**: Review plan, run `/tech_debt_sweep apply`
- **Monthly**: Run `/tech_debt_trends` to track progress

### How Hooks Work

`hooks/hooks.json` defines three deterministic quality gates implemented by
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
/research_codebase
> How does the authentication system work?
```

The command will:
1. Spawn parallel agents to explore the codebase
2. Find relevant files and patterns
3. Create a research document at `thoughts/shared/research/YYYY-MM-DD-authentication-flow.md`

### Create an Implementation Plan

```
/create_plan
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

### /research_codebase

Creates documentation of how the codebase currently works. Uses parallel agents to explore efficiently.

**Key principles:**
- Document what IS, not what SHOULD BE
- No recommendations unless explicitly asked
- Include specific file:line references
- Save research for future reference

### /create_plan

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
