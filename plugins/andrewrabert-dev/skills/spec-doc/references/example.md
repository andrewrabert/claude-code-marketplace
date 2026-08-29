# Worked example

A complete spec for a small CLI, short enough to read whole. Read it once, then
read "What to notice" at the end.

The tool is fictional. Every value is neutral.

---

````markdown
# tally

**Version 1.0**

`tally` is a command-line program over a set of named counters. Each counter
holds a non-negative integer and a last-changed instant.

This document specifies the command-line surface: the commands, their
arguments, where settings come from, and what the program writes to its output
streams. It specifies observable behavior only.

The keywords MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be read as
described in RFC 2119.

## 1. Scope

### Goals

1. Define every command a caller may invoke, and every argument each accepts.
2. Define how a setting resolves when more than one source supplies it.
3. State the conditions a script may rely on.

### Non-goals

- The storage format of the counter set.
- Behavior when two processes write one counter at the same time. See §7.
- Exit codes beyond success and failure.
- Any surface other than the command line.

## 2. Terminology

- **Counter**: One named non-negative integer, with the instant it last
  changed.
- **Name**: The string that addresses a counter. See §3.
- **Set**: The collection of counters one invocation operates on.
- **Setting**: A named value the program reads from a flag or the environment.

## 3. Names

A name MUST begin with a letter. It MUST contain only letters, digits, `-`, and
`_`. It MUST be between 1 and 64 characters.

A name that fails any rule is refused. The program MUST NOT create a counter as
a side effect of a refused name.

Names are case-sensitive. `Visits` and `visits` are two counters.

## 4. Commands

`tally` with no command prints the command listing on stdout and succeeds.

Every command writes its result to stdout and its diagnostics to stderr. A
failure writes one line to stderr in the form `error: <message>`, and the
program fails.

| Command | Arguments | Result on stdout |
|---|---|---|
| `inc NAME` | `--by <N>` | The counter's new value |
| `get NAME` | — | The counter's value |
| `list` | `--sort <ORDER>`, `--json` | One counter per line |
| `reset NAME` | `--all` | Nothing |

### 4.1 inc

Adds to a counter. A counter that does not exist is created at `0` before the
addition.

`--by` takes an integer. Absent `--by` ⇒ `1`. A negative value is accepted, and
is refused when it would take the counter below `0`. A `--by` of `0` is
accepted, and updates the last-changed instant.

### 4.2 get

Writes the counter's value. A name that does not exist is refused.

### 4.3 list

Writes one line per counter, as `<name> <value>`.

`--sort` is `name` (default, case-sensitive) or `changed` (most recently changed
first). Two counters with the same instant MAY appear in either order. A caller
MUST NOT depend on which.

`--json` writes an array instead, one object per counter, with the members
`name`, `value`, and `changed`. `changed` is an ISO 8601 datetime with an
explicit UTC offset.

An empty set writes nothing, and succeeds. Under `--json` it writes `[]`.

### 4.4 reset

Removes a counter. `--all` removes every counter, and takes no name. Passing
both a name and `--all` is refused.

A name that does not exist is refused. `--all` on an empty set succeeds.

## 5. Settings

A setting resolves from two layers. The nearer layer wins:

1. Command-line flags.
2. The process environment.

| Variable | Flag | Default | Meaning |
|---|---|---|---|
| `TALLY_DIR` | `--dir` | `~/.local/share/tally` | Where the set is held. |
| `TALLY_FORMAT` | `--json` | *(lines)* | Output shape for `list`. |

A relative `TALLY_DIR` resolves against the working directory.

A directory that does not exist is created on the first write. A directory that
exists and cannot be read stops the program before any command runs.

## 6. Guarantees

A caller MAY rely on all of the following.

1. **A refused command changes nothing.** A command that fails leaves every
   counter at the value it held before.
2. **A read observes the last write.** A `get` after an `inc` in the same
   process, or in a later one, observes the incremented value.
3. **A counter is never negative.** No sequence of commands produces a value
   below `0`.
4. **The set is the only state.** Every counter is held in the directory
   `TALLY_DIR` names. No other location holds anything a command returns.

## 7. Conformance

An implementation conforms to this document if:

1. It accepts every command in §4 with the arguments listed there.
2. It refuses every name that fails §3.
3. It resolves settings by §5, in that layer order.
4. It holds every guarantee in §6.

An implementation MAY:

- Accept further commands and further arguments.
- Change the wording of any message, unless this document quotes it.
- Choose any order for counters this document leaves unordered.

An implementation MUST NOT:

- Change the meaning of a listed argument.
- Change a listed default.
- Remove a listed argument.

## 8. Deferred

The following are intentionally left to a later revision:

- Concurrent writers, and what a caller may assume when two run at once.
- Exit codes beyond success and failure.
- A counter type other than a non-negative integer.
- Removing a counter as a recoverable operation.
````

---

## What to notice

**The Non-goals do work.** "Behavior when two processes write one counter at the
same time" is listed, and §7 never discusses locking. Without that line, a
reader assumes the silence is an oversight. With it, the silence is a decision.

**Every default is in a table.** `--by`, `--sort`, `TALLY_DIR`. None of them
appear only in prose.

**Every absence is stated.** "Absent `--by` ⇒ `1`." "An empty set writes nothing,
and succeeds." "Under `--json` it writes `[]`." A reader never guesses.

**A MAY carries its matching prohibition.** §4.3 says two counters with the same
instant MAY appear in either order, and then says a caller MUST NOT depend on it.
The second half is what makes the first half safe.

**The guarantees cross sections.** "A refused command changes nothing" is not a
fact about `inc`, `get`, `list`, or `reset`. It is the promise that holds across
all four, which is why it cannot live in any one of them.

**No mechanism appears.** The document never says how the set is stored, how a
write is made whole, or how a refusal rolls back. §6.1 promises the outcome, and
leaves the implementer every way of reaching it.

**Deferred is not empty.** Four gaps, each one a question a reader would
otherwise hunt for.

**The edge cases are specified, not implied.** A `--by` of `0`. `--all` on an
empty set. Both a name and `--all`. Each of these is one sentence, and each is a
place two implementations would otherwise diverge.
