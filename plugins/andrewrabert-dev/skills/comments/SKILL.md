---
name: comments
description: Use before adding comments to code, or after writing/editing code that contains comments
---

# Comment Discipline

**Code is self-explanatory by default. Write no comment unless the one condition below holds.**

## The One Condition

Add a comment only when the *why* behind the code is non-obvious and unrecoverable from the code itself — a real gotcha that would cause a bug if missed.

**The test: write the wrong edit as actual code — the specific line a competent reader would put here once the comment is gone. If you can only produce it by naming an identifier that doesn't already appear at this line (a function, a global, a path not in the surrounding code), then the comment warns against something the code doesn't contain — cut it. If you can't produce a wrong line at all, cut it.** "Would cause a bug if missed" is the falsifiable bar, not a vibe. The same bar applies to doc comments (`///`, `"""`, `/** */`) — they are not exempt.

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

## A Dead Bug Is Not a Gotcha

A comment can name a *real* bug and still fail — when the bug belonged to the old code and the current code no longer has it. It reads as a warning but is really a tombstone: it narrates what *used to* break, or defends why the code *isn't* written some other way. The fix removed what it guarded.

**The tell:** the comment describes a past failure, or a race reachable only by undoing the current design. Once the design stopped being poor, the comment has nothing left to guard — cut it.

A comment phrased in the subjunctive — *would, otherwise, instead of, here … would race* — is almost always defending against an alternative the code doesn't contain. The reader can't write that alternative unless the comment teaches it to them first. That's the tell.

## After Writing or Editing Code

Review the comments you added or touched in this diff. For each, confirm it meets the one condition. If it doesn't, remove it and let the code carry the meaning. Leave pre-existing comments on lines you didn't change.

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
