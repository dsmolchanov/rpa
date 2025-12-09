---
description: Enhance existing implementation plans by synthesizing user feedback and opinions
model: opus
---

# Enhance Implementation Plan

You are tasked with enhancing an existing implementation plan by incorporating user feedback, critiques, and suggested improvements. Your job is to synthesize the best insights from multiple opinions and produce an improved version of the plan.

## Initial Response

When this command is invoked:

1. **Parse the input to identify**:
   - Plan document path (e.g., `thoughts/shared/plans/2025-01-08-feature-implementation.md`)
   - User opinions/feedback/critiques to incorporate

2. **Handle different input scenarios**:

   **If NO document path provided**:
   ```
   I'll help you enhance an existing implementation plan with your feedback and opinions.

   Please provide:
   1. The path to the plan document (e.g., `thoughts/shared/plans/2025-01-08-feature-implementation.md`)
   2. Your opinions, critiques, or suggested enhancements

   Tip: You can list recent plans with `ls -lt thoughts/shared/plans/ | head`
   ```
   Wait for user input.

   **If document path provided but NO opinions**:
   ```
   I've found the implementation plan at [path]. Please share your opinions, critiques, or suggested enhancements.

   For example:
   - "Phase 2 should come before Phase 1 for better dependency ordering"
   - "Add error handling considerations to each phase"
   - "The success criteria are too vague - make them more specific"
   - "Consider these alternative approaches: [your thoughts]"
   - "Merge insights from these perspectives: [opinion 1], [opinion 2]"
   ```
   Wait for user input.

   **If BOTH document path AND opinions provided**:
   - Proceed immediately to Step 1
   - No preliminary questions needed

## Process Steps

### Step 1: Read and Understand Current Plan

1. **Read the existing plan document COMPLETELY**:
   - Use the Read tool WITHOUT limit/offset parameters
   - Understand the current phases, scope, and approach
   - Note the success criteria (both automated and manual)
   - Identify the implementation strategy and constraints
   - Note file:line references and code patterns mentioned

2. **Parse all user opinions**:
   - Extract key critiques and concerns
   - Identify suggested additions or modifications
   - Note alternative approaches or architectures
   - Find common themes across multiple opinions
   - Identify concerns about feasibility vs. style preferences

### Step 2: Analyze and Synthesize Opinions

1. **Categorize the feedback**:
   - **Technical corrections**: Implementation errors or better approaches
   - **Missing phases**: Work that should be included but wasn't
   - **Scope adjustments**: Things to add or remove from scope
   - **Ordering improvements**: Better sequencing of phases
   - **Success criteria refinements**: More specific or complete verification steps
   - **Risk mitigation**: Edge cases or failure modes not addressed
   - **Alternative approaches**: Different ways to solve the problem

2. **Identify research needs**:
   - Does incorporating the feedback require additional codebase research?
   - Are there technical claims that need verification?
   - Do alternative approaches need feasibility validation?

### Step 3: Research If Needed

**Only spawn research tasks if the opinions require verification or new investigation.**

If the feedback references code patterns or approaches not covered in the original plan:

1. **Create a research todo list** using TodoWrite

2. **Spawn parallel sub-tasks for research**:
   Use the right agent for each type of research:

   **For code investigation:**
   - **codebase-locator** - To find files relevant to suggested changes
   - **codebase-analyzer** - To understand feasibility of alternative approaches
   - **codebase-pattern-finder** - To find existing patterns that support or contradict suggestions

   **For historical context:**
   - **thoughts-locator** - To find related research or past decisions
   - **thoughts-analyzer** - To extract insights from previous implementations

3. **Wait for ALL sub-tasks to complete** before proceeding

4. **Read any new files identified by research** FULLY into main context

### Step 4: Present Synthesis Plan

Before making changes, present your synthesis approach:

```
Based on your feedback, I've identified:

**Technical Improvements:**
- [Improvement 1 - what changes and why]
- [Improvement 2]

**Scope Adjustments:**
- [Add: Item to add - based on [which opinion]]
- [Remove: Item to remove - based on [which opinion]]

**Phase Restructuring:**
- [Change 1 - e.g., "Move Phase 2 before Phase 1"]
- [Change 2]

**Success Criteria Refinements:**
- [Refinement 1]
- [Refinement 2]

**My research confirmed:**
- [Verified finding 1]
- [Verified finding 2]

**Feedback I'm NOT incorporating (and why):**
- [Rejected suggestion - reason it doesn't apply]

I plan to enhance the plan by:
1. [Specific change]
2. [Specific change]
3. [Specific change]

Does this synthesis capture the best from your feedback?
```

Get user confirmation before proceeding.

### Step 5: Update the Plan Document

1. **Make focused, precise edits** to the existing document:
   - Use the Edit tool for surgical changes
   - Maintain the existing structure unless feedback specifically addresses it
   - Keep all file:line references accurate
   - Add new references for newly discovered code patterns

2. **Update relevant sections**:
   - **Overview**: If scope changed significantly
   - **Current State Analysis**: If new discoveries were made
   - **What We're NOT Doing**: If scope was adjusted
   - **Implementation Approach**: If strategy changed
   - **Phases**: Add, remove, reorder, or modify as needed
   - **Success Criteria**: Ensure both automated and manual criteria are specific
   - **Testing Strategy**: Update if new edge cases identified

3. **Add an Enhancement section** at the end:
   ```markdown
   ## Enhancement History

   ### YYYY-MM-DD Enhancement
   Based on feedback, this plan was improved with:
   - [Key improvement 1 - sourced from feedback]
   - [Key improvement 2 - discovered during verification]

   Changes made:
   - [Specific change 1]
   - [Specific change 2]
   ```

4. **Preserve quality standards**:
   - Include specific file paths and line numbers
   - Write measurable success criteria
   - Maintain clear distinction between automated vs manual verification
   - Keep language actionable and clear
   - Ensure no open questions remain

### Step 6: Review

1. **Present the changes made**:
   ```
   I've enhanced the implementation plan at `[path]`

   Key improvements made:
   - [Improvement 1 - sourced from [which feedback]]
   - [Improvement 2 - sourced from [which feedback]]
   - [Improvement 3 - discovered during verification research]

   The enhanced plan now:
   - [Key benefit 1]
   - [Key benefit 2]

   Would you like any further adjustments?
   ```

2. **Be ready to iterate further** based on feedback

## Important Guidelines

1. **Synthesize, Don't Just Append**:
   - Don't simply add all opinions verbatim
   - Find the best insights from each perspective
   - Resolve contradictions between opinions intelligently
   - Create a coherent, unified plan

2. **Verify Before Incorporating**:
   - Don't blindly accept feedback that contradicts the codebase
   - Research claims about code patterns or feasibility
   - Validate alternative approaches are actually viable
   - Point out when an opinion is incorrect (respectfully)

3. **Maintain Plan Quality**:
   - Ensure all phases have clear success criteria
   - Keep automated vs manual verification distinct
   - Preserve working file:line references
   - Add new references for new content
   - No open questions in the final plan

4. **Be Transparent About Sources**:
   - Note which changes came from which feedback
   - Explain why certain suggestions were not incorporated
   - Credit good insights to the feedback that suggested them

5. **Be Skeptical But Open**:
   - Question suggestions that seem to add complexity
   - But also recognize when complexity is necessary
   - Don't dismiss alternative approaches without investigation
   - Be willing to make significant changes if justified

6. **Track Progress**:
   - Use TodoWrite for complex enhancements
   - Update todos as you complete research
   - Mark tasks complete when done

## Success Criteria Guidelines

When updating success criteria based on feedback, maintain the two-category structure:

1. **Automated Verification** (can be run by execution agents):
   - Commands that can be run: `make test`, `npm run lint`, etc.
   - Specific files that should exist
   - Code compilation/type checking
   - Automated test suites

2. **Manual Verification** (requires human testing):
   - UI/UX functionality
   - Performance under real conditions
   - Edge cases that are hard to automate
   - User acceptance criteria

## Example Interaction Flows

**Scenario 1: User provides everything upfront**
```
User: /enhance_plan thoughts/shared/plans/2025-01-08-auth-feature.md
Opinion 1: "Phase 1 should handle the database migration before the API changes"
Opinion 2: "Add rollback procedures for each phase"
Opinion 3: "The success criteria for Phase 2 are too vague - needs specific test commands"
Opinion 4: "Consider using the existing AuthService pattern instead of creating a new one"