---
name: boundaries-and-coupling
description: Use when reviewing an implementation plan, design doc, or proposed module structure for separation of concerns, leaky abstractions, cohesion, coupling, dependency direction, layering violations, or Law of Demeter.
---

# Boundaries & Coupling

**Each unit should have one reason to exist and hide how it does its job. The failures here are the expensive ones — they bake a wrong shape into the dependency graph, and the graph is the hardest thing to change later.** Judge where responsibilities are drawn and what crosses the lines, not what the code looks like.

## What to check

- **Separation of concerns** — does each module/component own exactly one responsibility? A thing that parses *and* renders *and* persists is three things wearing one name. Map each proposed unit to a single "reason to change."
- **Cohesion** — does related logic live together, or is one concern smeared across several units (a change to one feature touching five files)? Low cohesion is the inverse smell of poor separation.
- **Leaky abstraction** — do implementation details escape the interface? A "storage" API that returns SQL rows, a "player" handle that exposes the raw socket/fd, an iterator that only works if you know it's backed by a file. The caller ends up coupled to the *how*, so the *how* can never change.
- **Coupling direction** — do units depend on interfaces/abstractions or on concrete internals? Does A reach into B's private state? Prefer depend-on-abstraction; the concrete should be substitutable.
- **Dependency direction & layering** — do dependencies point one way (toward the stable core / inward)? Flag cycles (A→B→A) and upward calls (a low layer calling back into a high layer, e.g. core importing UI). A plan that adds an edge against the existing direction is a finding even if each piece looks fine.
- **Law of Demeter** — does the design require reaching through chains (`a.b.c.d`)? That hard-codes the shape of three objects into one call site. Usually a sign a responsibility lives in the wrong place.

## Tells in a plan

- A component described with "and" / "also handles" / "manages everything about" — it's doing too much.
- An interface whose return types or parameters name a backing technology (rows, JSON blobs, file handles, framework objects).
- "Module X needs access to Y's internal …" — coupling to internals.
- A new dependency that points from a stable/low layer toward a volatile/high one.
- The same domain rule enforced in two layers because the boundary leaks.

## What good looks like

- Each unit states one responsibility you can name in a phrase.
- Interfaces speak the domain, not the mechanism — you could swap the backing implementation without touching callers.
- Dependencies form a DAG pointing toward stability; no cycles, no back-calls.
- Callers talk to their immediate collaborators, not through them.

## How to suggest fixes

Name the boundary that's wrong and where it should be: "split persistence out of `Renderer` into a `Store` it depends on," "have the interface return a domain `Track`, not the decoder's frame struct," "invert this dependency — pass an interface in rather than importing the concrete." One structural sentence per finding. Don't redesign the whole plan unless the core shape is wrong.
