---
name: chat
description: Answers each question with every earlier turn carried. Start a session with it as `claude --agent context-mangle:chat`; each request carries only this system prompt, the session's turns and the reply tool.
tools: SendUserMessage
omitClaudeMd: true
---

<!-- The plugin's proxy applies the settings field below to each request:
see scripts/proxy.py. -->
<context-mangle>
{
  "system_prompt": "Answer the user's question.",
  "no_reminders": true
}
</context-mangle>
