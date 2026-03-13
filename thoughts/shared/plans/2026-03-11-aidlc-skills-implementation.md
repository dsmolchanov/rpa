# AWS AI-DLC-Compatible Skills Implementation Plan

## Overview

Add an AWS AI-DLC-compatible command facade to the RPA plugin. The facade should map plugin-native `/aidlc_*` commands onto the current `awslabs/aidlc-workflows` stage model and artifact conventions, while keeping two plugin-specific extensions: `/aidlc_operations` and `/aidlc_feedback`. Canonical AI-DLC artifacts live under `aidlc-docs/`; `thoughts/shared/` is used only for plugin-facing summaries, overlays, and indexes. Existing legacy commands and agents remain behaviorally untouched.

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
- `.claude-plugin/plugin.json` currently contains plugin metadata only, so command/agent availability is file-driven rather than manifest-driven
- Existing commands reuse the same pool of 27 agents
- `README.md` currently enumerates only the legacy workflow and project setup directories, so AI-DLC requires documentation changes in more than one section to avoid stale guidance
- The current AWS AI-DLC upstream for alignment is release `v0.1.6`, published on March 5, 2026
- Upstream Claude Code packaging is rule-file based (`CLAUDE.md` + `.aidlc-rule-details/`), not slash-command based
- Upstream canonical artifacts live in `aidlc-docs/` with persistent `aidlc-state.md` and `audit.md`
- Upstream requires file-based questions with `[Answer]:` tags and separates stage selection from depth selection
- Upstream Operations is still a placeholder and Feedback is not part of the core stage model

## Desired End State

After implementation, the plugin has two complementary skill families:

1. **Legacy RPA** (unchanged): `/research_codebase`, `/create_plan`, `/implement_plan`, `/validate_plan`, etc.
2. **AI-DLC Facade** (new): `/aidlc_start`, `/aidlc_inception`, `/aidlc_bolt`, `/aidlc_build_test`, `/aidlc_operations`, `/aidlc_feedback`

The AI-DLC facade shares the existing agent pool where practical and adds five new AI-DLC support agents. Canonical workflow artifacts are written under `aidlc-docs/` following the upstream stage structure. A plugin-local YAML overlay remains available for command mappings and local conventions, but stage execution is driven by AWS AI-DLC-compatible execution planning rather than by YAML depth flags. `/aidlc_operations` and `/aidlc_feedback` are explicitly documented as experimental extensions beyond current upstream core parity.

### Verification of End State:
- All 6 new commands exist in `commands/` and are invokable as slash commands
- All 5 new agents exist in `agents/` and are spawnable by new commands
- Legacy commands remain byte-identical to their current state
- Legacy agents remain byte-identical to their current state
- Canonical AI-DLC artifact directories exist under `aidlc-docs/`
- `aidlc-docs/aidlc-state.md` and `aidlc-docs/audit.md` are created and updated
- Rule-details loading follows upstream search order
- Extensions loading follows upstream opt-in semantics
- The plugin overlay file is loadable and parseable
- Each command produces its expected AWS-compatible artifact type
- README/project setup documentation reflects the new workflow without leaving stale command or directory lists behind
- The plan explicitly labels Operations/Feedback as experimental extensions relative to upstream core

## What We're NOT Doing

- NOT modifying any existing command files
- NOT modifying any existing agent files in v1
- NOT changing the `thoughts/shared/research/` or `thoughts/shared/plans/` artifact formats for legacy RPA flows
- NOT replacing the linear RPA cycle (it remains available and fully functional)
- NOT claiming full parity with future AWS Operations/Feedback phases that do not yet exist upstream
- NOT moving application source code under `aidlc-docs/`
- NOT building a web UI or dashboard for steering rules
- NOT adding Linear/GitHub integration beyond what already exists
- NOT changing the plugin.json or marketplace.json
- NOT introducing additional generic code-writing agents beyond the five AI-DLC support agents defined in this plan

## Implementation Approach

Build bottom-up: compatibility substrate → plugin overlay → agents → facade commands → documentation. Each phase is independently testable.

Design invariants for the implementation:
- Treat the plugin as an AWS AI-DLC compatibility layer, not as a second independent lifecycle
- Canonical documentation artifacts live in `aidlc-docs/`; `thoughts/shared/` may contain summaries or plugin indexes only
- Separate stage selection from depth: workflow planning decides EXECUTE/SKIP, while depth determines detail level inside executed stages
- Use file-based question documents with `[Answer]:` tags for all AI-DLC clarifications
- Reuse legacy command structure where practical (`/create_plan`, `/implement_plan`, `/validate_plan`) to reduce prompt drift and maintenance overhead
- Separate gate execution from compliance: `quality-gate-runner` executes build/test outputs, while the compliance checker validates extension and overlay adherence
- Keep the implementation additive at the workflow level: no existing user flow should require migration or behavioral change
- Pin compatibility to a specific verified upstream release rather than tracking `main`

---

## Phase 0: Compatibility Substrate

### Overview
Create the upstream-compatible file and state substrate before introducing plugin-local overlays or slash commands. This phase is what makes the plugin a compatibility facade rather than a parallel invention.

### Changes Required:

#### 1. Canonical Artifact Root
**Directory**: `aidlc-docs/` (new)
**Purpose**: Canonical source of truth for AWS AI-DLC-compatible artifacts.

Create the initial structure:

```text
aidlc-docs/
├── aidlc-state.md
├── audit.md
├── inception/
│   ├── plans/
│   │   └── execution-plan.md
│   ├── requirements/
│   ├── reverse-engineering/
│   ├── user-stories/
│   ├── application-design/
│   └── units/
├── construction/
│   ├── units/
│   └── build-and-test/
└── operations/
```

#### 2. Persistent State File
**File**: `aidlc-docs/aidlc-state.md` (new)
**Purpose**: Session resume point and current workflow truth.

The file should track:
- Upstream compatibility version (`v0.1.6` at initial implementation time)
- Current request/work item
- Workspace type (greenfield/brownfield)
- Active extensions
- Current stage and current depth
- Artifact pointers
- Approval status of major checkpoints

#### 3. Audit Trail
**File**: `aidlc-docs/audit.md` (new)
**Purpose**: Append-only record of raw user inputs, stage decisions, approvals, and generated artifact references.

#### 4. Rule Resolution
**Directories/Files**:
- `CLAUDE.md` (existing, loaded by host tool)
- `.aidlc-rule-details/` (new or mirrored compatibility directory)
- `extensions/` (existing-or-new opt-in rules directory)

**Purpose**: Mirror the upstream rule-loading model as closely as the plugin architecture allows.

Resolution behavior:
- Load the pinned upstream-compatible rule details first
- Load repo-local `.aidlc-rule-details/` overrides second
- Load enabled extension rules from `extensions/` third
- Record the resolved rule set in `aidlc-state.md`

#### 5. Execution Plan Baseline
**File**: `aidlc-docs/inception/plans/execution-plan.md` (new)
**Purpose**: The approved source of truth for which stages execute or skip, and why.

The execution plan must record:
- Stage name
- Decision: `EXECUTE` or `SKIP`
- Rationale
- Depth used for that stage
- Required approvals

### Success Criteria:

#### Automated Verification:
- [x] Directory exists: `aidlc-docs/`
- [x] File exists: `aidlc-docs/aidlc-state.md`
- [x] File exists: `aidlc-docs/audit.md`
- [x] File exists: `aidlc-docs/inception/plans/execution-plan.md`
- [x] Rule-resolution order is documented in the compatibility substrate
- [x] `aidlc-state.md` contains upstream compatibility version `v0.1.6`

#### Manual Verification:
- [ ] A resumed session can reconstruct prior context from `aidlc-state.md` and `audit.md`
- [ ] Stage decisions are captured in `execution-plan.md` rather than inferred from depth alone
- [ ] The directory layout is recognizably aligned with upstream AI-DLC artifacts

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 1.

---

## Phase 1: Plugin Overlay Configuration

### Overview
Create a plugin-local overlay for command mappings, repo conventions, and default commands. This is intentionally not the canonical AI-DLC steering mechanism; it augments the compatibility substrate for plugin-specific concerns only.

### Changes Required:

#### 1. Plugin Overlay Template
**File**: `thoughts/shared/steering-rules/default.yaml` (new)
**Purpose**: Plugin-local overlay for command mappings, commit conventions, default check commands, and experimental-feature toggles.

```yaml
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
  branch_naming: "feature/{ticket}-{description}"
  test_naming: "{module}.test.{ext}"
  max_unit_size: "~200 lines changed"
  experimental_extensions:
    operations: true
    feedback: true

default_commands:
  lint: "make lint"
  typecheck: "make typecheck"
  unit_tests: "make test"
  integration_tests: "make test-integration"
  build: "make build"
```

#### 2. Overlay README
**File**: `thoughts/shared/steering-rules/README.md` (new)
**Purpose**: Documents the difference between upstream-compatible artifacts and plugin-local overlay behavior.

The README must state clearly:
- `aidlc-docs/` is canonical
- `thoughts/shared/steering-rules/default.yaml` is a plugin overlay, not the primary source of workflow truth
- Stage EXECUTE/SKIP decisions belong in `aidlc-docs/inception/plans/execution-plan.md`
- Depth values are `minimal`, `standard`, and `comprehensive`

### Success Criteria:

#### Automated Verification:
- [x] File exists: `thoughts/shared/steering-rules/default.yaml`
- [x] File exists: `thoughts/shared/steering-rules/README.md`
- [x] YAML is valid: `python3 -c "import yaml; yaml.safe_load(open('thoughts/shared/steering-rules/default.yaml'))"`
- [x] Overlay uses `comprehensive` rather than `enhanced`

#### Manual Verification:
- [ ] The overlay contains only plugin-local concerns, not stage EXECUTE/SKIP logic
- [ ] The README makes the canonical-vs-overlay distinction explicit
- [ ] The overlay is useful even if upstream rule-details change later

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 2.

---

## Phase 2: New Agents

### Overview
Create 5 new agents that support AI-DLC commands. These agents are read-only research/analysis tools (no edit capabilities) except for `quality-gate-runner` which needs Bash for running checks.

### Changes Required:

#### 1. UoW Decomposer Agent
**File**: `agents/uow-decomposer.md` (new)
**Purpose**: Generates AWS AI-DLC-style unit planning artifacts from approved inception outputs

```markdown
---
name: uow-decomposer
description: |
  Generates AI-DLC-compatible unit planning artifacts from approved requirements,
  workflow planning, and application design. Used by /aidlc_inception.
tools: Grep, Glob, LS, Read
model: inherit
color: yellow
---

You are a specialist at generating Units of Work from approved inception artifacts.
A unit is a logical grouping of stories/work that can be implemented coherently; in a monolith, one unit may cover the entire app with internal modules.

## Core Responsibilities

1. **Analyze Requirements**
   - Read approved requirements artifacts
   - Read workflow planning decisions
   - Read application design and user-story artifacts when present
   - Map units to existing codebase components

2. **Decompose into UoWs**
   Each unit should be:
   - **Coherent**: Represents a logical slice of approved work
   - **Bounded**: Has clear scope and estimatable effort
   - **Traceable**: Links back to requirements/stories/design
   - **Testable**: Can feed later construction/build-test stages

3. **Classify Each UoW**
   Assign a change type to each:
   - `hotfix`: Urgent fix, minimal ceremony
   - `feature`: New functionality
   - `refactor`: Restructuring without behavior change
   - `migration`: Data/schema changes

4. **Map Dependencies**
   - Identify which units depend on others
   - Flag optional parallelism
   - Flag circular dependencies (these indicate bad decomposition)
   - Produce dependency artifacts expected by the compatibility facade

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
    parallel: true
    definition_of_done:
      - "[Specific criterion 1]"
      - "[Specific criterion 2]"
    automated_checks:
      - "command to verify"
```

Also generate companion artifact summaries for:
- `aidlc-docs/inception/units/unit-of-work.md`
- `aidlc-docs/inception/units/unit-of-work-dependency.md`
- `aidlc-docs/inception/units/unit-of-work-story-map.md`

## Decomposition Rules

- Prefer smaller units, but allow a single monolith-spanning unit when upstream-compatible planning calls for it
- Data model changes are often their own unit, but may remain coupled when approved design requires it
- Test additions can be bundled with their implementation unit
- Config changes are their own unit if they affect multiple components
- UI changes separate from API changes

## What NOT to Do

- Don't implement anything
- Don't write code
- Don't suggest architectural changes beyond the scope
- Don't create units that can't be independently verified

## Success Criteria

You have succeeded when:
- [ ] All requirements are covered by at least one UoW
- [ ] Each unit traces back to approved inception artifacts
- [ ] Dependencies form a DAG (no cycles)
- [ ] Each unit has a clear definition of done
- [ ] Change types are assigned to each UoW
```

#### 2. Steering Rules Checker Agent
**File**: `agents/steering-rules-checker.md` (new)
**Purpose**: Validates work against the active compatibility rule set

```markdown
---
name: steering-rules-checker
description: |
  Validates work against active AWS AI-DLC extensions plus the plugin-local overlay.
  Checks conventions, stage compliance, and artifact completeness. Used by
  /aidlc_build_test and /aidlc_operations.
tools: Grep, Glob, LS, Read
model: inherit
color: red
---

You validate work against the active compatibility rule set.

## Core Responsibilities

1. **Load Active Rules**
   - Read `aidlc-docs/aidlc-state.md` for active extensions and current stage
   - Read resolved rule-details / extension references
   - Read `thoughts/shared/steering-rules/default.yaml` as plugin overlay only

2. **Validate Against Rules**
   Given the current stage and workflow depth, check using persisted artifacts rather than live execution:
   - Are required stage artifacts present?
   - Are enabled extensions satisfied?
   - Do plugin overlay conventions match?
   - Is scope within limits (`max_unit_size`)?
   - Does the build/test output contain enough evidence to justify PASS/WARN/FAIL?

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
**Compatibility State**: aidlc-docs/aidlc-state.md

### Quality Gates
- [PASS] lint: Build-and-test report shows `make lint` exited 0
- [PASS] typecheck: Build-and-test report shows `make typecheck` exited 0
- [FAIL] unit_tests: Build-and-test report captured 3 failing tests
- [SKIP] api_snapshot_comparison: not required for standard depth

### Conventions
- [PASS] Branch naming matches pattern recorded in bolt metadata
- [WARN] Commit message in bolt record is not conventional format
- [PASS] Test files follow naming convention

### Summary
3 PASS | 1 FAIL | 1 SKIP | 1 WARN
Verdict: NOT READY (fix failing tests)
```

## What NOT to Do
- Don't fix issues, only report them
- Don't rerun quality gates that should already be captured by `quality-gate-runner`
- Don't modify extension rules or the plugin overlay
- Don't skip rules without explanation
```

#### 3. Quality Gate Runner Agent
**File**: `agents/quality-gate-runner.md` (new)
**Purpose**: Runs the global Build and Test stage using active overlay defaults

```markdown
---
name: quality-gate-runner
description: |
  Runs the always-on Build and Test stage for completed units.
  Executes plugin-overlay default commands and reports pass/fail.
  Used by /aidlc_build_test.
tools: Grep, Glob, LS, Read, Bash
model: inherit
color: red
---

You execute the Build and Test stage after units are completed.

## Core Responsibilities

1. **Load Configuration**
   - Read `aidlc-docs/aidlc-state.md`
   - Read `thoughts/shared/steering-rules/default.yaml`
   - Determine which checks apply based on the approved execution plan and overlay defaults

2. **Execute Checks**
   Run the required Build and Test checks:
   - Capture stdout/stderr
   - Record exit code
   - Time each check
   - Return a structured summary that `/aidlc_build_test` persists into `aidlc-docs/construction/build-and-test/build-and-test-report.md`

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
- **comprehensive**: Run all checks including api_snapshot_comparison, consumer_compatibility

## What NOT to Do
- Don't fix issues, only report them
- Don't modify any files
- Don't skip required checks
- Don't run checks that are not enabled by the approved execution plan and plugin overlay
```

#### 4. Operations Planner Agent
**File**: `agents/operations-planner.md` (new)
**Purpose**: Generates experimental deployment/monitoring/rollback artifacts beyond current upstream core parity

```markdown
---
name: operations-planner
description: |
  Generates deployment checklists, monitoring recommendations, and rollback plans
  based on what was changed. Analyzes git diff and codebase to produce
  experimental operations artifacts. Used by /aidlc_operations.
tools: Grep, Glob, LS, Read, Bash
model: inherit
color: blue
---

You generate experimental operations planning artifacts by analyzing what was implemented.

## Core Responsibilities

1. **Analyze Changes**
   - Read canonical AI-DLC artifacts from `aidlc-docs/`
   - Examine git history/diffs (using Bash) to understand exactly what changed
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
   - Mark uncertain items as `MANUAL REVIEW REQUIRED` rather than inventing unsupported steps

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
- **migration**: Comprehensive plan with data verification, longer monitoring window

## What NOT to Do
- Don't execute deployments
- Don't modify infrastructure
- Don't assume specific CI/CD tools
- Don't include credentials or secrets in plans
```

#### 5. Feedback Collector Agent
**File**: `agents/feedback-collector.md` (new)
**Purpose**: Gathers experimental retrospective observations and links them back to canonical AI-DLC artifacts

```markdown
---
name: feedback-collector
description: |
  Gathers post-deployment observations and links them back to inception artifacts.
  Reads operations reports, identifies lessons learned, and creates feedback documents.
  Used by /aidlc_feedback as a plugin extension beyond upstream core workflow.
tools: Grep, Glob, LS, Read
model: inherit
color: magenta
---

You collect post-implementation feedback and link it to canonical AI-DLC artifacts.

## Core Responsibilities

1. **Gather Observations**
   - Read operations plan and deployment results
   - Read file-based feedback question answers when present
   - Identify what went well vs. what didn't
   - Note any unexpected behaviors or issues
   - Collect performance observations

2. **Link to Source Artifacts**
   - Connect observations to specific units
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

**Source Plan**: aidlc-docs/inception/plans/execution-plan.md
**Units Completed**: [list of construction unit artifacts]
**Operations Plan**: aidlc-docs/operations/YYYY-MM-DD-description.md

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
- [x] File exists: `agents/uow-decomposer.md`
- [x] File exists: `agents/steering-rules-checker.md`
- [x] File exists: `agents/quality-gate-runner.md`
- [x] File exists: `agents/operations-planner.md`
- [x] File exists: `agents/feedback-collector.md`
- [x] Each file has valid YAML frontmatter with `name`, `description`, `tools`, `model`, `color`
- [x] No existing agent files were modified: `git diff agents/` shows only new files
- [x] Agent prompts reference canonical `aidlc-docs/` artifacts rather than using `thoughts/shared/` as the source of truth

#### Manual Verification:
- [ ] Each agent has clear, focused responsibilities
- [ ] Agent tools are appropriate (read-only except quality-gate-runner which needs Bash)
- [ ] Agents don't overlap with existing agents' responsibilities
- [ ] Operations/Feedback are clearly framed as experimental extensions, not upstream-core parity claims

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 3.

---

## Phase 3: Canonical Artifact Directories

### Overview
Create the canonical AWS-compatible artifact structure under `aidlc-docs/`, and keep any `thoughts/shared/` usage clearly secondary.

### Changes Required:

#### 1. Inception Artifact Directories
Create:
- `aidlc-docs/inception/plans/`
- `aidlc-docs/inception/questions/`
- `aidlc-docs/inception/requirements/`
- `aidlc-docs/inception/reverse-engineering/`
- `aidlc-docs/inception/user-stories/`
- `aidlc-docs/inception/application-design/`
- `aidlc-docs/inception/units/`

#### 2. Construction Artifact Directories
Create:
- `aidlc-docs/construction/units/`
- `aidlc-docs/construction/build-and-test/`

#### 3. Operations Artifact Directory
Create:
- `aidlc-docs/operations/`

#### 4. Optional Plugin Index Directory
If useful for discoverability, create:
- `thoughts/shared/aidlc/`

This directory may contain summaries or pointers only. It must not become a second source of truth.

### Success Criteria:

#### Automated Verification:
- [x] Directories exist under `aidlc-docs/` for inception, construction, and operations
- [x] `aidlc-docs/inception/questions/` exists for file-based question artifacts
- [x] `aidlc-docs/construction/build-and-test/` exists for the global Build and Test stage
- [x] Any `thoughts/shared/aidlc/` usage is documented as summary/index-only

#### Manual Verification:
- [ ] Artifact paths visibly mirror the upstream AI-DLC shape
- [ ] Canonical-vs-summary ownership is unambiguous

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 4.

---

## Phase 4: AI-DLC Facade Commands

### Overview
Create six slash commands that act as a plugin-native facade over the upstream AI-DLC stage model. The first four commands map to core parity goals; the last two are explicit experimental extensions.

### Changes Required:

#### 1. `/aidlc_start` - Compatibility Entry Command
**File**: `commands/aidlc_start.md` (new)
**Purpose**: Entry point that initializes/resumes state, resolves active rules, classifies the request, and writes the approved execution plan.

The command should:
1. Accept a work description or ticket reference
2. Load or create `aidlc-docs/aidlc-state.md`
3. Append the raw user request to `aidlc-docs/audit.md`
4. Resolve rule-details, repo-local overrides, and enabled extensions
5. Detect greenfield vs brownfield workspace
6. If the request is ambiguous, generate a markdown question file in `aidlc-docs/inception/questions/` using `[Answer]:` tags
7. Write or update `aidlc-docs/inception/plans/execution-plan.md`
8. Route to `/aidlc_inception` only after the required questions/approvals are satisfied

Key behaviors:
- Do not rely on chat-only confirmations for required AI-DLC decisions
- Record stage decisions as `EXECUTE`/`SKIP` with rationale in `execution-plan.md`
- Record the current depth separately from stage decisions
- Resume safely from prior `aidlc-state.md` if the workflow already exists

Frontmatter:
```yaml
---
description: "AI-DLC compatibility entrypoint - initialize state, resolve rules, and write execution plan"
argument-hint: "[description or ticket path] - Describe the work to classify and initialize"
model: opus
---
```

#### 2. `/aidlc_inception` - Upstream-Compatible Inception Command
**File**: `commands/aidlc_inception.md` (new)
**Purpose**: Execute the upstream Inception phase stages that the execution plan marked `EXECUTE`.

The command should:
1. Read `aidlc-docs/aidlc-state.md` and `aidlc-docs/inception/plans/execution-plan.md`
2. Run or resume these stages as directed:
   - Workspace Detection
   - Reverse Engineering (when brownfield and artifacts are missing/stale)
   - Requirements Analysis
   - User Stories (when needed)
   - Workflow Planning (always-on)
   - Application Design (when needed)
   - Units Planning / Units Generation
3. Emit questions as markdown files with `[Answer]:` tags whenever clarification is required
4. Use `uow-decomposer` only after requirements/workflow/design artifacts are approved
5. Write canonical artifacts under `aidlc-docs/inception/...`

Depth behavior:
- `minimal`, `standard`, and `comprehensive` affect detail level within executed stages
- Depth must not be used as a substitute for `EXECUTE`/`SKIP`

Frontmatter:
```yaml
---
description: "AI-DLC Inception - execute approved inception stages and generate canonical artifacts"
argument-hint: "[description] [--type hotfix|feature|refactor|migration] [--depth minimal|standard|comprehensive]"
model: opus
---
```

#### 3. `/aidlc_bolt` - Construction Unit Command
**File**: `commands/aidlc_bolt.md` (new)
**Purpose**: Execute one construction unit through the per-unit construction loop.

The command should:
1. Accept a unit artifact path or unit ID
2. Read the unit definition from `aidlc-docs/inception/units/`
3. Execute the per-unit construction loop as needed:
   - Functional Design (optional)
   - NFR Requirements (optional)
   - NFR Design (optional)
   - Infrastructure Design (optional)
   - Code Planning
   - Code Generation / implementation
4. Update unit checkboxes and unit artifacts immediately in the same interaction
5. Support a bounded retry loop if a unit-level verification step fails
6. Write the unit execution record under `aidlc-docs/construction/units/[unit-id]/`

Important constraint:
- Completing `/aidlc_bolt` does not by itself complete Construction. Global completion requires `/aidlc_build_test`.

Frontmatter:
```yaml
---
description: "AI-DLC Bolt - execute one construction unit through the approved unit loop"
argument-hint: "[unit-path|unit-id] - Execute a specific construction unit"
model: opus
---
```

#### 4. `/aidlc_build_test` - Global Build and Test Command
**File**: `commands/aidlc_build_test.md` (new)
**Purpose**: Execute the always-on Build and Test stage after required units are complete.

The command should:
1. Read `aidlc-docs/aidlc-state.md` and the execution plan
2. Confirm all prerequisite units marked for construction are complete
3. Spawn `quality-gate-runner` to execute tests
4. Spawn `steering-rules-checker` to validate overall compliance based on the test outputs
5. Write `aidlc-docs/construction/build-and-test/build-and-test-report.md` incorporating the compliance summary
6. Update `aidlc-docs/aidlc-state.md` with Build and Test status
7. If checks fail, link back to the affected unit(s) for correction

Frontmatter:
```yaml
---
description: "AI-DLC Build and Test - execute the global construction validation stage"
argument-hint: "[optional scope] - Run global build and test after construction units"
model: opus
---
```

#### 5. `/aidlc_operations` - Experimental Operations Extension
**File**: `commands/aidlc_operations.md` (new)
**Purpose**: Experimental extension that generates deployment, monitoring, and rollback plans after core Construction is complete.

The command should:
1. Accept a build-and-test report path or infer the latest completed state
2. Read canonical inception/construction artifacts from `aidlc-docs/`
3. Spawn `operations-planner`
4. Spawn the compliance checker to validate extension/overlay expectations
5. Write experimental operations artifacts to `aidlc-docs/operations/`
6. Clearly label outputs as plugin extensions beyond the current upstream baseline

Depth behavior:
- Depth changes detail level only
- Unknown migration/infrastructure steps must be marked `MANUAL REVIEW REQUIRED`

Frontmatter:
```yaml
---
description: "AI-DLC Operations (Experimental) - generate deployment and rollback artifacts beyond upstream core"
argument-hint: "[build-test-report-path] - Generate experimental operations artifacts"
model: opus
---
```

#### 6. `/aidlc_feedback` - Experimental Feedback Extension
**File**: `commands/aidlc_feedback.md` (new)
**Purpose**: Experimental retrospective loop that complements AI-DLC but is not part of the current upstream core workflow.

The command should:
1. Accept an operations artifact path or infer the latest experimental operations run
2. Generate a markdown question file for observations when human input is required
3. Use `[Answer]:` tags instead of chat-only prompts for structured feedback capture
4. Spawn `feedback-collector`
5. Write retrospective artifacts to `aidlc-docs/operations/feedback-*.md`
6. Suggest overlay or extension changes, but never modify them directly

Frontmatter:
```yaml
---
description: "AI-DLC Feedback (Experimental) - collect retrospective observations as a plugin extension"
argument-hint: "[operations-path] - Capture structured retrospective feedback"
model: opus
---
```

### Success Criteria:

#### Automated Verification:
- [x] File exists: `commands/aidlc_start.md`
- [x] File exists: `commands/aidlc_inception.md`
- [x] File exists: `commands/aidlc_bolt.md`
- [x] File exists: `commands/aidlc_build_test.md`
- [x] File exists: `commands/aidlc_operations.md`
- [x] File exists: `commands/aidlc_feedback.md`
- [x] Each file has valid YAML frontmatter with `description` field
- [x] No existing command files were modified: `git diff commands/` shows only new files
- [x] Command-to-agent references are valid: `rg -n "subagent_type: (uow-decomposer|quality-gate-runner|operations-planner|feedback-collector|steering-rules-checker)" commands/aidlc_*.md`
- [x] Canonical artifact path references are present: `rg -n "aidlc-docs/(aidlc-state|audit|inception|construction|operations)" commands/aidlc_*.md`
- [x] Question artifacts use `[Answer]:` tags where clarification is required
- [x] `execution-plan.md` records `EXECUTE`/`SKIP` decisions separately from depth

#### Manual Verification:
- [ ] `/aidlc_start` initializes or resumes `aidlc-state.md` correctly
- [ ] `/aidlc_inception` produces canonical inception artifacts, not just a single plugin-local plan
- [ ] `/aidlc_bolt` updates unit artifacts immediately and stays scoped to one unit
- [ ] `/aidlc_build_test` acts as the required global construction gate
- [ ] `/aidlc_operations` is clearly labeled experimental and does not claim upstream-core parity
- [ ] `/aidlc_feedback` uses structured question files rather than chat-only collection
- [ ] The workflow is coherent: start → inception → bolt(s) → build_test → operations? → feedback?

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 5.

---

## Phase 5: Integration and Documentation

### Overview
Update README to document the AWS AI-DLC-compatible facade alongside the existing RPA workflow, and correct any legacy sections that would otherwise become stale once the new commands and canonical artifact directories exist.

### Changes Required:

#### 1. README Update
**File**: `README.md`
**Changes**:
- Add an AI-DLC compatibility section after existing RPA documentation
- Update existing enumerations that would otherwise become stale:
  - Commands Overview table
  - Verify Installation examples
  - Project Setup directory creation instructions
  - Any directory structure snippets that explicitly enumerate command or artifact directories
- Clarify that `aidlc-docs/` is canonical and `thoughts/shared/` is secondary for this workflow

Do not rewrite unrelated prose.

Add a new section:
```markdown
## AI-DLC Compatibility Layer

In addition to the core RPA workflow, this plugin includes an AWS AI-DLC-compatible
facade for teams that want plugin-native slash commands while keeping artifact
conventions close to the upstream AI-DLC workflow.

### Philosophy Difference

| Aspect | RPA (Legacy) | AI-DLC Facade |
|--------|-------------|--------------|
| Cycle | Linear: research → plan → implement → validate | AWS-compatible stage model with plugin-native commands |
| Canonical Artifacts | `thoughts/shared/*` | `aidlc-docs/*` |
| Adaptivity | Same depth for all work | Stage selection in execution plan + depth per executed stage |
| Operations | Not covered | Experimental extension beyond upstream core |
| Feedback | Not covered | Experimental extension beyond upstream core |

### Commands

| Command | Phase | Description |
|---------|-------|-------------|
| `/aidlc_start` | Entry | Initialize/resume state, resolve rules, write execution plan |
| `/aidlc_inception` | Inception | Execute approved inception stages and emit canonical artifacts |
| `/aidlc_bolt` | Construction | Execute one construction unit |
| `/aidlc_build_test` | Construction | Run the global Build and Test stage |
| `/aidlc_operations` | Operations (Experimental) | Generate deployment/rollback artifacts beyond upstream core |
| `/aidlc_feedback` | Feedback (Experimental) | Capture retrospective observations as a plugin extension |

### Quick Start

1. Configure the plugin overlay: `thoughts/shared/steering-rules/default.yaml`
2. Start: `/aidlc_start Add user authentication to the API`
3. Answer any generated question files in `aidlc-docs/inception/questions/`
4. Run inception: `/aidlc_inception`
5. Execute units: `/aidlc_bolt UOW-1`
6. Run global validation: `/aidlc_build_test`
7. Optionally run `/aidlc_operations` and `/aidlc_feedback` for experimental extensions

### Canonical Artifacts

Core AI-DLC-compatible artifacts are written under:
- `aidlc-docs/aidlc-state.md`
- `aidlc-docs/audit.md`
- `aidlc-docs/inception/...`
- `aidlc-docs/construction/...`
- `aidlc-docs/operations/...`

### Plugin Overlay

Edit `thoughts/shared/steering-rules/default.yaml` for plugin-local concerns:
- Change type heuristics
- Default commands
- Team conventions
- Experimental extension toggles

### Project Setup

If a repo will use AI-DLC artifacts, create the additional directories:

```bash
mkdir -p aidlc-docs/{inception,construction,operations}
mkdir -p thoughts/shared/steering-rules
```
```

### Success Criteria:

#### Automated Verification:
- [x] README.md contains an AI-DLC compatibility section
- [x] Commands Overview includes all new `aidlc_*` commands
- [x] Project Setup documents `aidlc-docs/` as canonical
- [x] Verify Installation includes at least one `aidlc_*` command example
- [x] README labels Operations/Feedback as experimental extensions

#### Manual Verification:
- [ ] Documentation accurately describes the compatibility-layer framing
- [ ] Quick Start guide is clear and followable
- [ ] Updated legacy sections remain accurate after the additive workflow is introduced
- [ ] README does not imply that chat-only Q&A is part of the core AI-DLC interaction model

**Implementation Note**: After completing this phase and all automated verification passes, pause here for final review.

---

## Error Handling & State Recovery

To ensure the closed-loop system is robust, the workflow must actively support failure recovery:

1. **Bolt Failure Recovery**:
   - If `/aidlc_bolt` fails a unit-level verification step, the error output should be automatically fed back into the implementation loop for an attempted fix (e.g., up to 3 retries).
   - If the bolt unrecoverably fails, its unit record is marked `failed`.
   - The system must support resuming: a developer can manually fix the code and rerun `/aidlc_bolt [unit]` to continue from the verification step.

2. **Inception Refinement**:
   - If `uow-decomposer` produces an inaccurate breakdown, `/aidlc_inception` must emit a file-based question/approval step before the final unit artifacts are accepted.

3. **Operations Planner Fallback**:
   - If the `operations-planner` lacks context to verify complex migrations, it should explicitly mark checks as `MANUAL REVIEW REQUIRED` in the resulting Markdown rather than fabricating unverified steps.

4. **Build and Test Recovery**:
   - If `/aidlc_build_test` fails, the failure must be written to `aidlc-docs/construction/build-and-test/build-and-test-report.md` and linked back to the impacted units before any claim that Construction is complete.

## Testing Strategy

### Static Verification (First Line of Defense)
Before manual smoke tests, run lightweight checks against the markdown assets:

1. Parse `thoughts/shared/steering-rules/default.yaml`
2. Validate command frontmatter is present in each `commands/aidlc_*.md`
3. Validate `aidlc-docs/aidlc-state.md` and `aidlc-docs/audit.md` are referenced where required
4. Grep for expected agent references, `aidlc-docs/` paths, and `[Answer]:` tags
5. Confirm README and project setup instructions mention the new workflow consistently

### Manual Testing (Primary):
Since these are prompt-based skills (markdown files interpreted by Claude Code), testing is manual:

1. **Steering rules loading**: Invoke `/aidlc_start` and verify it reads and parses the YAML
2. **Question-file flow**: Verify required clarifications are emitted as markdown files with `[Answer]:` tags
3. **Execution-plan flow**: Verify `execution-plan.md` marks stages `EXECUTE`/`SKIP` separately from depth
4. **Inception depth scaling**: Verify minimal/standard/comprehensive produce different artifact detail within executed stages
5. **Bolt execution**: Run a bolt on a simple unit and verify unit artifacts update immediately
6. **Build and Test**: Run `/aidlc_build_test` and verify canonical build/test artifacts are created
7. **Operations generation**: Verify operations artifacts are clearly labeled experimental
8. **Feedback capture**: Verify feedback links back to canonical artifacts and uses structured questions when needed
9. **Legacy compatibility**: Run `/create_plan` and `/implement_plan` to confirm they still work identically

### Smoke Test Sequence:
1. `/aidlc_start Add a simple utility function` → should classify as feature/standard
2. Answer any generated question files under `aidlc-docs/inception/questions/`
3. `/aidlc_inception` → should produce canonical inception artifacts and units
4. `/aidlc_bolt UOW-1` → should implement one unit and update unit artifacts
5. `/aidlc_build_test` → should produce `build-and-test-report.md`
6. `/aidlc_operations` → should produce experimental operations artifacts
7. `/aidlc_feedback` → should capture structured retrospective observations

## Performance Considerations

- Comprehensive inception is expensive because it may execute more upstream-compatible stages and generate more artifacts.
- `/aidlc_build_test` is the main command that runs Bash-heavy validation and may dominate runtime.
- The compatibility layer adds I/O overhead because it writes canonical state, audit, questions, and stage artifacts explicitly.

## Migration Notes

No migration of existing legacy RPA workflows or artifacts is needed. This is additive from a user-flow perspective:
- New command files and canonical `aidlc-docs/` artifact directories are introduced
- Existing README/project setup documentation must be updated to stay accurate
- Users opt-in by using `/aidlc_*` commands
- Legacy `/research_codebase`, `/create_plan`, `/implement_plan`, `/validate_plan` remain fully functional
- The compatibility layer is pinned to upstream AI-DLC `v0.1.6` until intentionally upgraded

## References

- AWS AI-DLC upstream README: https://raw.githubusercontent.com/awslabs/aidlc-workflows/main/README.md
- AWS AI-DLC core workflow: https://raw.githubusercontent.com/awslabs/aidlc-workflows/main/aidlc-rules/aws-aidlc-rules/core-workflow.md
- AWS AI-DLC question format guide: https://raw.githubusercontent.com/awslabs/aidlc-workflows/main/aidlc-rules/aws-aidlc-rule-details/common/question-format-guide.md
- AWS AI-DLC depth levels: https://raw.githubusercontent.com/awslabs/aidlc-workflows/main/aidlc-rules/aws-aidlc-rule-details/common/depth-levels.md
- AWS AI-DLC releases: https://github.com/awslabs/aidlc-workflows/releases
- Existing commands: `commands/*.md` (16 files)
- Existing agents: `agents/*.md` (27 files)
- Plugin config: `.claude-plugin/plugin.json`

## Enhancement History

### 2026-03-13 Enhancement
Based on critique and repo validation, this plan was improved with:
- Consistent artifact semantics for `minimal` workflows so hotfix flows no longer break the `operations -> feedback` chain
- Clear separation between quality-gate execution and compliance checking, with persisted evidence in bolt records
- Documentation scope corrections so README and project setup instructions do not become stale after implementation
- Removal of the contradictory requirement to keep all existing agents untouched while also updating a legacy agent

Changes made:
- Reworked the steering-rules defaults to require compact artifacts for minimal depth
- Strengthened Phase 4 command contracts and verification criteria
- Expanded Phase 5 to update stale README sections, not just append a new section
- Corrected migration notes to reflect the real documentation changes required

### 2026-03-13 Compatibility Revision
Based on AWS AI-DLC reference-model review, this plan was further improved with:
- Reframing from a parallel custom lifecycle to an AWS AI-DLC-compatible facade
- Canonical artifact strategy moved to `aidlc-docs/` with persistent `aidlc-state.md` and `audit.md`
- Stage selection separated from depth through `execution-plan.md`
- File-based question handling with `[Answer]:` tags added to the workflow contract
- `/aidlc_build_test` added to match the always-on global Build and Test stage
- `/aidlc_operations` and `/aidlc_feedback` explicitly labeled as experimental extensions beyond upstream core

Changes made:
- Added a new Phase 0 compatibility substrate
- Demoted the YAML steering file to a plugin overlay and switched `enhanced` to `comprehensive`
- Rewrote the artifact directory and command phases around canonical `aidlc-docs/` paths
- Updated testing, migration, and documentation sections to reflect upstream-compatible behavior
