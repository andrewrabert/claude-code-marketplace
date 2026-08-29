# Normative language

Which keyword to pick, and how to keep rules apart from description.

---

## The keywords

Use the RFC 2119 set. Nothing else carries force.

| Keyword | Means | Use when |
|---|---|---|
| MUST | Absolute requirement. | Breaking it makes the implementation non-conformant. |
| MUST NOT | Absolute prohibition. | Doing it makes the implementation non-conformant. |
| SHOULD | Strong recommendation. | A good implementation does it. A reason to skip it can exist, and the implementer must weigh it. |
| SHOULD NOT | Strong discouragement. | Same, inverted. |
| MAY | Genuinely optional. | Neither choice affects conformance. A caller MUST NOT depend on which was picked. |

Write them in capitals. Capitals mark the sentence as normative at a glance, and
let a reader grep the rules out of the prose.

State the convention once, near the top:

```markdown
The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be read as
described in RFC 2119.
```

---

## Picking between them

**MUST or SHOULD.** Ask what happens when an implementation ignores it. If a
caller's correct code breaks, it is MUST. If the result is merely worse, it is
SHOULD.

Do not use MUST for everything. A document where every rule is MUST gives an
implementer no room, and they will violate one and stop trusting the rest.

**MAY and the caller.** Every MAY creates an obligation on the other side. When
an implementation MAY choose, a caller MUST NOT depend on the choice. Write both
halves. A lone MAY reads as permission and gets depended on.

> An implementation MAY return results in any order. A caller MUST NOT depend on
> the order.

**Never MUST a fact.** "The file MUST be UTF-8" is a rule. "The file MUST have
been written by this tool" is not a rule, it is an assumption. State assumptions
as description.

---

## Rules against description

A sentence without a keyword is description. A reader may ignore it, and will.

So:

- Never hide a requirement in a descriptive sentence. "Paths are relative to the
  root" is description. "A path MUST be relative to the root" is a rule.
- Never attach a keyword to a sentence that is not a rule. "This document MUST
  be read in order" is noise.
- One rule per sentence. Two MUSTs joined by "and" produce a partial violation
  no one can name.

---

## Informative passages

Some passages explain rather than require: a rationale, a usage walkthrough, a
worked example.

Mark them. Put the marker in its own sentence, at the head of the passage:

```markdown
### <n>.<n> How a consumer uses this (informative)

This subsection is informative, not normative.
```

An informative passage MUST contain no keyword. If it needs one, it is not
informative, and the rule belongs in a normative section.

This is the release valve. It lets you write the helpful explanation without
that explanation becoming a constraint on every future implementation.

---

## Stating absence

Every optional thing needs its absence defined. This is the most commonly
skipped rule, and the one that produces the most divergent implementations.

```markdown
Absent `status` ⇒ `stable`.
Absent `--sort` ⇒ `path`.
No `verified` entry ⇒ the concept is unverified.
An empty `--in` value denies both modes.
An omitted `=<modes>` means read and write.
```

Three kinds of absence, and each needs a different sentence:

| Kind | Say |
|---|---|
| A default | `Absent X ⇒ <value>.` |
| A meaningful absence | `No X ⇒ <state>.` The absence is itself information. |
| A refusal | `X is required. A call without it is refused.` |

Never write "optional" alone. Optional says a caller may omit it. It does not
say what happens when they do.

---

## Rationale

A surprising rule earns one sentence of reason. Attach it to the rule, and name
no mechanism.

> Labels are keyed rather than positional, because a positional index
> misattributes silently the moment the list is reordered.

Rules for rationale:

- One sentence. A paragraph of reasoning belongs in an informative subsection.
- It explains the rule. It does not explain the code.
- Only for a rule a competent reader would otherwise question. A rationale on an
  obvious rule makes the document longer and the rule look doubtful.

---

## One term, one meaning

Pick one word per concept and repeat it. A spec is not prose; variation reads as
distinction.

If the document says "note", it never says "file", "document", or "entry" for
the same thing. When you catch a synonym, do not rewrite the sentence around it.
Replace the word everywhere, and check the glossary still holds one entry.

The same applies to verbs. If a bad input is "refused", it is never "rejected",
"denied", or "ignored" — those are three different behaviors, and a reader will
assume you meant three different things.
