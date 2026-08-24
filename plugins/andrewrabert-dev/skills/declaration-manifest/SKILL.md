---
name: declaration-manifest
description: Declaration manifest formats for plans. Load before writing any `Declaration Manifest` plan section — the per-language manifest specs (Python, Rust) and the rule for embedding a manifest as a plan section.
---

# Declaration Manifest

A declaration manifest states one change as an equation. The set of declarations
the combined diff adds equals the set under `Additions`. The set it deletes
equals the set under `Deletions`.

Per-language specs, each with the standalone format and an example:

- [references/python-declaration-manifest.md](references/python-declaration-manifest.md) — constrained kinds `def`, `class`.
- [references/rust-declaration-manifest.md](references/rust-declaration-manifest.md) — constrained kinds `fn`, `struct`, `trait`, `impl`.

## Embedding in a plan

The standalone manifest is a document with an H1 title. Inside a plan it is one
H2 section:

- The title becomes the section heading: `## Declaration Manifest: <Language>`.
- Every other heading demotes one level: `## Additions` becomes `### Additions`,
  and `### <specific file>` becomes `#### <specific file>`.
- The heading references inside the binding sentence demote the same way.
- Write one section per language in which the change adds or deletes constrained
  declarations. A language with no constrained declarations gets no section.
- Every other rule of the standalone format applies unchanged.

Embedded skeleton:

````markdown
## Declaration Manifest: <Language>
<the language's binding sentence, heading references demoted>

### Additions

#### <specific_file>
```<lang>
<declarations>
```

### Deletions

#### <specific_file>
```<lang>
<declarations>
```
````
