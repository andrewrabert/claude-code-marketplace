---
description: Analyze one Claude Code session into a findings note (bugs, friction, learnings)
argument-hint: "[session-id] (omit → current session)"
allowed-tools: Bash, Task
---

Analyze one session with the `session-findings` plugin.

Resolve the argument to a **concrete session id**, then spawn the bundled
`classify-session` subagent (`Task`) with that id and nothing else — it owns the
rest of the pipeline (locate → digest → classify → stamp time → write notes),
keeping the multi-KB digest and its reasoning out of this conversation.

Resolve the id here, at the boundary — the agent must never guess which session:

- `$ARGUMENTS` given → it is the concrete session id; pass it through.
- Empty → the current session. You are the live session, so its transcript is
  the newest-mtime `*.jsonl` under this cwd's encoded project dir. Encode cwd by
  replacing every `/` and `.` with `-`:
  `DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(pwd | sed 's/[/.]/-/g')"`,
  then the id is `basename "$(ls -t "$DIR"/*.jsonl | head -1)" .jsonl`.

Then relay the agent's compact summary (counts + notable bugs/learnings) to the
user.
