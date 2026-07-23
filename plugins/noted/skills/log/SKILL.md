---
name: log
description: Use when explicitly asked to journal or log the conversation (e.g. /log) — capture an immutable, timestamped entry via the noted MCP LogNote tool.
---

# log

Journal about the current conversation using the noted MCP `LogNote` tool.
Invoke this only when explicitly asked (e.g. `/log <focus>`); never start it on
your own.

`mcp__noted__LogNote` writes an immutable, timestamped entry — its metadata is
auto-generated and it cannot be edited or deleted afterward. Write the log to
stand on its own: enough context that a future reader understands what happened
without the surrounding conversation.

If a focus is given, center the entry on it; otherwise summarize the salient
decisions, changes, and open threads from the conversation.
