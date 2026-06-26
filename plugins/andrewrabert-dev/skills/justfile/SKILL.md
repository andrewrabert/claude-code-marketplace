---
name: justfile
description: Use when creating or editing a justfile or `.just` file, or adding/changing recipes for the `just` task runner. Covers the conventions to follow - the first recipe is a private `list` that runs `just --list`, recipes are kebab-case and documented with a `#` comment, and multi-line bodies use a shebang.
---

# Justfile Preferences

**Project conventions take precedence unless the user says otherwise.** If a
justfile already does something a different way consistently, match it rather
than imposing these defaults.

## The first recipe lists the others

Running bare `just` runs the *first* recipe in the file. That's almost never
what you want as a side effect, so make the first recipe a harmless one that
just prints the menu of available recipes:

```just
[private]
list:
    @just --list
```

- The name is cosmetic — `just` picks the first recipe regardless of what it's
  called — so `list` is used because it reads well and says what it does.
- `[private]` keeps it out of its own `just --list` output, where it would
  otherwise be noise.
- `@` suppresses echoing the `just --list` command itself, so you see only the
  menu.

If recipes share setup (e.g. a `setup` recipe that installs a git hook), the
listing recipe can depend on it too, so even a bare `just` keeps the
environment in order:

```just
[private]
list: setup
    @just --list
```

## Document recipes with a comment

A `#` comment on the line directly above a recipe becomes its description in
`just --list`. This is the menu users actually read, so write the comment for
them — say what the recipe accomplishes, not how. Document every public recipe
that isn't self-evident from its name.

```just
# Run the test suite
test:
    pytest

# Build the release artifacts
build:
    ...
```

## Recipe style

- **kebab-case names**: `new-plugin`, `check-plugin`.
- **`@` to suppress echo** when the command's *output* is the point and seeing
  the command itself would be clutter (listings, generators, anything whose
  result is what matters).
- **Variadic parameters with `*`**: `check-plugin *names:` accepts zero or more
  arguments, so the recipe works whether the user passes targets or not.
- **`{{justfile_directory()}}` for paths**, never a hardcoded path or an
  assumption about the caller's working directory. Recipes get run from
  anywhere, and `just` does not cd into the justfile's directory for you.

## Wrapper recipes: forward all args to a command

This is **the** way to forward all arguments to a wrapped command — always use
it. Other approaches (`{{args}}`, bare `$@`) may look like they work in casual
testing but silently mangle whitespace and quoting. Pair a variadic `*args`
with `[positional-arguments]` and `"$@"`:

```just
# Run the CLI
[positional-arguments]
run *args:
    @uv run my-cli "$@"
```

`[positional-arguments]` exposes the args as shell positionals so `"$@"`
forwards each as a distinct, quote-preserving argument. Both are required:
`"$@"` without the setting expands to nothing, and the setting without `"$@"`
forwards nothing. Don't use `{{args}}` — it joins the args into one string the
shell re-splits on whitespace, mangling quoted/spaced args.

Set `[positional-arguments]` as a per-recipe attribute (as above), not globally
with `set positional-arguments`, so it only affects the recipes that need it.

## Surface recipes in the project README

When a project has a justfile, give its main `README.md` a `## Development`
section that points at `just` and pastes the current `just --list` output, so
contributors see the available recipes without cloning and running it:

````markdown
## Development

This project uses [just](https://github.com/casey/just) as a command runner.

```
Available recipes:
    [test]
    test          # Run tests

    [lint]
    lint          # Lint workspace

    [run]
    run *args     # Run the app
```
````

This is the expected shape: the `## Development` heading, the one-line
[just](https://github.com/casey/just) pointer, then a fenced block with the
literal `just --list` output — grouped via `[group('...')]` attributes. Paste
the real output rather than hand-writing it, and refresh it when recipes change
so it never drifts.

Every command in the README must run through a `just` recipe — show `just
test`, `just build`, etc., never the raw underlying command. If a documented
step has no recipe yet, add one and reference that; don't document a bare
command.

## Multi-line recipes

Each line of a normal recipe runs in its *own* shell, so variables and `cd`
don't carry from one line to the next. When the body needs shared state, make
it a shebang recipe — the whole body then runs as one script:

```just
setup:
    #!/bin/sh
    set -eu
    hook="{{justfile_directory()}}/.git/hooks/pre-commit"
    [ -f "${hook}" ] && exit 0
    cp "{{justfile_directory()}}/dev/pre-commit" "${hook}"
```

Start shebang bodies with `set -eu` (for `sh`/`bash`) so a failed command
aborts the recipe instead of silently continuing. For a couple of dependent
commands that don't justify a shebang, chain them on one line with `\`
continuations and `;`.

## Common mistakes

- A real task as the first recipe — bare `just` then runs it unintentionally.
  The first recipe should be the `list` recipe.
- Forgetting `[private]` on the listing recipe, so it clutters `--list`.
- Multi-line shell logic without a shebang, expecting variables or `cd` to
  persist between lines.
- Hardcoding paths or assuming the working directory instead of using
  `{{justfile_directory()}}`.
- Forwarding args to a wrapped command with `{{args}}` instead of
  `[positional-arguments]` + `"$@"` — quoted/whitespace args get re-split and
  mangled.
