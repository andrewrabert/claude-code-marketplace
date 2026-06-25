---
name: resource-lifecycle
description: Use when reviewing an implementation plan or design doc for resource management and state — RAII/ownership, cleanup tied to lifetime, single source of truth for state, and making invalid states unrepresentable.
---

# Resource Lifecycle & State

**A resource should be owned by exactly one thing, released when that thing dies, and every piece of state should have exactly one authoritative home. Most "spooky action at a distance" bugs trace back to violating one of these — and a plan is where you decide them.** Judge who owns what, when it's released, and where the truth lives.

## What to check

- **RAII / cleanup tied to lifetime** — is every acquired resource (file, socket, lock, GPU handle, subscription, spawned task) released by the lifetime of an owning object, not by a manual "remember to close" step? Manual paired acquire/release is a leak waiting on the next early-return or error path. The plan should say *who drops it*, not *where we call close*.
- **Single owner** — does each resource have one clear owner? "Shared mutable, anyone can touch it" is the smell. Shared *immutable* is fine; shared *mutable* needs a named owner and a discipline (message-passing, a lock with a defined scope).
- **Single source of truth** — is each piece of state authoritative in exactly one place, with everything else a derived/observed view? Flag any plan that lets two components both *decide* the same value — they will drift. Consumers reflect state; they don't co-own it. (Example doctrine: playback state flows out from the player; the UI mirrors it, never sets it.)
- **Invalid states unrepresentable** — does the design encode invariants in types/structure so bad combinations can't be constructed, rather than guarding them with runtime checks scattered at call sites? "A connection that's `open` but has no socket" should be impossible to build, not validated everywhere.
- **Lifecycle ordering** — are init/teardown order dependencies explicit? Hidden "must call A before B" ordering is a defect class; the plan should make it structural (B can't exist without A).
- **Construction cost / lifetime placement** — is each resource built at the lifetime that matches its true scope? An expensive-to-build, broadly-scoped object (a compiled pipeline, a glyph atlas, a connection pool — anything tied to a device/process, not to one request) constructed *inside* a per-operation function is both a lifetime mistake and a recurring latency cost: it's rebuilt on every call when it could be built once and reused. Flag when something device- or process-scoped is created per-request/per-menu/per-frame. The fix is to hoist it to the owner whose lifetime actually matches its scope.

Note: *single source of truth* applies beyond runtime state — a configured value that must agree across the system (a shared dependency version, a constant duplicated across manifests) has the same drift failure mode; see the `dependency-strategy` lens for the version/manifest case.

## Tells in a plan

- "We'll close / free / unsubscribe it when …" described as a step rather than an owner's drop.
- The same value stored or cached in two places "to keep them in sync" — that *is* the bug.
- A global or widely-shared mutable bag of state ("the context," "the manager") that many components write.
- Booleans/flags that only make sense in combination (`is_loading` + `data` + `error` all independently settable).
- Two components that both push the same fact outward (UI sets pause *and* the engine sets pause).
- An expensive handle (compiled pipeline, glyph atlas, pool) constructed inside a per-request/per-operation function when it's really device- or process-scoped.

## What good looks like

- Each resource has an owner whose lifetime brackets it; teardown is automatic.
- One authoritative store per piece of state; all else observes/derives.
- Types make illegal states impossible to instantiate (enums/sum types over flag soup; non-null handles over "maybe initialized").
- Acquisition order is enforced by construction, not convention.

## How to suggest fixes

Point at the owner and the truth: "give the socket to a `Connection` that closes it on drop instead of the manual `close()` in the error path," "make the engine the sole writer of pause; the UI observes it," "replace the three flags with one `enum State { Loading, Ready(Data), Failed(Err) }`," "build the iced engine once on the shared device and reuse it — don't rebuild the pipeline + glyph atlas inside `run_menu` every time a menu opens." One sentence. Flag the tradeoff if the single-owner discipline forces message-passing where direct mutation was assumed.
