---
name: change-resilience
description: Use when reviewing a plan, diff, or existing code for how well it absorbs change — DRY vs YAGNI balance, open/closed extension points, testability seams, and reversibility of decisions.
---

# Change Resilience

**Code is read and changed far more than it's written. Good structure makes the likely changes cheap without paying upfront for changes that may never come. The two failure modes pull opposite ways — too much speculative abstraction, or too much copy-paste — and a reviewer has to call both.** Judge how the design ages, not how it looks on day one.

## What to check

- **DRY, but not premature** — is each *concept* defined once, so a rule change happens in one place? Flag duplicated domain logic that must change together. **But** don't reward abstraction-on-first-repeat: two things that look alike today but change for different reasons should stay separate. The test is *shared reason to change*, not *similar code*.
- **YAGNI / speculative generality** — does the design build for requirements that don't exist? Plugin systems with one plugin, config for things that never vary, generic frameworks wrapping a single case, "we might need …" interfaces. Every speculative seam is real complexity paid now against a maybe. Cut to what's actually required.
- **Open/closed where churn is real** — at the points that genuinely change often (new formats, new providers, new platforms), can you extend without editing the core? Add an implementation, not a new `switch` arm in five files. **Only** where the churn is real — applying open/closed everywhere is just speculative generality with a nicer name.
- **Testability seams** — can the units be tested without spinning up the whole world? Are dependencies injectable (passed in) rather than reached for (globals, singletons, direct construction of heavy collaborators)? Code with no seam for the network/clock/filesystem/GPU is untestable. This often *is* the separation-of-concerns check from the test's point of view.
- **Verification tests the invariant, not just asserts it** — when the work rests on an equivalence or correctness invariant ("the GPU output is identical to the CPU path," "the new encoder round-trips the old format"), does its verification actually test that invariant, or only state it and check by eyeball? Verification that is all-manual-runtime ("open it and confirm it looks the same") has no guard against the very drift its DRY findings warn about — the shared seam exists precisely so an automated equivalence/golden check can pin it. An asserted invariant with no test is a regression waiting for the first refactor.
- **Reversibility** — does any decision paint into a corner — a data format, a public API, a wire protocol, a dependency that's hard to back out? Mark one-way doors and make sure they're the ones worth committing to. Two-way doors don't need this scrutiny; spend it on the irreversible.

## Tells

- The same business rule computed in multiple places "for now."
- Abstraction layers, factories, or config knobs with exactly one concrete use.
- "To be flexible / future-proof / in case we need …" without a named, real requirement.
- A `switch`/`match` on a type tag that will keep growing — and lives in several files.
- Core logic that constructs its own database/HTTP/clock/GPU handle — no injection point, no test seam.
- An asserted equivalence/correctness invariant ("identical output," "same behavior") whose only verification is manual inspection — no automated equivalence or golden test.
- A format or public contract introduced casually that callers/persisted data will depend on forever.

## What good looks like

- One definition per concept; duplication only where the pieces genuinely diverge.
- Complexity matches today's requirements; generality appears the moment a *second* real case does, not before.
- The few high-churn axes are open for extension; everything else is plain and direct.
- Heavy dependencies are injected, so units test in isolation.
- One-way doors are identified and deliberately chosen.

## How to suggest fixes

Push toward the cheaper-to-change shape, in one sentence: "extract this fee calc into one function — it's enforced in three places," "drop the plugin abstraction; there's one implementation, inline it until there's a second," "make the parser dispatch on a `Format` trait so a new format is one file, not edits across five," "inject the clock so this is testable without sleeping," "this on-disk format is a one-way door — pin it down before shipping," "add an output-equivalence test over the shared `build_scene` for both finalizers — don't leave 'identical look' to manual inspection." Call the tradeoff: more indirection now vs cheaper change later, and whether the change is actually likely.
