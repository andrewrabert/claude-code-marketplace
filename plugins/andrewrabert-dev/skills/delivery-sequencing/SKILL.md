---
name: delivery-sequencing
description: Use when reviewing a plan, diff, or existing code for the order it ships work in — de-risking the approach early vs merely doing the hardest part first, shipping a thin end-to-end validating slice, and not gating shippable wins behind unsolved problems.
---

# Delivery Sequencing

**The order work ships in — across a plan, a stack of diffs, or a migration through existing code — is a design decision, not a schedule detail. Stage ordering decides what gets validated first, what unknown blocks what, and how much is built before the approach is proven. A rollout can have every component right and still sequence them so the risky unknown sits in front of everything else.** Judge what each stage de-risks and what it blocks, not just whether the stages are individually correct.

## What to check

- **De-risk first vs hard-first** — is the unproven part tackled early *to validate the whole approach*, or does the work just do the *hardest* sub-problem first and call that de-risking? Those aren't the same. Attacking the hardest piece first only helps when that piece is what proves the approach works; if it's an isolated hard problem the rest doesn't depend on, doing it first just delays every shippable result behind it. Ask: does finishing this stage *prove the mechanism*, or only clear one hard obstacle?
- **Thin validating slice first** — is there a smallest end-to-end slice that exercises the whole new mechanism on the *easy* case, shipped before the gnarly variant? Proving the mechanism end-to-end on the clean path (the own-window / single-owner / happy case) retires the central risk cheaply; the hard variant then rides proven rails. Going wide on the hard case before the mechanism is proven anywhere risks discovering the approach is wrong after the most expensive work.
- **Don't gate shippable wins behind unsolved problems** — if a later stage is clean, independent, and shippable on its own, it should not sit *behind* an earlier stage that's admittedly underspecified or unsolved. Flag ordering that couples a ready win to a hard unknown: the win can't ship until the unknown resolves, for no structural reason.
- **Stated independence matches the order** — when the work says a stage "ships independently after" another, the ordering should reflect that. Calling Stage 2 independent yet sequencing the risky, entangled Stage 1 first contradicts that claim — if Stage 2 is truly independent, it's a candidate to go *first* and prove the approach.
- **Failure isolation across stages** — if an early stage stalls (the unsolved bit stays unsolved), how much downstream work is blocked? Sequencing should minimize how much is stranded behind the riskiest unknown.

## Tells

- "Tackle the gnarly bit first" / "hardest part first" framed as de-risking, when that part is an isolated obstacle the rest doesn't need.
- The unsolved / underspecified / "this is the hard part" stage placed *before* a clean, self-contained stage.
- A stage described as "ships independently" but ordered after a dependent-looking risky one.
- The thin end-to-end proof of the new mechanism happening only on the hardest case, with no earlier happy-path validation.
- A single hard unknown sitting upstream of most of the deliverable value.

## What good looks like

- The first stage shipped is the smallest slice that proves the whole approach end-to-end, usually on the easy/clean case.
- The hardest unsolved problem is sequenced so that, if it stalls, the least possible shippable work is stranded behind it.
- Independent stages are ordered to ship value early; nothing clean waits on something gnarly without a structural reason.
- Each stage's purpose is stated as what it *proves* or *unblocks*, not just what it builds.

## How to suggest fixes

Re-order toward earliest validation and least blocking: "ship the X11 own-window GPU menu first — it proves the whole present-into-swapchain mechanism on the clean single-owner case; tackle the Wayland re-role second on proven rails," "the Wayland surface-ownership unknown is both hard and unsolved — don't put it in front of a stage that's ready to ship," "you call Stage 2 independent — then lead with it and let it validate the approach before the gnarly Stage 1." One sentence per finding. If the hard part genuinely must go first (a true blocking dependency), say so and name why the ordering is forced rather than chosen.
