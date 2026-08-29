# Skeleton

Every section, what it holds, and how it fails.

Sections are numbered in the document. A reader cites `§7.3`, so the numbers are
part of the contract. Do not renumber across a minor version.

---

## Title and version

```markdown
# <Name>

**Version <major>.<minor>**

<One or two sentences. What the thing is, and what it operates on.>

<One sentence naming what this document specifies.>
```

The last sentence is load-bearing. It tells a reader which questions this
document answers, before they read a word of the body.

**Fails when:** the opening sells the thing. A spec does not persuade. Delete
any adjective claiming quality.

---

## Scope

Two lists.

```markdown
## 1. Scope

### Goals

1. <What a reader can do with this document.>

### Non-goals

- <A thing this document deliberately does not decide.>
```

Goals are numbered, and each states a capability the document gives the reader.
Not a feature of the thing — a capability of the document.

Non-goals are the most useful part of the whole section. Each one licenses you
to stay silent later. Write them before the body, and the body writes itself.

Every Non-goal should be a real temptation. "Does not specify the wire protocol"
is useful because a reader might expect it. "Does not specify the weather" is
noise.

**Fails when:** the Non-goals are written after the body. Then they describe
what you happened to omit, rather than constraining what you may write.

---

## Terminology

A closed glossary. Every term the body uses in a special sense.

```markdown
## 2. Terminology

- **<Term>**: <One sentence. What it is.> <Optional second sentence: where it is
  defined in full.>
```

Rules:

- Define a term before the body uses it.
- One term per concept. If two words appear for one idea, pick one and delete
  the other from the whole document.
- A term that appears once does not need an entry.
- Do not define common English.

**Fails when:** the body introduces a term the glossary does not hold. Sweep the
body for bolded or quoted nouns and check each against this list.

---

## The surface

The bulk. One section per part of the surface. There is no fixed shape, because
the shape follows the thing.

Common shapes:

| Kind of surface | Section per |
|---|---|
| CLI | Command group. Plus one section for settings, one for paths. |
| File format | Structural level: the container, the record, each field family. |
| HTTP API | Resource. Plus one for authentication, one for errors. |
| Protocol | Message. Plus one for the state machine, one for framing. |

Within a section:

- A table for anything enumerable. Commands, fields, states, defaults.
- Prose for anything conditional.
- A fenced block for an exact input or output shape.

Every default appears in the table that holds the thing it defaults. Never in
prose alone.

**Fails when:** a section explains why the surface has its shape. Rationale
belongs in one sentence attached to a surprising rule, not in a paragraph.

---

## Guarantees

What a caller may rely on. This section is short and it is the reason the
document exists.

```markdown
## <n>. Guarantees

A caller MAY rely on all of the following.

1. **<Short name.>** <The promise, stated as observable behavior.>
```

Each guarantee:

- Is observable. A caller can write a test that fails when it breaks.
- Names no mechanism.
- Constrains every future implementation. Write only what you are willing to
  keep.

A guarantee is not a feature list. "The tool is fast" is not a guarantee.
"A read never blocks on a concurrent write" is.

**Fails when:** it restates the surface sections. A guarantee crosses sections.
It is the promise that holds no matter which command the caller used.

---

## Conformance

The checkable list. An implementer reads this to know when they are done. A test
author reads it to know what to test.

```markdown
## <n>. Conformance

An implementation conforms to this document if:

1. <A checkable condition, citing the section that defines it.>

An implementation MAY:

- <A freedom, stated explicitly.>

An implementation MUST NOT:

- <A prohibition.>
```

The `MAY` list matters as much as the numbered list. It tells an implementer
where they are free, so they do not over-constrain themselves, and it tells a
caller what they may not depend on.

Rules:

- Each numbered item cites the section that defines it. Conformance restates
  nothing; it points.
- An item that cannot be tested is not a conformance item. Move it to
  Guarantees, or cut it.
- Be permissive by default. List what an implementation must not do, and let
  everything else be allowed. A spec that forbids by omission cannot be extended.

**Fails when:** the list repeats the whole body. Conformance is a checklist over
the body, not a summary of it.

---

## Deferred

What a later revision will cover.

```markdown
## <n>. Deferred

The following are intentionally left to a later revision:

- <A question this document does not answer.>
```

Two jobs:

1. It stops a reader from searching for something that is not there.
2. It records that you saw the gap. A gap named is a decision. A gap unnamed is
   an oversight.

Put here anything the source did not settle, anything you could not confirm, and
anything you chose not to promise yet.

**Fails when:** it is empty. A first version always has gaps. An empty Deferred
section means you did not look.

---

## Changes

Omit at version 1.

```markdown
## <n>. Changes from <previous version>

### Breaking changes

- **<What changed.>** <What a reader must do.> <The fallback, if one exists.>

### Additive changes

- <A new optional thing. Its absence yields the previous version's behavior.>
```

Separate the two. A reader scanning for breakage must not read past an additive
list to find it.

**Fails when:** a breaking change hides in the additive list. If a conformant
document under the old version stops being conformant, it is breaking.

---

## Appendix: worked example

Optional, and worth the space when the surface is unusual.

One example, end to end, exercising every family the document defines. When the
document supersedes an earlier version, show the same example in both forms.

**Fails when:** the example uses values that leak. See
[boundary.md](boundary.md).
