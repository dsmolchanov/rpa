# AI-DLC inception artifacts — contract

The execution plan is authoritative: create a listed artifact only when its
stage is `EXECUTE`. Existing valid artifacts for `SKIP` stages are preserved but
not treated as outputs of the current request.

## Canonical paths and minimum content

### Workspace Detection

Recorded in `aidlc-docs/aidlc-state.md`:

- current request identifier/summary;
- workspace type (`greenfield` or `brownfield`);
- current depth and enabled extensions;
- current stage and artifact pointers.

### Reverse Engineering

`aidlc-docs/inception/reverse-engineering/system-map.md`

- workspace scope and evidence baseline;
- components, responsibilities, and boundaries;
- data/control flow and external integrations;
- constraints, conventions, and known unknowns;
- brownfield `file:line` evidence for every verifiable claim.

### Requirements Analysis

`aidlc-docs/inception/requirements/requirements.md`

- objective and scope exclusions;
- functional requirements with stable `REQ-*` IDs;
- non-functional requirements and constraints with measurable outcomes;
- compatibility, migration, security/privacy, and operational requirements when
  applicable;
- acceptance criteria and resolved decision references;
- traceability to the source request and relevant system-map evidence.

### User Stories

`aidlc-docs/inception/user-stories/user-stories.md`

- stable `US-*` IDs;
- actor, outcome, and value;
- acceptance scenarios including material failure/permission paths;
- mapped `REQ-*` IDs and explicit exclusions/dependencies.

### Workflow Planning

The durable workflow plan remains
`aidlc-docs/inception/plans/execution-plan.md`. Inception may add artifact
pointers or completion evidence without changing approved `EXECUTE`/`SKIP`,
depth, rationale, or approval decisions. A stage-selection change belongs to
`/aidlc_start`.

### Application Design

`aidlc-docs/inception/application-design/application-design.md`

- selected design and constraints;
- components/interfaces and ownership boundaries;
- data model and data/control flows where applicable;
- failure behavior, security/privacy, reliability, observability, and migration
  design where required;
- alternatives and durable decisions;
- traceability to `REQ-*`, `US-*`, and brownfield evidence.

### Units Planning / Generation

Three synchronized artifacts:

- `aidlc-docs/inception/units/unit-of-work.md`
  - stable `UOW-*` IDs, outcome, in/out of scope, affected surfaces,
    requirements/stories, acceptance/verification, and dependencies.
- `aidlc-docs/inception/units/unit-of-work-dependency.md`
  - every `UOW-*`, predecessor/successor relationships, rationale, parallel-safe
    groups, and cycle/blocker detection.
- `aidlc-docs/inception/units/unit-of-work-story-map.md`
  - each `REQ-*` and executed `US-*` mapped to one or more `UOW-*`, with an
    explicit reason for any intentionally deferred item.

Unit artifacts are generated only after all executed prerequisite artifacts
required by the pinned workflow are valid and approved.

## Question and approval files

The only question-file template is the pinned
`.aidlc-rule-details/common/question-format-guide.md`. Store inception questions
under `aidlc-docs/inception/questions/`; do not copy the template into this
contract. A required answer is pending when its `[Answer]:` field has no
non-whitespace response. Preserve answered files as durable decision evidence.

## State transition rules

- Update state only after the corresponding artifact passes its contract.
- A pending question records the affected stage and question-file pointer; it
  does not mark the stage complete.
- Resume revalidates artifacts before trusting completion labels.
- Inception approval is `yes` only after every `EXECUTE` stage is valid and
  approved and every `SKIP` remains explicit.
- Artifact prose may vary with depth, but IDs, traceability, decisions,
  evidence, and acceptance criteria never disappear at lower depth.
