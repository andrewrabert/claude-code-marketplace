---
name: dependency-strategy
description: Use when reviewing a plan, diff, or existing code for how it depends on third-party code — version single-source-of-truth across the workspace, API stability of the chosen dep, blast radius on currently-working/fallback paths, and reversibility of the dependency choice.
---

# Dependency Strategy

**A third-party dependency is something you don't control changing under code you do. The version you pin, how stable that version's API is, and which of your existing paths you couple to it are design decisions — usually the least-reversible ones, and the ones that get the least scrutiny.** Judge what's committed to outside your own walls, not the code inside them.

## What to check

- **Version single-source-of-truth** — is each shared dependency pinned in exactly one authoritative place, or is the same dep constrained in several crates/manifests that must be kept aligned by hand? Flag mismatched specs for one logical version (an exact `29.0.3` in one crate, a range `"29"` in another), and **transitive** pins that can drift independently (a dep whose own lockstep requirement — e.g. a git-master crate's bundled GPU/runtime version — must match your direct pin but isn't enforced anywhere). Two places that decide one version *will* diverge.
- **API stability of the dep** — what does the chosen version actually promise? Pinning a rev of a moving git branch buys a *snapshot*, not a stable API — every bump is unbounded churn with no semver contract. Depending on a pre-release / `*-dev` / `master` for anything load-bearing is borrowing against a moving target. Name it when the design leans on an unstable upstream.
- **Blast radius on the known-good path** — does the change drag a *currently stable* path — especially a fallback, safety-net, or "always works" path — onto the new, less-stable dependency? A fallback's entire value is that it works when the primary doesn't; coupling it to the same moving/unproven dep inverts its purpose and removes the safety it existed to provide. The new path may earn the risk; the path that was already fine should not inherit it for free.
- **Reversibility of the dep choice** — a major-version jump, a git-rev commitment, or a new wire/format dependency is a one-way-ish door. Can you back the new path out without also reverting an API migration forced on unrelated, previously-working code? If aborting the experiment means un-migrating the stable path too, the choice is more entangled than it looks.
- **Scope of the bump** — is the dependency change scoped to the code that needs it, or does it force a workspace-wide migration (a shared crate's major bump rippling to every consumer) as a side effect of one feature? Flag when one feature's dep need rewrites unrelated callers.

## Tells

- The same dependency version written in two manifests, or an exact pin in one place and a range in another, "kept in sync" by hand.
- "Pin to git rev `abc123…`" / "use master" / "0.x-dev" for a load-bearing path, with "expect API churn" stated as accepted rather than contained.
- A fallback / SHM / safety-net / legacy path quietly migrated onto the same new dependency as the feature path.
- A major-version bump of a shared crate justified by one consumer, with the rest "re-validated against the new API."
- No statement of how to back the dependency out if the experiment fails.

## What good looks like

- One authoritative pin per dependency; consumers inherit it, they don't re-declare it. Lockstep requirements (a dep that must match another dep's version) are enforced by the manifest, not by a human remembering.
- Load-bearing code depends on released, semver'd versions; unstable/git/pre-release deps are confined to clearly experimental, easily-removed surfaces.
- The known-good and fallback paths keep depending on what already works; only the new path takes on the new dependency's risk.
- The dependency decision is a two-way door, or there's an explicit reason why the one-way commitment is worth it and a stated way to exit.

## How to suggest fixes

Point at the commitment and contain it: "pin wgpu once in a workspace dependency and have both crates inherit it — don't let `29.0.3` and `\"29\"` drift," "keep the SHM fallback on stable iced; only the GPU path takes the git-master dep, so a no-Vulkan box still has a path on a released API," "if iced-master is required, isolate it behind the GPU feature and state the back-out: dropping the feature must not force the CPU path off its current iced," "this shared-crate major bump rewrites five consumers for one feature — scope it or stage it." One sentence per finding. If the unstable dep is genuinely unavoidable, say so and push the risk off the fallback at minimum.
