---
name: auto-plan
description: Use when user wants autonomous planning - spawns subagent for planning, optionally brainstorms first if primary agent decides context is insufficient
---

# Auto Plan

Spawn a subagent to create an implementation plan. You (the primary agent) answer all questions the subagent asks.

## Process

1. **Decide if brainstorming needed:** Based on your conversation context, determine if requirements are clear enough to plan directly or if `andrewrabert-personal:auto-brainstorm` should run first.

2. Spawn subagent with Task tool:
   - subagent_type: `general-purpose`
   - prompt: Include user's prompt (and brainstorm results if applicable), instruct to use `superpowers:writing-plans`

3. When subagent asks questions via AskUserQuestion, YOU answer them

4. Return plan to user

## Example Prompt for Subagent

```
Use superpowers:writing-plans to create an implementation plan for:

<user-request>
{USER_PROMPT_HERE}
</user-request>

<context>
{ANY BRAINSTORM RESULTS OR CONVERSATION CONTEXT}
</context>

Ask clarifying questions as needed - they will be answered.
```
