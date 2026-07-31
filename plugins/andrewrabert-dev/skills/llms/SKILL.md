---
name: llms
description: Use any time llms.txt or "llms" is referenced, or when working with a project that publishes one (pydantic, pydantic-settings, "Model Context Protocol specification", "mcp specification") — fetch that project's canonical remote llms.txt as the source of truth for current docs. Covers what llms.txt is (an index of pages to fetch) and how to follow it.
---

# llms.txt

`llms.txt` is a plain-text or Markdown, LLM-oriented file published by a
project at a canonical URL. Treat it as the authoritative, current source for
that project's docs.

## Registry

- [pydantic, pydantic-settings](https://pydantic.dev/docs/validation/latest/llms.txt)
- ["Model Context Protocol specification", "mcp specification"](https://modelcontextprotocol.io/llms.txt)

For anything else, projects typically serve it from `/llms.txt`. This may be
the full documentation or an index to other URLs or paths. When it's an index,
some projects also serve a `llms-full.txt` containing the full documentation.
