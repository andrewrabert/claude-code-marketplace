---
name: auto-brainstorm
description: Use when user wants autonomous brainstorming - spawns subagent that uses superpowers:brainstorming while primary agent answers all questions
---

# Auto Brainstorm

Spawn a subagent to brainstorm the user's prompt. You (the primary agent) answer all questions the subagent asks.

## Process

1. Spawn subagent with Task tool:
   - subagent_type: `general-purpose`
   - prompt: Include user's prompt, instruct to use `superpowers:brainstorming`

2. When subagent asks questions via AskUserQuestion, YOU answer them based on:
   - Context from the conversation
   - Your understanding of the user's intent
   - Reasonable assumptions

3. Return brainstorming results to user

## Example Prompt for Subagent

```
Use superpowers:brainstorming to explore this request:

<user-request>
{USER_PROMPT_HERE}
</user-request>

Ask clarifying questions as needed - they will be answered.
```
