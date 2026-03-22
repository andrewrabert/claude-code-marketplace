---
name: done
description: Run code simplifier and code reviewer agents in parallel on changed code
---

# Review

Launch the code-simplifier and code-reviewer agents in parallel using the Agent tool.

1. **code-simplifier agent** (`code-simplifier:code-simplifier`): Simplify and refine changed code for clarity, consistency, and maintainability.

2. **code-reviewer agent** (`feature-dev:code-reviewer`): Review changed code for bugs, security vulnerabilities, and adherence to project conventions.

Both agents should focus on recently changed code (unstaged and staged changes via `git diff`). Launch them simultaneously - they are independent.

After both complete, summarize findings to the user.
