# CLI Declaration Manifest

A manifest for one change, stated as an equation: the set of CLI declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- A direction with no declarations gets no section; an absent section means the empty set.
- Constrained declaration kinds: subcommand, flag, option, positional argument. A flag takes no value; an option takes a value. Behavior, output, exit codes, and implementation sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any surface beyond declarations.
- Begins with a title, `# Declaration Manifest: CLI`, followed by the equation as one binding sentence.
- Each direction section holds one `### <full command>` section per command that holds a constrained declaration; each command section holds one plain fenced block.
- Declaration lines use the CLI Interface Specification formats: a flag is `--shout  Help text`, an option is `--times <N>  Help text`, a positional is `NAME  Help text`, and a subcommand is a line under `COMMAND:` in the parent command's block.
- A new command is two declarations: its line under `COMMAND:` in the parent's section, and its own section with every flag, option, and positional it holds. The root command has no parent line.
- A deleted command mirrors a new command: its line under `COMMAND:` in the parent's section, and its own section with every declaration it held.

## Format

````markdown
# Declaration Manifest: CLI
The set of subcommand, flag, option, and positional argument declarations
the resulting combined diff adds must equal the declarations under
`## Additions`, and the set it deletes must equal the declarations under
`## Deletions`.

## Additions

### <full command>
```
<declarations>
```

## Deletions

### <full command>
```
<declarations>
```
````

## Example

````markdown
# Declaration Manifest: CLI
The set of subcommand, flag, option, and positional argument declarations
the resulting combined diff adds must equal the declarations under
`## Additions`, and the set it deletes must equal the declarations under
`## Deletions`.

## Additions

### `greet`
```
COMMAND:
  bye  Say goodbye to one person
```

### `greet bye`
```
--times <N>  Repeat the goodbye [default: 1]
--wave       Add a wave emoji

NAME  The person's name
```

### `greet hello`
```
--color <WHEN>  Colorize the greeting [default: auto]
```

## Deletions

### `greet hello`
```
--whisper  Print the greeting in lower case
```
````

