# Core Workflow

This compatibility layer follows the upstream AI-DLC stage model at a high level:

1. Entry / initialization
2. Inception
3. Construction (per-unit loop)
4. Build and Test
5. Operations (experimental plugin extension)
6. Feedback (experimental plugin extension)

## Inception

The execution plan may mark these stages `EXECUTE` or `SKIP`:

- Workspace Detection
- Reverse Engineering
- Requirements Analysis
- User Stories
- Workflow Planning
- Application Design
- Units Planning / Units Generation

Stage selection is recorded in `aidlc-docs/inception/plans/execution-plan.md`.

## Construction

Construction runs per approved unit and may include:

- Functional Design
- NFR Requirements
- NFR Design
- Infrastructure Design
- Code Planning
- Code Generation / implementation

Global Construction completion requires a separate Build and Test stage.
