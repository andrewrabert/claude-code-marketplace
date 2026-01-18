---
name: auto-implement
description: Use when user wants autonomous implementation - invokes auto-plan if no plan specified, then uses subagent-driven-development for execution
---

# Auto Implement

Autonomous implementation using subagent-driven-development. You (the primary agent) answer all subagent questions.

## Process

1. **Check for existing plan:** If user hasn't specified a plan, invoke `andrewrabert-personal:auto-plan` first.

2. **Execute:** Use `superpowers:subagent-driven-development` to implement the plan.

3. When any subagent asks questions, YOU answer them based on:
   - Context from the conversation
   - Your understanding of the user's intent
   - Reasonable assumptions

4. Return results to user
