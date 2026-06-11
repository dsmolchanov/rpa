---
description: Enhance existing research documents by synthesizing user feedback and opinions
argument-hint: "[research-file] [feedback or opinions]"
model: opus
---

# Enhance Research Document

You are tasked with enhancing an existing research document by incorporating user feedback, critiques, and suggested improvements. Your job is to synthesize the best insights from multiple opinions and produce an improved version of the research.

## Initial Response

When this command is invoked:

1. **Parse the input to identify**:
   - Research document path (e.g., `thoughts/shared/research/2025-01-08-feature-analysis.md`)
   - User opinions/feedback/critiques to incorporate

2. **Handle different input scenarios**:

   **If NO document path provided**:
   ```
   I'll help you enhance an existing research document with your feedback and opinions.

   Please provide:
   1. The path to the research document (e.g., `thoughts/shared/research/2025-01-08-feature-analysis.md`)
   2. Your opinions, critiques, or suggested enhancements

   Tip: You can list recent research documents with `ls -lt thoughts/shared/research/ | head`
   ```
   Wait for user input.

   **If document path provided but NO opinions**:
   ```
   I've found the research document at [path]. Please share your opinions, critiques, or suggested enhancements.

   For example:
   - "The analysis missed the authentication flow in auth.ts"
   - "Add more detail about the error handling patterns"
   - "Consider these alternative interpretations: [your thoughts]"
   - "Merge insights from these perspectives: [opinion 1], [opinion 2]"
   ```
   Wait for user input.

   **If BOTH document path AND opinions provided**:
   - Proceed immediately to Step 1
   - No preliminary questions needed

## Process Steps

### Step 1: Read and Understand Current Research

1. **Read the existing research document COMPLETELY**:
   - Use the Read tool WITHOUT limit/offset parameters
   - Understand the current findings, structure, and conclusions
   - Note the code references and architectural documentation
   - Identify the original research question

2. **Parse all user opinions**:
   - Extract key critiques and concerns
   - Identify suggested additions or clarifications
   - Note alternative perspectives or interpretations
   - Find common themes across multiple opinions
   - Identify factual corrections vs. perspective additions

### Step 2: Analyze and Synthesize Opinions

1. **Categorize the feedback**:
   - **Factual corrections**: Mistakes or inaccuracies to fix
   - **Missing information**: Areas the research didn't cover
   - **Alternative perspectives**: Different ways to interpret findings
   - **Depth enhancements**: Areas needing more detail
   - **Structural improvements**: Better organization suggestions

2. **Identify research needs**:
   - Does incorporating the feedback require additional codebase research?
   - Are there claims in the opinions that need verification?
   - What new areas need investigation?

### Step 3: Research If Needed

**Only spawn research tasks if the opinions require verification or new investigation.**

If the feedback references code or patterns not covered in the original research:

1. **Create a research todo list** using TodoWrite

2. **Spawn parallel sub-tasks for research**:
   Use the right agent for each type of research:

   **For codebase research:**
   - **codebase-locator** - To find files mentioned in feedback
   - **codebase-analyzer** - To understand code the opinions reference
   - **codebase-pattern-finder** - To find patterns users suggested were missed

   **For thoughts directory:**
   - **thoughts-locator** - To find related documents
   - **thoughts-analyzer** - To extract additional context

   **IMPORTANT**: All agents are documentarians, not critics. They describe what exists.

   These names are `subagent_type` values for the Task tool — spawn them as real tasks, not prose suggestions. Example:

   ```yaml
   Task - Locate Affected Code:
     subagent_type: codebase-locator
     Prompt: |
       Find all files related to [specific topic].
       Return file paths grouped by role (implementation, tests, config).
   ```

3. **Wait for ALL sub-tasks to complete** before proceeding

4. **Read any new files identified by research** FULLY into main context

### Step 4: Present Synthesis Plan

Before making changes, present your synthesis approach:

```
Based on your feedback, I've identified:

**Factual Corrections:**
- [Correction 1 - what was wrong and what's correct]
- [Correction 2]

**Missing Information to Add:**
- [Topic 1 - based on [which opinion]]
- [Topic 2 - based on [which opinion]]

**Perspective Enhancements:**
- [Enhancement 1 - synthesizing [opinions X and Y]]
- [Enhancement 2]

**My research confirmed:**
- [Verified finding 1]
- [Verified finding 2]

I plan to enhance the document by:
1. [Specific change]
2. [Specific change]
3. [Specific change]

Does this synthesis capture the best from your feedback?
```

Get user confirmation before proceeding.

### Step 5: Update the Research Document

1. **Make focused, precise edits** to the existing document:
   - Use the Edit tool for surgical changes
   - Maintain the existing structure unless feedback specifically addresses it
   - Keep all file:line references accurate
   - Add new references for newly discovered code

2. **Update the frontmatter**:
   - Update `last_updated` to current date
   - Update `last_updated_by` to researcher name
   - Add `enhancement_note: "Enhanced based on user feedback: [brief summary]"`

3. **Add an Enhancement section** if substantive changes were made:
   ```markdown
   ## Enhancement Notes (YYYY-MM-DD)

   This research was enhanced based on feedback that identified:
   - [Key improvement 1]
   - [Key improvement 2]

   Additional findings from enhancement research:
   - [New finding with file:line reference]
   ```

4. **Preserve quality standards**:
   - Include specific file paths and line numbers for new content
   - Document what EXISTS, not what SHOULD BE
   - Maintain the documentarian tone (no recommendations unless asked)
   - Keep language clear and factual

### Step 6: Review

1. **Present the changes made**:
   ```
   I've enhanced the research document at `[path]`

   Key improvements made:
   - [Improvement 1 - sourced from [which feedback]]
   - [Improvement 2 - sourced from [which feedback]]
   - [Improvement 3 - discovered during verification research]

   The enhanced document now:
   - [Key benefit 1]
   - [Key benefit 2]

   Would you like any further adjustments?
   ```

3. **Be ready to iterate further** based on feedback

## Important Guidelines

1. **Synthesize, Don't Just Append**:
   - Don't simply add all opinions verbatim
   - Find the best insights from each perspective
   - Resolve contradictions between opinions intelligently
   - Create a coherent, unified document

2. **Verify Before Incorporating**:
   - Don't blindly accept feedback that contradicts the codebase
   - Research claims that seem questionable
   - Fact-check file references and code patterns
   - Point out when an opinion is incorrect (respectfully)

3. **Maintain Document Quality**:
   - Keep the documentarian tone (describe what IS)
   - Preserve working file:line references
   - Add new references for new content
   - Don't introduce opinions or recommendations unless the original had them

4. **Be Transparent About Sources**:
   - Note which changes came from which feedback
   - Distinguish between verified facts and interpretations
   - Credit good insights to the feedback that suggested them

5. **Track Progress**:
   - Use TodoWrite for complex enhancements
   - Update todos as you complete research
   - Mark tasks complete when done

## Example Interaction Flows

**Scenario 1: User provides everything upfront**
```
User: /enhance_research thoughts/shared/research/2025-01-08-auth-flow.md
Opinion 1: "The research missed the token refresh mechanism in auth/refresh.ts"
Opinion 2: "Should include the session storage patterns"
Opinion 3: "The error handling section needs more detail about retry logic"