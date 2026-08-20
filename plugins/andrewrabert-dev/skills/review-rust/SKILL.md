---
name: review-rust
description: Rust code review reference. Load before reviewing any Rust code — anti-pattern checklist plus deep references for ownership, error handling, concurrency, performance, and unsafe/FFI findings.
---

# Rust Review

## Core Question

**Is this pattern hiding a design problem?**

When reviewing code:
- Is this solving the symptom or the cause?
- Is there a more idiomatic approach?
- Does this fight or flow with Rust?

## Reference Files

Read the file that matches the finding class. Paths are relative to this skill.

| Finding involves | Read |
|------------------|------|
| Any Rust diff (always) | [references/anti-patterns.md](references/anti-patterns.md) |
| Moves, borrows, E0382/E0499/E0502/E0507/E0515/E0597/E0716 | [references/ownership-errors.md](references/ownership-errors.md) |
| Lifetime annotations, `'static`, HRTB, variance | [references/lifetime-patterns.md](references/lifetime-patterns.md) |
| API ownership shape: `String` vs `&str` params, taking ownership | [references/ownership-api-design.md](references/ownership-api-design.md) |
| `unwrap`, `?`, error types, thiserror/anyhow, panics | [references/error-patterns.md](references/error-patterns.md) |
| Send/Sync errors, deadlocks, locks across `await` | [references/concurrency-errors.md](references/concurrency-errors.md) |
| Task spawning, select, channels, cancellation, backpressure | [references/async-patterns.md](references/async-patterns.md) |
| `std::thread`, shared state, thread pools | [references/thread-patterns.md](references/thread-patterns.md) |
| Allocation waste, iterator chains, memory layout | [references/performance.md](references/performance.md) |
| `unsafe`, raw pointers, FFI, `#[repr(C)]`, transmute | [references/unsafe/INDEX.md](references/unsafe/INDEX.md), then the matching rule in `references/unsafe/rules/` |

For unsafe review: [references/unsafe/checklists/review-unsafe.md](references/unsafe/checklists/review-unsafe.md) is the pass
checklist; cite rule IDs (e.g. `safety-09`) in findings.

## Anti-Pattern → Better Pattern

| Anti-Pattern | Why Bad | Better |
|--------------|---------|--------|
| `.clone()` everywhere | Hides ownership issues | Proper references or ownership |
| `.unwrap()` in production | Runtime panics | `?`, `expect`, or handling |
| `Rc` when single owner | Unnecessary overhead | Simple ownership |
| `unsafe` for convenience | UB risk | Find safe pattern |
| OOP via `Deref` | Misleading API | Composition, traits |
| Giant match arms | Unmaintainable | Extract to methods |
| `String` everywhere | Allocation waste | `&str`, `Cow<str>` |
| Ignoring `#[must_use]` | Lost errors | Handle or `let _ =` |

## Code Smell → Refactoring

| Smell | Indicates | Refactoring |
|-------|-----------|-------------|
| Many `.clone()` | Ownership unclear | Clarify data flow |
| Many `.unwrap()` | Error handling missing | Add proper handling |
| Many `pub` fields | Encapsulation broken | Private + accessors |
| Deep nesting | Complex logic | Extract methods |
| Long functions | Multiple responsibilities | Split |
| Giant enums | Missing abstraction | Trait + types |

## Common Error Patterns

| Error | Anti-Pattern Cause | Fix |
|-------|-------------------|-----|
| E0382 use after move | Cloning vs ownership | Proper references |
| Panic in production | Unwrap everywhere | ?, matching |
| Slow performance | String for all text | &str, Cow |
| Borrow checker fights | Wrong structure | Restructure |
| Memory bloat | Rc/Arc everywhere | Simple ownership |

## Deprecated → Better

| Deprecated | Better |
|------------|--------|
| Index-based loops | `.iter()`, `.enumerate()` |
| `collect::<Vec<_>>()` then iterate | Chain iterators |
| Manual unsafe cell | `Cell`, `RefCell` |
| `mem::transmute` for casts | `as` or `TryFrom` |
| Custom linked list | `Vec`, `VecDeque` |
| `lazy_static!` | `std::sync::OnceLock` |

## Quick Review Checklist

- [ ] No `.clone()` without justification
- [ ] No `.unwrap()` in library code
- [ ] No `pub` fields with invariants
- [ ] No index loops when iterator works
- [ ] No `String` where `&str` suffices
- [ ] No ignored `#[must_use]` warnings
- [ ] No `unsafe` without SAFETY comment
- [ ] No lock guard held across `await`
- [ ] No blocking calls in async functions
- [ ] No giant functions (>50 lines)
