---
name: spec-doc
disable-model-invocation: true
description: Write a standalone specification document for a surface that already exists or is being designed — a CLI, a file format, an API, a protocol. Produces a permanent reference a reader can implement or script against without reading the source. Load before writing any document named a spec, a format, or a reference. Not for a per-change declaration delta; that is the surface-spec skill.
---

# Spec Document

A spec document states what a thing does. It never states how the thing does it.

A reader must be able to write a script, or a second implementation, from the
document alone. A reader must never learn from it which language, library, or
data structure sits behind the surface.

## When to use this skill

- The user asks for a spec, a specification, a format, or a reference document.
- A surface is stable enough to promise, and the promise should outlive the
  current implementation.
- A README describes a surface in prose, and the user wants the contract
  extracted from it.

Do not use this skill for a per-change declaration delta. That is `surface-spec`,
which states the declarations one diff adds and deletes. This skill produces a
standalone document for a whole surface, and covers behavior as well as
declarations.

## The one test

Ask of every sentence: **would this stay true after a full rewrite in another
language?**

- Yes — it belongs in the document.
- No — it is implementation. Cut it, or restate it as the guarantee it serves.

A mechanism is never the specification. The promise the mechanism keeps is.

> Write: A write either fully replaces the note or leaves it unchanged. A reader
> never observes a partial note.
>
> Do not write: The program writes to a temporary file and renames it.

See [references/boundary.md](references/boundary.md) for the full method and a
rewrite table.

## Procedure

1. **Read the real surface.** Read the source, the tests, and the help output.
   A spec written from a README repeats the README's gaps. Note every default,
   every refusal, and every error condition.
2. **Fix the scope.** Write the Goals and the Non-goals first. Every Non-goal is
   a thing you now may not mention. This is the step that makes the rest easy.
3. **Close the terminology.** Name each concept once. Every later section uses
   that name and no synonym.
4. **Write the surface sections.** One section per part of the surface.
5. **Write the Guarantees.** State what a caller may rely on. Each one is a
   promise about behavior, never about mechanism.
6. **Write the Conformance section.** A numbered, checkable list. If an item
   cannot be tested, it is not a conformance item.
7. **Write the Deferred section.** Name what you left out on purpose, so a
   reader stops looking for it.
8. **Sweep for leaks.** Re-read against the Non-goals and the one test.

## Section order

| Section | Holds |
|---|---|
| Title and version | The name, the version, one sentence on what the thing is. |
| Scope | Goals as a numbered list. Non-goals as a bulleted list. |
| Terminology | A closed glossary. Every term the document later uses. |
| *(the surface)* | One section per part. The bulk of the document. |
| Guarantees | What a caller may rely on. Numbered. |
| Conformance | The checkable list. What an implementation MAY and MUST NOT do. |
| Deferred | What a later revision will cover. |
| Changes | What moved since the last version. Omit at version 1. |
| Appendix | A worked example, end to end. Optional. |

[references/skeleton.md](references/skeleton.md) gives each section in full,
with the phrasing patterns for each.

## Rules

- Every normative sentence carries MUST, MUST NOT, SHOULD, or MAY. A sentence
  with none of these is description, and a reader may ignore it.
- Mark informative text as informative, in its own sentence, at the head of the
  passage.
- State what an absence means. "Absent `--sort` ⇒ `path`." Never leave a default
  to be guessed.
- Give the reason for a surprising rule, in one sentence, and name no mechanism.
- Use one term for one concept, and repeat it.
- Quote an exact string only when the exact string is the contract. Then say so.
- Keep the examples neutral. A sample value naming a real vendor, product, or
  model is a leak. See [references/boundary.md](references/boundary.md).

See [references/normative-language.md](references/normative-language.md) for
which keyword to pick, and for the informative markers.

## Output

Write the document to a file. Use `.md`.

Report three things to the user:

1. The path.
2. Any fact you took from the source that the existing prose documentation does
   not state.
3. Anything you put under Deferred because the source did not settle it.

Do not report a section list. The reader can see the sections.

## Boundaries

**Will:**

- Read the implementation to learn the behavior, and then specify the behavior.
- Refuse to specify a behavior it could not confirm, and list it under Deferred.
- State a guarantee at the level a caller can observe.

**Will not:**

- Name a language, a library, a framework, a data structure, or a file layout
  the caller cannot observe.
- Invent a behavior to fill a gap. An unconfirmed behavior goes under Deferred.
- Promote a current implementation detail to a promise. A promise constrains
  every future implementation, so each one is a deliberate choice.
- Copy a README's claims without checking them against the source.

## References

- [references/skeleton.md](references/skeleton.md) — every section, with its
  phrasing patterns and its failure modes.
- [references/boundary.md](references/boundary.md) — how to keep implementation
  out. The rewrite table, the leak checklist.
- [references/normative-language.md](references/normative-language.md) — MUST,
  SHOULD, MAY. Informative markers. Stating absence.
- [references/example.md](references/example.md) — a complete worked example,
  short enough to read whole.
