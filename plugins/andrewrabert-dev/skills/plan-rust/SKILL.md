---
name: plan-rust
description: Rust design decisions for planning. Load before declaring any Rust surface — error strategy (thiserror vs anyhow, Result vs Option vs panic), concurrency model (threads vs async, sharing model), and naming/style conventions.
---

# Rust Plan

Settle these decisions before declaring a surface. Emit one shape; never leave
the choice to the implementer.

## Error Strategy

**Is this failure expected or a bug?**

```
Is failure expected?
├─ Yes → Is absence the only "failure"?
│        ├─ Yes → Option<T>
│        └─ No → Result<T, E>
│                 ├─ Library → thiserror
│                 └─ Application → anyhow
└─ No → Is it a bug?
        ├─ Yes → panic!, assert!
        └─ No → Consider if really unrecoverable
```

| Context | Error Crate | Why |
|---------|-------------|-----|
| Library | `thiserror` | Typed errors for consumers |
| Application | `anyhow` | Ergonomic error handling |
| Mixed | Both | thiserror at boundaries, anyhow internally |

Fallible operations name their error type in the return. Declare the error
enum's variants in the plan; they are API.

Details: [references/error-strategy.md](references/error-strategy.md) (library vs application design,
error layering, testing).

## Concurrency Model

**Is this CPU-bound or I/O-bound, and what's the sharing model?**

```
What type of work?
├─ CPU-bound → std::thread or rayon
├─ I/O-bound → async/await
└─ Mixed → hybrid (spawn_blocking)

Need to share data?
├─ No → message passing (channels)
├─ Immutable → Arc<T>
└─ Mutable →
   ├─ Read-heavy → Arc<RwLock<T>>
   ├─ Write-heavy → Arc<Mutex<T>>
   └─ Simple counter → AtomicUsize
```

Decide Send/Sync at plan time: a type that crosses threads is `Send`, a type
shared by reference is `Sync`. `Rc` and `RefCell` are neither; they never
appear in a surface that async handlers or spawned tasks touch.

Details: [references/concurrency-models.md](references/concurrency-models.md) (async models, Send/Sync
semantics, performance characteristics).

## Conventions

Declarations follow Rust naming and style convention so the surface compiles
as written: [references/conventions.md](references/conventions.md) (50 core rules),
[references/clippy-lints.md](references/clippy-lints.md) (lint reference).

## Ownership in Signatures

| Situation | Parameter type |
|-----------|----------------|
| Read only | `&T`, `&str`, `&[T]` |
| Store the value | `T`, `String`, `Vec<T>` |
| Maybe-owned | `Cow<'_, str>` |
| Conditional ownership | `impl Into<T>` |

Return owned types from constructors; return references only when the
lifetime is already anchored to a parameter.
