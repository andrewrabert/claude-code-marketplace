---
name: comments
description: Use before adding comments to code, or after writing/editing code that contains comments
---

# Comment Discipline

**Eliminate the comment by default. Keep one only when you can justify it as critical to the code as it stands right now — the one condition below. The code's history is inadmissible evidence: a keep-justification that reaches for the previous version, the bug you just fixed, or the change you just made is not a justification. When in doubt, cut it.**

## The One Condition

Add a comment only when it is *critical*: the *why* behind the code is non-obvious and unrecoverable from the code itself — a real gotcha that would cause a bug if missed. If it is merely helpful, nice-to-have, or you are unsure it clears the bar, eliminate it.

**The test: write the wrong edit as actual code — the specific line a competent reader would put here once the comment is gone. If you can only produce it by naming an identifier that doesn't already appear at this line (a function, a global, a path not in the surrounding code), then the comment warns against something the code doesn't contain — cut it. If you can't produce a wrong line at all, cut it.** "Would cause a bug if missed" is the falsifiable bar, not a vibe. The same bar applies to doc comments (`///`, `"""`, `/** */`) — they are not exempt.

The justification must be stated entirely in terms of the current code. You often arrive at a line having just changed it, so the history is vivid to you — the old bug, the subtle fix, the alternative you rejected. None of that is evidence. The next reader has only the code in front of them; a comment is critical only if *they* need it, and they never saw the version you're remembering. If the only defense you can mount for a comment involves what the code *was* — "this was broken before," "we used to do it the other way," "the fix here was subtle" — you have no defense. Cut it.

If a comment does not meet that bar, the code should carry the meaning instead. Don't write the comment.

```python
# Stripe caps line items at 250; extras are dropped without error
for window in chunked(charges, 250):
    ...

# Seed before spawning workers, or every worker draws the same sequence
random.seed(run_seed)
```

## Justifying a Structure Is Not a Gotcha

The seductive failure is the comment that rationalizes a design decision. It answers a "why," so it slips past a bar phrased loosely — but it describes *intent*, not a bug-causing fact. Delete it and no one writes wrong code. It fails the test.

```python
# Fails the bar — defends a design, names no bug
RETRY_LIMIT = 5  # defined once so callers stay aligned
DEFAULTS = {...}  # the canonical place for these
ROUTES = {...}  # grouped so they don't drift apart
session = build_session()  # assembled here for readability
```

**The tell:** if you're writing a sentence to defend why the comment earns its place, that defense is the signal to delete it.

## Reassurance Is Not a Gotcha

A comment that certifies the existing code is correct — *is sound, is safe, is fine, works, resolves at link time, this is OK because…* — guards nothing. It answers a "why" (why the code is acceptable), so it slips past a loose bar, but it warns against no edit: delete it and the identical code stays. This is the affirmative twin of the tombstone below, and it's the easiest mistake to make around FFI, concurrency, and linking — where the reader can't see the external invariant and you feel the urge to vouch for the code.

```python
# Fails the bar — vouches that the code works, names no breaking edit
# Decimal is thread-safe, so sharing this context across workers is sound
ctx = decimal.getcontext()

# Fails the bar — certifies the call resolves, warns against nothing
# requests bundles its own CA store, so this verifies fine without certifi
resp = session.get(url)
```

**The tell:** the comment is in the affirmative mood — it pronounces the code safe rather than warning that a change breaks it. **Beware the rescue reflex:** if the only way to keep the comment is to picture a reader who'd "fix" the code by introducing something not present at the line (a mutex, an explicit link attribute), you are manufacturing the alternative so you can defend against it. That is the same failure as inventing a wrong edit in the test above — cut it.

## A Dead Bug Is Not a Gotcha

A comment can name a *real* bug and still fail — when the bug belonged to the old code and the current code no longer has it. It reads as a warning but is really a tombstone: it narrates what *used to* break, or defends why the code *isn't* written some other way. The fix removed what it guarded.

**The tell:** the comment describes a past failure, or a race reachable only by undoing the current design. Once the design stopped being poor, the comment has nothing left to guard — cut it.

A comment phrased in the subjunctive — *would, otherwise, instead of, here … would race* — is almost always defending against an alternative the code doesn't contain. The reader can't write that alternative unless the comment teaches it to them first. That's the tell.

## Narrating the Change Is Not a Gotcha

A comment lives in the present tense of the code, and its audience is the next reader — who has only the code in front of them, not the version it replaced. The moment a comment explains why the code *changed* — what it used to do, what it now does *instead*, why the old way no longer works — it is narrating a transition. Transitions are events, and events belong in the commit that made them. Such a comment is a changelog entry welded to the source, where it rots undated and unauthored, a worse copy of the git log.

```python
# Fails the bar — explains the diff, not the code
# Read straight from the source now; we no longer go through the cache,
# instead of the adjusted value we used before
value = source.read()
```

**The tell:** temporal, backward-pointing framing — *no longer, used to, now, instead of, we switched to.* The reader can't see the prior state, so a sentence that only lands as a contrast against it is addressed to the wrong audience. **The test:** would this still make sense to someone who never saw the previous version? If it only makes sense as "here's what changed," it is rationale-for-a-change — put it in the commit message. A genuine standing fact survives only when stated as a property of the code as it is *now*, with no reference to what it replaced.

## After Writing or Editing Code

Review the comments you added or touched in this diff. For each, default to removing it; keep it only if you can state the wrong edit it prevents *in the code as it now stands*. You just made this change, so every keep-justification will be tempted toward the history — the bug you fixed, what the line used to say, why you rewrote it. Those defend the *diff*, and the diff already has a home: the commit message. If the comment can only be defended that way, remove it. Leave pre-existing comments on lines you didn't change.

## When the Bar Isn't Met, the Code Carries It

When tempted to explain *what* the code does, make the code self-explanatory instead:

- Rename a variable or function
- Extract a well-named helper
- Introduce a named constant for a magic value

```python
# Fails the bar — the comment restates the code
total -= refund  # subtract the refund

# Fails the bar — a label the code already shows
# Open the database connection
conn = sqlite3.connect(db_path)
```
