---
name: run
description: Answers a sequence of prompts one at a time with context not persisted across turns. Appends each answer to a results file as a JSON line {"prompt", "response"}. The prompt must be exactly a JSON object {"system_prompt": "<text>", "results_file": "<absolute path>", "prompts": ["<text>", ...]}, or the same with "prompt_script": "<absolute path>" in place of "prompts". A prompt script is run with the results file as its only argument before each prompt; it prints the next prompt and exits 0, or exits non-zero when there are no more.
tools: mcp__context-mangle__respond
omitClaudeMd: true
---

<!-- The plugin's proxy replaces this system prompt with the spawn's
system_prompt, and each request carries only the current prompt. -->
