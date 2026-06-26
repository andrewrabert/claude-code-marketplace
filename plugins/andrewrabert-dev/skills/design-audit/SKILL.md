---
name: design-audit
description: Use to apply ONE design lens (e.g. resource-lifecycle/RAII, boundaries-and-coupling) exhaustively across a whole codebase or large subtree — fan out one design-architect pass per module, then aggregate and dedup. For repo-wide structural audits too big for a single review.
---

# Design Audit

**A single `design-architect` review fits one bounded artifact in one context — it samples a big repo, it doesn't sweep it. An audit is the opposite job: pick one lens and find *every* instance across the whole tree.** You get there by fan-out — many bounded passes, one per module, aggregated — not by handing a whole codebase to one review.

Use this when the ask is "find all the X problems in this codebase" (X = RAII/lifecycle, leaky boundaries, wide interfaces, …). For reviewing a single plan/diff/file, invoke `design-architect` directly instead — you don't need the fan-out.

## Method

1. **Fix the lens and the scope.** One lens per audit — map the request to it: RAII/ownership/cleanup → `resource-lifecycle`; separation/coupling/layering → `boundaries-and-coupling`; API surface → `interface-design`; DRY/YAGNI/seams → `change-resilience`; third-party pins → `dependency-strategy`; stage ordering → `delivery-sequencing`. If the request spans several, run several audits, not one blurred pass. Set the root (whole repo or a subtree).
2. **Discover units.** Glob the tree into **bounded slices** that each fit one agent context — language-aware: Python packages, Rust crates, JS/TS dirs, or top-level source dirs. Produce an explicit worklist of slices. If a slice is still too big for one context, split it further. Skip vendored/generated/`node_modules`/build output.
3. **Fan out, one pass per slice.** For each slice, spawn one `design-architect` (Agent tool), all in parallel where the runner allows (batch if there are many). Give each pass:
   - the slice's paths,
   - "review **existing code**" (not a plan),
   - "apply **only** the `<lens>` lens, **exhaustively** — flag every instance, do not prune to the worst few."

   `design-architect` self-verifies each finding via `design-verifier`, so every pass returns code-grounded findings, not guesses. (When available, the Workflow tool is a good fit for driving the per-slice passes; the Agent tool works fine otherwise.)
4. **Aggregate.** Collect all passes. **Dedup** by `file:line` + principle (the same issue can surface from two adjacent slices). Sort by severity (🔴 → 🔵).
5. **Report with coverage.** Emit one consolidated findings list, then a coverage line: which slices ran, and **anything skipped, truncated, or split** — state it. Never present a sampled subset as if it were the whole tree.

## Rules

- **One lens per audit.** Mixing lenses across a repo-scale pass produces noise; run them as separate audits and label each.
- **Exhaustive, not weighted.** Unlike a single review (which prioritizes what calcifies and drops the trivial), an audit's job is full coverage of the one lens — keep the 🔵s, the caller asked for all of them.
- **No silent caps.** If you batch, sample, or cap for cost, say so in the coverage line. Silent truncation reads as "covered everything" when it didn't.
- **Cost is real.** N slices = N agent passes. For a large tree, tell the caller the slice count before fanning out if it's large, and let them scope down if they want.
- **Structural only.** Same boundary as `design-architect` — this finds organizational problems, not line-level bugs or style.

## Output

```
Lens: resource-lifecycle   Scope: src/   Coverage: 4/4 slices (none skipped)

🔴 bug-in-waiting | RAII / cleanup tied to lifetime | src/net/socket.py:88
  problem: …
  fix: …
🟡 …
```

End with the coverage line if not led with it. If a slice errored or was split, name it.
