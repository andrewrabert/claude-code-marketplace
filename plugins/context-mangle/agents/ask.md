---
name: ask
description: Answers each question with no context carried from earlier turns. Start a session with it as `claude --agent context-mangle:ask`; each request carries only this system prompt, the current question and the reply tool.
tools: SendUserMessage
omitClaudeMd: true
---

<!-- The plugin's proxy sends only the text between the tags below as the
system prompt, and each request carries only the current turn. -->
<context-mangle:ask>
Answer the user's question. Each question reaches you alone.
</context-mangle:ask>
