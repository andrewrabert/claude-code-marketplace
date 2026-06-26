---
name: interface-design
description: Use when reviewing a plan, diff, or existing code for interface and API quality — least privilege, narrow surfaces, command/query separation, and error-handling strategy.
---

# Interface Design

**An interface is a promise you have to keep. The narrower it is, the less it constrains the implementation behind it and the fewer ways callers can misuse it. A wide, surprising, or error-swallowing surface commits you to all of that — whether it's proposed in a plan or already shipped.** Judge the shape of the contract, not the internals.

## What to check

- **Least privilege / smallest surface** — does each unit expose only what callers actually need? Public-by-default, "expose it in case someone wants it," and god-objects-with-30-methods all over-promise. Every exported symbol is a thing you can't change freely later.
- **Command/query separation** — does a function either *do* something (mutate, side effect) or *answer* something (return a value), not both invisibly? A getter that also mutates, or a "check" that also creates, surprises callers and breaks reasoning about order. Mutating builders/fluent APIs are a deliberate exception — name it if so.
- **Narrow, total signatures** — do inputs and outputs say what's really required and possible? Avoid wide param bags, boolean flags that change behavior mode (`render(thing, true, false)`), and return types that lie about failure. Prefer specific types over stringly-typed or "options struct with 12 optional fields."
- **Error strategy, decided up front** — is it decided *how* failures surface and *where* they're handled? Result/exception/error-code is a real choice; pick one per layer and be consistent. Flag: swallowing errors, returning sentinel values (-1, null, empty) that callers forget to check, and panics/aborts on recoverable conditions. Decide what's recoverable vs fatal at the boundary, not ad hoc.
- **Idempotency / reentrancy where it matters** — if an operation can be retried, redelivered, or called concurrently, does the contract say whether that's safe? Retry/queue/event-handler designs that don't address this are a finding.
- **Callback & closure-bound honesty** — when a function takes a closure and runs it *inside* a loop that can retry/reconfigure/redeliver, the closure's bound is part of the contract. A `FnOnce`/one-shot callback silently forbids re-invocation — so a retry path that must run the callback again (re-record into a freshly-acquired resource, recompute against the new state) either can't retry or presents a result the callback never produced. Match the bound to the call pattern: if the loop may invoke the closure more than once, it must be a multi-call bound, and the contract should say how many times and against what state.

## Tells

- "Expose a method for …" repeated until the type has a dozen — surface creep.
- A function name that's a noun/question (`status`, `isReady`) but the description has it changing state.
- Boolean parameters selecting behavior, or an options bag absorbing unrelated knobs.
- "Returns null/-1/empty on failure" — sentinel errors callers will skip.
- "We'll handle errors later" / no statement of what's fatal vs recoverable.
- Retry or concurrent paths with no word on idempotency.
- A closure run inside an acquire/retry/reconfigure loop typed as one-shot (`FnOnce`), when that loop can re-run after the resource it records into is replaced.

## What good looks like

- Minimal public surface; everything else private. Adding to it later is easy; removing is the hard part you're avoiding.
- Each operation is clearly a command or a query.
- Signatures are specific and honest about failure (Result/typed errors), consistent within a layer.
- The recoverable/fatal split and the concurrency contract are stated, not implied.

## How to suggest fixes

Name the contract change: "drop these four getters from the public surface; only `play/pause/seek` need to be," "split `getOrCreate` into `get` (query) and `create` (command)," "return `Result<Track, LoadError>`, not `Track?` with null-on-failure," "state that this handler must be idempotent — events can redeliver," "type the draw closure `FnMut`, not `FnOnce` — the Lost→reconfigure path must re-record into the new view." One sentence each. If narrowing the surface costs a convenience callers wanted, say so.
