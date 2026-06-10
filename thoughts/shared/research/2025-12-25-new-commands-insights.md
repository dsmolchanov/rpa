---
date: 2025-12-25 15:54:35 EST
researcher: Antigravity
git_commit: d8ad788105bcee1d1c8bf3cae78d24253c7a048f
branch: master
repository: rpa
topic: "Insights for New Commands and Subagents"
tags: [research, rpa, commands, agents, workflows]
status: complete
last_updated: 2025-12-25
last_updated_by: Antigravity
---

# Research: Insights for New Commands and Subagents

**Date**: 2025-12-25 15:54:35 EST
**Researcher**: Antigravity
**Git Commit**: d8ad788105bcee1d1c8bf3cae78d24253c7a048f
**Branch**: master
**Repository**: rpa

## Research Question
Analyze the existing codebase to provide additional insights for creating new commands and subagents.

## Summary
The RPA (Research, Plan, Act) system uses a directory-based architecture where "Commands" are Markdown-defined workflows and "Agents" are Markdown-defined personas/system prompts. Creating new capabilities involves adding files to `.agent/workflows/` (for commands) or `.agent/workflows/agents/` (for specialized sub-agents).

## Detailed Findings

### 1. Anatomy of a Command (Workflow)
Commands are stored in `.agent/workflows/*.md`. They function as interactive scripts for the agent to follow.

**Key Components:**
*   **Frontmatter**: Defines metadata. `description` is critical as it appears in the help menu.
    ```yaml
    ---
    description: Document codebase as-is with thoughts directory for historical context
    model: opus
    ---
    ```
*   **Trigger Definition**: "When this command is invoked..." section.
*   **Step-by-Step Logic**: Numbered lists defining the process.
    *   *Insight*: Commands often enforce a specific order of operations (e.g., "Step 1: Read files", "Step 2: Spawn sub-tasks").
*   **Sub-task Orchestration**: Instructions to "Spawn parallel sub-tasks" using specific named agents.
    *   *Reference*: `research_codebase.md:43` "Spawn parallel sub-agent tasks for comprehensive research"

### 2. Anatomy of an Agent (Persona)
Agents are stored in `.agent/workflows/agents/*.md`. These are NOT autonomous binaries but **specialized personas** that the main agent adopts or "spawns" (conceptually).

**Key Components:**
*   **Identity**: "You are a specialist at...".
*   **Core Responsibilities**: What this specific mode/persona is allowed to do.
*   **Strict Constraints**: "What NOT to do" (e.g., "Do NOT critique code").
*   **Structured Output**: A template section showing exactly how the result should look.
    *   *Reference*: `agents/codebase-locator.md:68` defines the exact "File Locations" output format.

### 3. Directory Structure
*   `commands/` (Mapped to `.agent/workflows/`): User-facing entry points (slash commands).
*   `agents/` (Mapped to `.agent/workflows/agents/`): Specialized personas called by commands.
*   `scripts/` (Mapped to `.agent/workflows/scripts/`): Bash helper scripts for deterministic tasks (like metadata generation).

### 4. Integration Logic
*   **Commands call Agents**: A command file like `research_codebase.md` acts as a "Controller". It delegates work to "Agents" by name.
*   **Scripts for Standardization**: `spec_metadata.sh` is used to generate standard headers for artifacts, ensuring all docs have git context.

## Insights for Creating New Commands

1.  **Follow the Controller-Worker Pattern**:
    *   Don't write one massive prompt.
    *   Create a **Command** file that acts as the Controller (handles user interaction, planning, and synthesis).
    *   Create **Agent** files for specific heavy-lifting (e.g., "Database Analyzer", "Test Runner").

2.  **Enforce Read-Only Phases**:
    *   Existing commands strictly separate "Reading/Researching" from "Planning" or "Acting".
    *   New commands should follow this `Read -> Plan -> Execute` loop to avoid hallucinations.

3.  **Use Templates for Output**:
    *   Define the exact Markdown structure you want the agent to output. This makes the output machine-readable by other agents/steps.

4.  **Leverage the Metadata Script**:
    *   Any command that generates a file (research doc, plan, etc.) *must* call `.agent/workflows/scripts/spec_metadata.sh` to get accurate timestamp/git info.

## Code References
- `.agent/workflows/research_codebase.md` - Example of a complex "Controller" command.
- `.agent/workflows/agents/codebase-locator.md` - Example of a specialized "Worker" agent.
- `.agent/workflows/scripts/spec_metadata.sh` - Standard metadata generation script.

## Open Questions
- **Sub-agent Execution in Antigravity**: The original RPA repo assumes a specific `spawn_agent` capability. In Antigravity, we currently emulate this by the main agent adopting the persona or using `browser_subagent`. For fully parallel execution, we might need a specific `run_agent` tool or just continue with sequential mode emulation.
