---
name: mangle
description: Call the mangle tool with the target, pattern and replacement given as arguments
argument-hint: <messages|system> <pattern> <replacement>
disable-model-invocation: true
---

Call the `mcp__context-mangle__mangle` tool once with the three arguments below,
split as a POSIX shell splits words: the first is `target`, the second is
`pattern`, and the third is `replacement`. A quoted argument is one word, and
`''` or `""` is an empty one. Pass each value exactly, with no change.

Arguments: $ARGUMENTS

If there are not exactly three arguments, or the target is not `messages` or
`system`, do not call the tool. Reply with
`usage: /mangle <messages|system> <pattern> <replacement>`.

After the call, reply only with the tool's result.
