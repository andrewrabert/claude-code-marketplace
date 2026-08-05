---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when the user wants to pin down domain terminology or a ubiquitous language, record an architectural decision, or when another skill needs to maintain the domain model.
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design. This is the *active* discipline — challenging terms, inventing edge-case scenarios, and writing the glossary and decisions down the moment they crystallise. (Merely *reading* `CONTEXT.md` for vocabulary is not this skill — that's a one-line habit any skill can do. This skill is for when you're changing the model, not just consuming it.)

## Storage: noted, exclusively

The domain model lives in noted (the `mcp__noted__*` tools) and nowhere else. Never create, edit, or read `CONTEXT.md`, `CONTEXT-MAP.md`, or ADR files in the repository — not even if such files already exist there; noted is the sole source of truth. Read with `ReadNote`, discover with `SearchNotes`, write with `WriteNote`/`EditNote`.

All paths below are relative to the project's prefix in the note tree; resolving that prefix is out of scope here.

Most projects have a single context:

```
<project>/
├── CONTEXT.md
└── adr/
    ├── 0001-event-sourced-orders.md
    └── 0002-postgres-for-write-model.md
```

If a `CONTEXT-MAP.md` note exists at the project prefix, the project has multiple contexts. The map points to where each one lives:

```
<project>/
├── CONTEXT-MAP.md
├── adr/                              ← system-wide decisions
├── ordering/
│   ├── CONTEXT.md
│   └── adr/                          ← context-specific decisions
└── billing/
    ├── CONTEXT.md
    └── adr/
```

Create notes lazily — only when you have something to write. If no `CONTEXT.md` note exists, write one when the first term is resolved. Write the first ADR note when the first ADR is needed; intermediate paths need no setup.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in the `CONTEXT.md` note, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update CONTEXT.md inline

When a term is resolved, update the `CONTEXT.md` note right there with `EditNote` (or `WriteNote` if it does not exist yet). Don't batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).
