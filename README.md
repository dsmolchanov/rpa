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

## Installation

### Quick Install (Recommended)

Copy the commands and scripts to your global Claude configuration:

```bash
# Create directories if they don't exist
mkdir -p ~/.claude/commands
mkdir -p ~/.claude/scripts

# Copy commands
cp commands/*.md ~/.claude/commands/

# Copy and make scripts executable
cp scripts/*.sh ~/.claude/scripts/
chmod +x ~/.claude/scripts/*.sh
```

### Manual Installation

1. Download or clone this repository
2. Copy the contents of `commands/` to `~/.claude/commands/`
3. Copy the contents of `scripts/` to `~/.claude/scripts/`
4. Ensure scripts are executable: `chmod +x ~/.claude/scripts/*.sh`

### Verify Installation

After installation, start Claude Code and check that commands are available:

```bash
# In Claude Code, these commands should now be available
/research_codebase
/create_plan
/implement_plan
```

## Directory Structure

After installation, your `~/.claude/` directory should look like:

```
~/.claude/
├── commands/
│   ├── research_codebase.md
│   ├── create_plan.md
│   ├── implement_plan.md
│   ├── iterate_plan.md
│   ├── enhance_plan.md
│   ├── enhance_research.md
│   ├── validate_plan.md
│   ├── create_handoff.md
│   └── resume_handoff.md
└── scripts/
    └── spec_metadata.sh
```

## Project Setup

For each project using RPA, create a `thoughts/` directory structure:

```bash
mkdir -p thoughts/shared/{research,plans,implementations,handoffs}
```

This creates:
- `thoughts/shared/research/` - Research documents
- `thoughts/shared/plans/` - Implementation plans
- `thoughts/shared/implementations/` - Validation reports
- `thoughts/shared/handoffs/` - Session handoff documents

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

Interactive command that creates detailed implementation plans.

**Flow:**
1. Read any referenced files
2. Research the codebase
3. Present understanding and ask questions
4. Propose plan structure
5. Write detailed plan with success criteria
6. Iterate based on feedback

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
- Specify a preferred model with `model: opus` in frontmatter
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
