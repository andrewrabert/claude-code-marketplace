---
name: declaration-manifest
description: Declaration manifest formats. Load before you write a declaration manifest. It contains the per-surface manifest specs (CLI, HTTP, MCP, Python, Rust).
---

# Declaration Manifest

Rules:

- A declaration manifest is a specification of all declaration additions & removals for a code change.
- It describes the complete, exact declaration surface a code change must have.
- The combined diff adds exactly the declarations under `Additions`.
- The combined diff deletes exactly the declarations under `Deletions`.
- When the combined diff adds no declarations, the `Additions` section states
  this explicitly: its only content is the phrase `No additions.`
- When the combined diff deletes no declarations, the `Deletions` section
  states this explicitly: its only content is the phrase `No deletions.`

Each per-surface spec gives the standalone format and an example:

- [references/cli.md](references/cli.md) — constrained kinds subcommand, flag, option, positional argument.
- [references/http.md](references/http.md) — constrained kinds endpoint, path parameter, query parameter, header, request body field.
- [references/mcp.md](references/mcp.md) — constrained kinds tool, tool argument.
- [references/python.md](references/python.md) — constrained kinds `def`, `class`.
- [references/rust.md](references/rust.md) — constrained kinds `fn`, `struct`, `trait`, `impl`.

## The standalone document

The standalone manifest is a document with an H1 title. Write one manifest for
each surface in which the change adds or deletes constrained declarations. A
surface with no constrained declarations gets no manifest.

Skeleton:

````markdown
# Declaration Manifest: <Surface>
<the surface's binding sentence>

## Additions

### <specific_file>
```<lang>
<declarations>
```

## Deletions

### <specific_file>
```<lang>
<declarations>
```
````
