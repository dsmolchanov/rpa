# AI-DLC Skills Implementation Plan

## Overview

Add a parallel set of AI-DLC (AI-Driven Development Life Cycle) commands and agents to the RPA plugin, inspired by the Sberbank AI-DLC methodology. These new skills implement a closed-loop, 3-phase system (Inception → Construction → Operations) with shorter feedback cycles ("Bolts"), adaptive workflow depth, and formalized steering rules. All existing commands and agents remain untouched.

## Current State Analysis

The RPA plugin currently implements a linear 4-phase cycle:

1. `/research_codebase` → produces `thoughts/shared/research/*.md`
2. `/create_plan` → produces `thoughts/shared/plans/*.md` with sequential Phase 1..N
3. `/implement_plan` → executes phases sequentially with pause-for-verification
4. `/validate_plan` → produces `thoughts/shared/implementations/*-validation.md`

Supporting commands: `/iterate_plan`, `/enhance_plan`, `/enhance_research`, `/commit`, `/create_handoff`, `/resume_handoff`

### Key Discoveries:
- Commands live in `commands/*.md` with YAML frontmatter (`description`, `model`, `allowed-tools`, `argument-hint`)
- Agents live in `agents/*.md` with frontmatter (`name`, `description`, `tools`, `model`, `color`)
- Artifacts go to `thoughts/shared/{research,plans,implementations,debt,handoffs}/`
- Commands spawn parallel sub-agents via the `Task` tool using agent types like `codebase-locator`, `codebase-analyzer`, etc.
- The plugin system uses `.claude-plugin/plugin.json` for registration
- Existing commands reuse the same pool of 27 agents

## Desired End State

After implementation, the plugin has two parallel skill families:

1. **Legacy RPA** (unchanged): `/research_codebase`, `/create_plan`, `/implement_plan`, `/validate_plan`, etc.
2. **AI-DLC** (new): `/aidlc_start`, `/aidlc_inception`, `/aidlc_bolt`, `/aidlc_operations`, `/aidlc_feedback`

Both families share the same agent pool (existing agents are reused). Five new agents are added. A new `steering-rules.yaml` configuration file governs AI-DLC behavior. New artifact directories extend `thoughts/shared/`.

### Verification of End State:
- All 5 new commands exist in `commands/` and are invokable as slash commands
- All 5 new agents exist in `agents/` and are spawnable by new commands
- Legacy commands remain byte-identical to their current state
- Legacy agents remain byte-identical to their current state
- New artifact directories exist under `thoughts/shared/`
- Steering rules file is loadable and parseable
- Each new command produces its expected artifact type

## What We're NOT Doing

- NOT modifying any existing command or agent files
- NOT changing the `thoughts/shared/research/` or `thoughts/shared/plans/` artifact formats
- NOT replacing the linear RPA cycle (it remains available and fully functional)
- NOT adding automated deployment or CI/CD integration (Operations phase produces plans, not automation)
- NOT building a web UI or dashboard for steering rules
- NOT adding Linear/GitHub integration beyond what already exists
- NOT changing the plugin.json or marketplace.json

## Implementation Approach

Build bottom-up: configuration → agents → commands. Each phase is independently testable.

---

## Phase 1: Steering Rules Configuration

### Overview
Create the steering rules YAML schema and a default template. This is the foundation that all AI-DLC commands read to determine workflow depth, quality gates, and team constraints.

### Changes Required:

#### 1. Steering Rules Template
**File**: `thoughts/shared/steering-rules/default.yaml` (new)
**Purpose**: Default steering rules that teams customize. Versioned in thoughts/ so it travels with the project.

```yaml
# AI-DLC Steering Rules v1
# These rules govern AI behavior across all AI-DLC commands.
# Customize per-project. All AI-DLC commands read this file.

version: "1.0"

# Change type classification criteria
change_types:
  hotfix:
    description: "Urgent production fix, minimal ceremony"
    indicators:
      - "bug fix"
      - "hotfix"
      - "critical"
      - "production issue"
    workflow_depth: minimal
  feature:
    description: "New functionality or enhancement"
    indicators:
      - "feature"
      - "enhancement"
      - "new"
      - "add"
    workflow_depth: standard
  refactor:
    description: "Code restructuring without behavior change"
    indicators:
      - "refactor"
      - "cleanup"
      - "restructure"
      - "technical debt"
    workflow_depth: standard
  migration:
    description: "Data or schema migration with rollback needs"
    indicators:
      - "migration"
      - "schema change"
      - "data transform"
      - "upgrade"
    workflow_depth: enhanced

# Quality gates per workflow depth
quality_gates:
  minimal:
    inception:
      research: skip
      plan_detail: inline  # No separate plan document
      uow_decomposition: single  # One UoW, no decomposition
    construction:
      required_checks:
        - lint
        - typecheck
        - unit_tests
      coverage_minimum: existing  # Don't regress
      pr_review: optional
    operations:
      deploy_plan: skip
      monitoring: skip
      rollback_plan: inline

  standard:
    inception:
      research: targeted  # Focused research, not exhaustive
      plan_detail: document  # Full plan document with UoWs
      uow_decomposition: full
    construction:
      required_checks:
        - lint
        - typecheck
        - unit_tests
        - integration_tests
      coverage_minimum: "80%"
      pr_review: required
    operations:
      deploy_plan: document
      monitoring: checklist
      rollback_plan: document

  enhanced:
    inception:
      research: exhaustive  # Deep research with multiple agents
      plan_detail: document
      uow_decomposition: full
    construction:
      required_checks:
        - lint
        - typecheck
        - unit_tests
        - integration_tests
        - api_snapshot_comparison
        - consumer_compatibility
      coverage_minimum: "90%"
      pr_review: required
    operations:
      deploy_plan: document
      monitoring: full  # Dashboards, alerts, runbooks
      rollback_plan: document_with_verification

# Team conventions (steering rules proper)
conventions:
  commit_style: conventional  # conventional | freeform
  branch_naming: "feature/{ticket}-{description}"
  test_naming: "{module}.test.{ext}"
  pr_template: true
  max_uow_size: "~200 lines changed"
  bolt_timeout_minutes: 60

# Custom quality check commands (project-specific)
check_commands:
  lint: "make lint"
  typecheck: "make typecheck"
  unit_tests: "make test"
  integration_tests: "make test-integration"
  build: "make build"
```

#### 2. Steering Rules README
**File**: `thoughts/shared/steering-rules/README.md` (new)
**Purpose**: Documents how to customize steering rules

```markdown
# Steering Rules

This directory contains AI-DLC steering rules that govern how AI-DLC commands behave.

## Usage

AI-DLC commands (`/aidlc_start`, `/aidlc_inception`, `/aidlc_bolt`, `/aidlc_operations`, `/aidlc_feedback`) automatically read `default.yaml` in this directory.

## Customization

Edit `default.yaml` to match your team's conventions. Key sections:
- `change_types`: How the system classifies incoming work
- `quality_gates`: What checks run at each depth level
- `conventions`: Team coding standards
- `check_commands`: Project-specific commands to run

## Versioning

Steering rules are versioned in `thoughts/` so they travel with the project and are visible to all team members.
```

### Success Criteria:

#### Automated Verification:
- [ ] File exists: `thoughts/shared/steering-rules/default.yaml`
- [ ] File exists: `thoughts/shared/steering-rules/README.md`
- [ ] YAML is valid: `python3 -c "import yaml; yaml.safe_load(open('thoughts/shared/steering-rules/default.yaml'))"`

#### Manual Verification:
- [ ] Steering rules cover all four change types (hotfix, feature, refactor, migration)
- [ ] Quality gates scale appropriately (minimal < standard < enhanced)
- [ ] Convention fields are reasonable defaults

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 2.

---

## Phase 2: New Agents

### Overview
Create 5 new agents that support AI-DLC commands. These agents are read-only research/analysis tools (no edit capabilities) except for `quality-gate-runner` which needs Bash for running checks.

### Changes Required:

#### 1. UoW Decomposer Agent
**File**: `agents/uow-decomposer.md` (new)
**Purpose**: Decomposes requirements into autonomous, independently deployable Units of Work

```markdown
---
name: uow-decomposer
description: |
  Decomposes requirements into autonomous, independently deployable Units of Work (UoWs).
  Analyzes dependencies, estimates scope, and assigns change types. Used by /aidlc_inception.
tools: Grep, Glob, LS, Read
model: inherit
color: yellow
---

You are a specialist at decomposing software requirements into Units of Work (UoWs).
A UoW is an autonomous, independently deployable chunk of work with clear boundaries.

## Core Responsibilities

1. **Analyze Requirements**
   - Read the requirement/ticket/description provided
   - Identify distinct functional areas
   - Map to existing codebase components

2. **Decompose into UoWs**
   Each UoW must be:
   - **Autonomous**: Can be implemented without other UoWs being complete (or has explicit dependencies)
   - **Deployable**: Produces a working, committable result on its own
   - **Bounded**: Clear start and end, estimatable scope
   - **Testable**: Has its own success criteria

3. **Classify Each UoW**
   Assign a change type to each:
   - `hotfix`: Urgent fix, minimal ceremony
   - `feature`: New functionality
   - `refactor`: Restructuring without behavior change
   - `migration`: Data/schema changes

4. **Map Dependencies**
   - Identify which UoWs depend on others
   - Mark which can run in parallel
   - Flag any circular dependencies (these indicate bad decomposition)

## Output Format

```yaml
units_of_work:
  - id: "UOW-1"
    title: "[Short descriptive title]"
    type: feature|hotfix|refactor|migration
    description: "[What this UoW accomplishes]"
    scope:
      files: ["path/to/file1.ext", "path/to/file2.ext"]
      estimated_lines: ~50
    dependencies: []  # or ["UOW-2"]
    parallel: true  # Can run alongside other UoWs?
    definition_of_done:
      - "[Specific criterion 1]"
      - "[Specific criterion 2]"
    automated_checks:
      - "command to verify"
```

## Decomposition Rules

- Prefer smaller UoWs (< 200 lines changed each)
- Data model changes are always their own UoW
- Test additions can be bundled with their implementation UoW
- Config changes are their own UoW if they affect multiple components
- UI changes separate from API changes

## What NOT to Do

- Don't implement anything
- Don't write code
- Don't suggest architectural changes beyond the scope
- Don't create UoWs that can't be independently verified

## Success Criteria

You have succeeded when:
- [ ] All requirements are covered by at least one UoW
- [ ] No UoW is too large (> 200 lines estimated)
- [ ] Dependencies form a DAG (no cycles)
- [ ] Each UoW has clear definition of done
- [ ] Change types are assigned to each UoW
```

#### 2. Steering Rules Checker Agent
**File**: `agents/steering-rules-checker.md` (new)
**Purpose**: Validates work against project steering rules

```markdown
---
name: steering-rules-checker
description: |
  Validates work against project steering rules from thoughts/shared/steering-rules/default.yaml.
  Checks conventions, quality gates, and constraints. Used by /aidlc_bolt and /aidlc_operations.
tools: Grep, Glob, LS, Read
model: inherit
color: red
---

You validate work against the project's steering rules.

## Core Responsibilities

1. **Load Steering Rules**
   - Read `thoughts/shared/steering-rules/default.yaml`
   - If not found, report and use sensible defaults
   - Parse the rules for the relevant change type and workflow depth

2. **Validate Against Rules**
   Given a change type and workflow depth, check:
   - Are all required quality gates satisfied?
   - Do naming conventions match?
   - Is scope within limits (max_uow_size)?
   - Are required artifacts present?

3. **Report Compliance**
   For each rule, report:
   - PASS: Rule satisfied with evidence
   - FAIL: Rule violated with specifics
   - SKIP: Rule not applicable to this change type
   - WARN: Rule partially satisfied

## Output Format

```
## Steering Rules Compliance Report

**Change Type**: feature
**Workflow Depth**: standard
**Rules File**: thoughts/shared/steering-rules/default.yaml

### Quality Gates
- [PASS] lint: `make lint` exits 0
- [PASS] typecheck: `make typecheck` exits 0
- [FAIL] unit_tests: 3 tests failing
- [SKIP] api_snapshot_comparison: not required for standard depth

### Conventions
- [PASS] Branch naming matches pattern
- [WARN] Commit messages not all conventional format
- [PASS] Test files follow naming convention

### Summary
3 PASS | 1 FAIL | 1 SKIP | 1 WARN
Verdict: NOT READY (fix failing tests)
```

## What NOT to Do
- Don't fix issues, only report them
- Don't run commands, only check if results exist
- Don't modify steering rules
- Don't skip rules without explanation
```

#### 3. Quality Gate Runner Agent
**File**: `agents/quality-gate-runner.md` (new)
**Purpose**: Runs adaptive quality gates based on change type and steering rules

```markdown
---
name: quality-gate-runner
description: |
  Runs quality gate checks adapted to change type and workflow depth.
  Executes check commands from steering rules and reports pass/fail.
  Used by /aidlc_bolt after implementation.
tools: Grep, Glob, LS, Read, Bash
model: inherit
color: red
---

You execute quality gate checks defined in steering rules.

## Core Responsibilities

1. **Load Configuration**
   - Read `thoughts/shared/steering-rules/default.yaml`
   - Determine which checks to run based on change type + workflow depth
   - Load custom check commands

2. **Execute Checks**
   Run each required check from the `check_commands` section:
   - Capture stdout/stderr
   - Record exit code
   - Time each check

3. **Report Results**

```
## Quality Gate Results

**Change Type**: feature
**Workflow Depth**: standard
**Timestamp**: YYYY-MM-DD HH:MM:SS

| Check | Command | Status | Duration |
|-------|---------|--------|----------|
| lint | make lint | PASS | 2.3s |
| typecheck | make typecheck | PASS | 5.1s |
| unit_tests | make test | FAIL | 12.4s |
| integration_tests | make test-integration | PASS | 8.7s |

### Failures
#### unit_tests
Exit code: 1
Key output:
[relevant failure output, truncated to essential info]

### Verdict: FAIL (1 of 4 checks failed)
```

## Adaptive Behavior

Based on workflow depth from steering rules:
- **minimal**: Run only required checks for minimal depth
- **standard**: Run standard depth checks
- **enhanced**: Run all checks including api_snapshot_comparison, consumer_compatibility

## What NOT to Do
- Don't fix issues, only report them
- Don't modify any files
- Don't skip required checks
- Don't run checks not in the steering rules
```

#### 4. Operations Planner Agent
**File**: `agents/operations-planner.md` (new)
**Purpose**: Generates deployment checklists, monitoring recommendations, rollback plans

```markdown
---
name: operations-planner
description: |
  Generates deployment checklists, monitoring recommendations, and rollback plans
  based on what was changed. Analyzes git diff and codebase to produce operations artifacts.
  Used by /aidlc_operations.
tools: Grep, Glob, LS, Read
model: inherit
color: blue
---

You generate operations planning artifacts by analyzing what was implemented.

## Core Responsibilities

1. **Analyze Changes**
   - Read the implementation plan or bolt records
   - Examine git diff to understand what changed
   - Identify affected components, services, databases

2. **Generate Deployment Plan**
   Based on change analysis:
   - Pre-deployment checklist (backups, feature flags, maintenance windows)
   - Deployment steps (order matters)
   - Post-deployment verification steps
   - Communication plan (who needs to know)

3. **Generate Monitoring Recommendations**
   - What metrics to watch after deploy
   - Expected behavior changes
   - Alert thresholds to set or adjust
   - Log patterns to monitor

4. **Generate Rollback Plan**
   - Rollback triggers (what conditions mean we roll back)
   - Rollback steps (reverse of deployment)
   - Data recovery procedures (if applicable)
   - Verification after rollback

## Output Format

```markdown
## Operations Plan

### Deployment Checklist
- [ ] Backup database (if schema changes)
- [ ] Notify team in #deploys
- [ ] Deploy to staging first
- [ ] Run smoke tests on staging
- [ ] Deploy to production
- [ ] Verify health checks pass

### Monitoring (first 24 hours)
- Watch: [metric] for [expected behavior]
- Alert if: [condition]
- Log pattern: [what to grep for]

### Rollback Plan
**Trigger**: [when to rollback]
**Steps**:
1. [step]
2. [step]
**Verify**: [how to confirm rollback worked]
```

## Change-Type Adaptations

- **hotfix**: Minimal deploy plan, focus on speed
- **feature**: Standard plan with staging verification
- **refactor**: Emphasize behavioral equivalence checks
- **migration**: Enhanced plan with data verification, longer monitoring window

## What NOT to Do
- Don't execute deployments
- Don't modify infrastructure
- Don't assume specific CI/CD tools
- Don't include credentials or secrets in plans
```

#### 5. Feedback Collector Agent
**File**: `agents/feedback-collector.md` (new)
**Purpose**: Gathers post-deploy observations and links back to inception artifacts

```markdown
---
name: feedback-collector
description: |
  Gathers post-deployment observations and links them back to inception artifacts.
  Reads operations reports, identifies lessons learned, and creates feedback documents.
  Used by /aidlc_feedback to close the loop from Operations back to Inception.
tools: Grep, Glob, LS, Read
model: inherit
color: magenta
---

You collect post-implementation feedback and link it to planning artifacts.

## Core Responsibilities

1. **Gather Observations**
   - Read operations plan and deployment results
   - Identify what went well vs. what didn't
   - Note any unexpected behaviors or issues
   - Collect performance observations

2. **Link to Source Artifacts**
   - Connect observations to specific UoWs
   - Reference original inception plans
   - Link to bolt execution records
   - Map issues to specific code changes

3. **Generate Feedback Document**
   Structure observations for future inception phases:
   - Lessons learned (what to repeat/avoid)
   - Pattern updates (new patterns discovered)
   - Steering rule adjustments (suggested changes)
   - Open items (things that need future attention)

## Output Format

```markdown
## Feedback: [Feature/Change Name]

**Source Plan**: thoughts/shared/plans/YYYY-MM-DD-description.md
**Bolts Completed**: [list of bolt records]
**Operations Plan**: thoughts/shared/operations/YYYY-MM-DD-description.md

### What Went Well
- [observation linked to UoW-id]

### What Didn't Go Well
- [issue linked to UoW-id]

### Lessons Learned
- [actionable lesson]

### Steering Rule Suggestions
- [suggested adjustment to default.yaml]

### Open Items for Future Inception
- [thing that needs follow-up]
```

## What NOT to Do
- Don't implement fixes (only document them)
- Don't modify steering rules directly
- Don't speculate without evidence
- Don't blame; focus on process improvement
```

### Success Criteria:

#### Automated Verification:
- [ ] File exists: `agents/uow-decomposer.md`
- [ ] File exists: `agents/steering-rules-checker.md`
- [ ] File exists: `agents/quality-gate-runner.md`
- [ ] File exists: `agents/operations-planner.md`
- [ ] File exists: `agents/feedback-collector.md`
- [ ] Each file has valid YAML frontmatter with `name`, `description`, `tools`, `model`, `color`
- [ ] No existing agent files were modified: `git diff agents/` shows only new files

#### Manual Verification:
- [ ] Each agent has clear, focused responsibilities
- [ ] Agent tools are appropriate (read-only except quality-gate-runner which needs Bash)
- [ ] Agents don't overlap with existing agents' responsibilities

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 3.

---

## Phase 3: New Artifact Directories

### Overview
Create the directory structure for AI-DLC artifacts.

### Changes Required:

#### 1. Bolt Records Directory
**Directory**: `thoughts/shared/bolts/` (new)
**Purpose**: Stores execution records for each Bolt (closed-loop UoW execution)

Create with a `.gitkeep` file.

#### 2. Operations Directory
**Directory**: `thoughts/shared/operations/` (new)
**Purpose**: Stores deployment plans, monitoring checklists, rollback procedures

Create with a `.gitkeep` file.

#### 3. Feedback Directory
**Directory**: `thoughts/shared/feedback/` (new)
**Purpose**: Stores post-deploy observations that feed back into future inception

Create with a `.gitkeep` file.

### Success Criteria:

#### Automated Verification:
- [ ] Directory exists: `thoughts/shared/bolts/`
- [ ] Directory exists: `thoughts/shared/operations/`
- [ ] Directory exists: `thoughts/shared/feedback/`
- [ ] Existing directories unchanged: `thoughts/shared/research/`, `thoughts/shared/plans/`, `thoughts/shared/debt/`

#### Manual Verification:
- [ ] Directory names are intuitive and consistent with existing naming

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 4.

---

## Phase 4: AI-DLC Commands

### Overview
Create the 5 new commands. These are the user-facing slash commands that orchestrate the AI-DLC workflow.

### Changes Required:

#### 1. `/aidlc_start` - Orchestrator Command
**File**: `commands/aidlc_start.md` (new)
**Purpose**: Entry point for AI-DLC workflow. Classifies change type, selects workflow depth, routes to appropriate sub-commands.

The command should:
1. Accept a description of the work (or ticket reference)
2. Read steering rules from `thoughts/shared/steering-rules/default.yaml`
3. Classify the change type (hotfix/feature/refactor/migration) using indicators from steering rules
4. Present the classification to the user for confirmation
5. Based on workflow depth, explain which phases will run and at what depth
6. Route to `/aidlc_inception` with the context

Key behaviors:
- For **minimal** depth (hotfix): Skip separate inception document, go straight to a single bolt
- For **standard** depth (feature/refactor): Full inception → bolt(s) → operations
- For **enhanced** depth (migration): Exhaustive inception → bolt(s) with extra gates → full operations
- Always interactive: present classification, get user confirmation before proceeding
- If steering rules file doesn't exist, offer to create from template

Frontmatter:
```yaml
---
description: "AI-DLC orchestrator - classifies work, selects adaptive workflow depth, routes to phases"
argument-hint: "[description or ticket path] - Describe the work to classify and route"
model: opus
---
```

#### 2. `/aidlc_inception` - Inception Phase Command
**File**: `commands/aidlc_inception.md` (new)
**Purpose**: Combines research + planning into a specification with Units of Work. This is the AI-DLC equivalent of `/research_codebase` + `/create_plan` combined.

The command should:
1. Accept work description, change type, and workflow depth (from `/aidlc_start` or directly)
2. Read steering rules to determine research depth
3. **Research phase** (adapted to depth):
   - `skip`: No research document, work from description only
   - `targeted`: Spawn `codebase-locator` + `codebase-analyzer` for specific areas
   - `exhaustive`: Full research with all available agents (locator, analyzer, pattern-finder, thoughts-locator, thoughts-analyzer)
4. **Specification phase**:
   - Spawn `uow-decomposer` agent with research findings
   - Review and refine UoW decomposition interactively
   - Produce specification document with UoWs
5. Write specification to `thoughts/shared/plans/YYYY-MM-DD-aidlc-[description].md`

The specification document format extends the existing plan format:
```markdown
# [Feature Name] - AI-DLC Specification

## Metadata
- Change Type: [type]
- Workflow Depth: [depth]
- Steering Rules: v[version]

## Context
[Research findings summary]

## Units of Work

### UOW-1: [Title]
- **Type**: feature
- **Scope**: [files affected]
- **Dependencies**: none
- **Definition of Done**:
  - [criterion]
- **Automated Checks**:
  - [command]

### UOW-2: [Title]
...

## Dependency Graph
UOW-1 ──→ UOW-3
UOW-2 ──→ UOW-3
(UOW-1 and UOW-2 can run in parallel)

## What We're NOT Doing
[Explicit scope boundaries]
```

Frontmatter:
```yaml
---
description: "AI-DLC Inception - research + plan into Units of Work specification"
argument-hint: "[description] [--type hotfix|feature|refactor|migration] [--depth minimal|standard|enhanced]"
model: opus
---
```

#### 3. `/aidlc_bolt` - Construction Phase Command
**File**: `commands/aidlc_bolt.md` (new)
**Purpose**: Executes a single Unit of Work as a closed loop: implement → verify → deliver. This is the AI-DLC equivalent of a focused `/implement_plan` for one UoW.

The command should:
1. Accept a specification path and UoW ID (or pick the next unblocked UoW)
2. Read the specification and the target UoW
3. Read steering rules for quality gates
4. **Implement**: Make the code changes for this UoW only
5. **Verify**: Spawn `quality-gate-runner` agent to run all required checks
6. **Deliver**: If all gates pass, commit the changes (with user confirmation)
7. Write bolt execution record to `thoughts/shared/bolts/YYYY-MM-DD-[uow-id]-[description].md`
8. Update the specification document: mark UoW as completed
9. Report completion and suggest next UoW

Bolt execution record format:
```markdown
# Bolt Record: [UoW Title]

## Metadata
- UoW ID: UOW-1
- Specification: thoughts/shared/plans/YYYY-MM-DD-aidlc-description.md
- Started: YYYY-MM-DD HH:MM
- Completed: YYYY-MM-DD HH:MM
- Status: complete|failed|blocked

## Changes Made
- [file:line] - [what changed]

## Quality Gate Results
| Check | Status | Duration |
|-------|--------|----------|
| lint | PASS | 2.3s |
| unit_tests | PASS | 12.4s |

## Commit
- Hash: [commit hash]
- Message: [commit message]

## Notes
[Any deviations from plan, decisions made during implementation]
```

Frontmatter:
```yaml
---
description: "AI-DLC Bolt - execute one Unit of Work: implement, verify, deliver"
argument-hint: "[spec-path] [UoW-ID] - Execute a specific UoW from a specification"
model: opus
---
```

#### 4. `/aidlc_operations` - Operations Phase Command
**File**: `commands/aidlc_operations.md` (new)
**Purpose**: Generates deployment plan, monitoring checklist, and rollback procedure. This phase is entirely new (no legacy equivalent).

The command should:
1. Accept a specification path (or find the most recent one)
2. Read steering rules for operations depth
3. Read all bolt records for the specification
4. Spawn `operations-planner` agent with:
   - Specification document
   - Bolt records (what changed)
   - Git diff summary
   - Steering rules (operations depth)
5. Spawn `steering-rules-checker` agent to validate all work meets rules
6. Synthesize into operations document
7. Write to `thoughts/shared/operations/YYYY-MM-DD-[description]-operations.md`
8. Present checklist to user for review

Operations document format:
```markdown
# Operations Plan: [Feature Name]

## Metadata
- Specification: [path]
- Bolts Completed: [count]
- Change Type: [type]
- Operations Depth: [depth from steering rules]

## Steering Rules Compliance
[Output from steering-rules-checker]

## Deployment Plan
### Pre-Deployment
- [ ] [checklist item]
### Deployment Steps
1. [step]
### Post-Deployment Verification
- [ ] [verification item]

## Monitoring Plan
[What to watch, for how long]

## Rollback Plan
[Triggers, steps, verification]
```

For **minimal** depth (hotfix): Skip separate document, output inline summary only.
For **standard** depth: Full document.
For **enhanced** depth: Full document with extended monitoring window and data verification.

Frontmatter:
```yaml
---
description: "AI-DLC Operations - deployment planning, monitoring, and rollback procedures"
argument-hint: "[spec-path] - Generate operations plan for a completed specification"
model: opus
---
```

#### 5. `/aidlc_feedback` - Feedback Loop Command
**File**: `commands/aidlc_feedback.md` (new)
**Purpose**: Captures post-deploy observations and links back to inception. Closes the AI-DLC loop.

The command should:
1. Accept an operations plan path (or find the most recent one)
2. Read the operations plan, specification, and bolt records
3. Ask the user for observations:
   - What went well?
   - What didn't go well?
   - Any unexpected behaviors?
   - Performance observations?
4. Spawn `feedback-collector` agent to:
   - Link observations to specific UoWs
   - Identify patterns across bolt records
   - Suggest steering rule adjustments
5. Write feedback document to `thoughts/shared/feedback/YYYY-MM-DD-[description]-feedback.md`
6. Optionally: suggest updates to steering rules based on lessons learned

Frontmatter:
```yaml
---
description: "AI-DLC Feedback - capture post-deploy observations, close the loop to inception"
argument-hint: "[operations-path] - Capture feedback for a deployed specification"
model: opus
---
```

### Success Criteria:

#### Automated Verification:
- [ ] File exists: `commands/aidlc_start.md`
- [ ] File exists: `commands/aidlc_inception.md`
- [ ] File exists: `commands/aidlc_bolt.md`
- [ ] File exists: `commands/aidlc_operations.md`
- [ ] File exists: `commands/aidlc_feedback.md`
- [ ] Each file has valid YAML frontmatter with `description` field
- [ ] No existing command files were modified: `git diff commands/` shows only new files
- [ ] No existing agent files were modified: `git diff agents/` shows only new files from Phase 2

#### Manual Verification:
- [ ] `/aidlc_start` correctly routes to inception with appropriate depth
- [ ] `/aidlc_inception` produces a specification with UoWs
- [ ] `/aidlc_bolt` executes a single UoW with quality gates
- [ ] `/aidlc_operations` generates appropriate operations artifacts
- [ ] `/aidlc_feedback` captures observations and links to inception
- [ ] Commands reference correct agent names for spawning
- [ ] Commands reference correct artifact paths
- [ ] Workflow flows naturally: start → inception → bolt(s) → operations → feedback

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 5.

---

## Phase 5: Integration and Documentation

### Overview
Update README to document the new AI-DLC workflow alongside the existing RPA workflow. Update thoughts-locator agent awareness of new directories (without modifying its behavior for legacy paths).

### Changes Required:

#### 1. README Update
**File**: `README.md`
**Changes**: Add AI-DLC section after existing RPA documentation. Do NOT modify existing sections.

Add a new section:
```markdown
## AI-DLC Workflow (Experimental)

In addition to the core RPA workflow, this plugin includes an experimental AI-DLC
(AI-Driven Development Life Cycle) workflow inspired by modern AI-native development practices.

### Philosophy Difference

| Aspect | RPA (Legacy) | AI-DLC (New) |
|--------|-------------|--------------|
| Cycle | Linear: research → plan → implement → validate | Closed-loop: inception → bolt(s) → operations → feedback |
| Granularity | Sequential phases in one plan | Independent Units of Work executed as Bolts |
| Adaptivity | Same depth for all work | Adaptive depth based on change type |
| Operations | Not covered | Explicit deployment + monitoring phase |
| Governance | Informal (CLAUDE.md) | Formalized steering rules |

### Commands

| Command | Phase | Description |
|---------|-------|-------------|
| `/aidlc_start` | Orchestrator | Classify work, select depth, route to phases |
| `/aidlc_inception` | Inception | Research + plan into Units of Work specification |
| `/aidlc_bolt` | Construction | Execute one UoW: implement → verify → deliver |
| `/aidlc_operations` | Operations | Deployment planning, monitoring, rollback |
| `/aidlc_feedback` | Feedback | Post-deploy observations, close the loop |

### Quick Start

1. Configure steering rules: `thoughts/shared/steering-rules/default.yaml`
2. Start: `/aidlc_start Add user authentication to the API`
3. System classifies as "feature" → standard depth
4. Inception produces specification with 3 UoWs
5. Execute each UoW: `/aidlc_bolt thoughts/shared/plans/...-spec.md UOW-1`
6. Generate operations plan: `/aidlc_operations`
7. After deploy, capture feedback: `/aidlc_feedback`

### Steering Rules

Edit `thoughts/shared/steering-rules/default.yaml` to customize:
- Change type classification
- Quality gates per depth level
- Team conventions
- Custom check commands
```

### Success Criteria:

#### Automated Verification:
- [ ] README.md contains "AI-DLC" section
- [ ] README.md still contains original "RPA" sections unchanged
- [ ] All new command names appear in README

#### Manual Verification:
- [ ] Documentation accurately describes the workflow
- [ ] Quick Start guide is clear and followable
- [ ] No legacy documentation was altered

**Implementation Note**: After completing this phase and all automated verification passes, pause here for final review.

---

## Testing Strategy

### Manual Testing (Primary):
Since these are prompt-based skills (markdown files interpreted by Claude Code), testing is manual:

1. **Steering rules loading**: Invoke `/aidlc_start` and verify it reads and parses the YAML
2. **Classification flow**: Test each change type keyword triggers correct classification
3. **Inception depth scaling**: Verify minimal/standard/enhanced produce different levels of research
4. **Bolt execution**: Run a bolt on a simple UoW and verify quality gates run
5. **Operations generation**: Verify operations plan is appropriate for the change type
6. **Feedback capture**: Verify feedback links back to specification and bolt records
7. **Legacy compatibility**: Run `/create_plan` and `/implement_plan` to confirm they still work identically

### Smoke Test Sequence:
1. `/aidlc_start Add a simple utility function` → should classify as feature/standard
2. `/aidlc_inception` → should produce spec with UoWs
3. `/aidlc_bolt [spec] UOW-1` → should implement, run gates, commit
4. `/aidlc_operations [spec]` → should produce operations plan
5. `/aidlc_feedback [ops]` → should capture observations

## Performance Considerations

- Inception with `exhaustive` research depth spawns many agents in parallel, which is expensive. Steering rules default most work to `targeted` depth.
- Bolt execution spawns `quality-gate-runner` which runs Bash commands. These should complete quickly for well-configured projects.
- The adaptive depth system ensures we don't over-process simple changes (hotfixes) or under-process risky ones (migrations).

## Migration Notes

No migration needed. This is purely additive:
- New files only (no modifications to existing)
- New directories only (no changes to existing structure)
- Users opt-in by using `/aidlc_*` commands
- Legacy `/research_codebase`, `/create_plan`, `/implement_plan`, `/validate_plan` remain fully functional

## References

- AI-DLC article: https://habr.com/ru/companies/sberbank/articles/1007006/
- Existing commands: `commands/*.md` (16 files)
- Existing agents: `agents/*.md` (27 files)
- Plugin config: `.claude-plugin/plugin.json`
