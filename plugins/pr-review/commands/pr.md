---
description: Invoke the pr-review agent
argument-hint: prompt
---

First prepare the review:

- For a pull request, call the pr-review `prepare_github_review` tool with its host, org, repo, and number.
- For two revisions of a local git repo, call the pr-review `prepare_local_review` tool with the git dir and the base and head revisions.

Then invoke the pr-review agent with only the printed token.

$ARGUMENTS

Reply only with the agent's response, verbatim.
