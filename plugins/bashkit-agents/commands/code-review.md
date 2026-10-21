---
description: Invoke the code-review agent
argument-hint: prompt
---

Invoke the code-review agent with the review to do: for a pull request, its host, org, repo, and number; for two revisions of a local git dir, the git dir and the base and head revisions.

$ARGUMENTS

The agent responds with a token. Call the code-review `read_review` tool with it, then reply only with its output, verbatim.
