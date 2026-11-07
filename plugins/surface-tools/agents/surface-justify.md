---
name: surface-justify
description: Writes a justification of at most 15 words for every node of a surface-spec capture, saying why each surface exists, parents before children. The prompt must be exactly a JSON object {"capture": "<absolute path of a surface-spec --json capture>"}. Any other prompt, a capture another surface-justify agent is justifying, or a capture with no node left to justify is refused before the agent starts. Its answer is an ERROR line unless every node is justified.
tools: mcp__surface-tools__justify
omitClaudeMd: true
---

<!-- surface-tools' proxy cuts this agent's system prompt and every earlier
turn; each request carries one prompt, built in hooks/register.ts. -->
