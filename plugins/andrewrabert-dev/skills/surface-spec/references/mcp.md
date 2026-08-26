# MCP Surface Spec

A surface spec for one change, stated as an equation: the set of MCP tool declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- Both direction sections are always present. An empty `## Additions` section holds the phrase `No additions.` in place of tool sections. An empty `## Deletions` section holds the phrase `No deletions.`
- Constrained declaration kinds: tool, tool argument. Behavior, result content, error text, and implementation sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any surface beyond declarations.
- Begins with a title, `# Surface Spec: MCP`, followed by the equation as one binding sentence.
- Each direction section holds one `### <tool name>` section per tool that holds a constrained declaration; each tool section holds one plain fenced block.
- The tool declaration is the first line of the tool's block: the tool's description. A section that only adds or deletes arguments to an existing tool has no description line.
- An argument line is `<name>: <type>  Description`, in input-schema order. A required argument appends `(required)` after the type. A schema default appends `[default: <value>]`. An enum type is its values joined by `|`.
- A new tool is its own section with its description line and every argument it holds.
- A deleted tool mirrors a new tool: its own section with its description line and every argument it held.

## Format

````markdown
# Surface Spec: MCP
The set of tool and tool argument declarations the resulting combined
diff adds must equal the declarations under `## Additions`, and the set
it deletes must equal the declarations under `## Deletions`.

## Additions

### <tool name>
```
<declarations>
```

## Deletions

### <tool name>
```
<declarations>
```
````

## Example

````markdown
# Surface Spec: MCP
The set of tool and tool argument declarations the resulting combined
diff adds must equal the declarations under `## Additions`, and the set
it deletes must equal the declarations under `## Deletions`.

## Additions

### SayBye
```
Say goodbye to one person.

name: string (required)  The person's name
times: integer  Repeat the goodbye [default: 1]
wave: boolean  Add a wave emoji [default: false]
```

### SayHello
```
color: auto|always|never  Colorize the greeting [default: auto]
```

## Deletions

### SayHello
```
whisper: boolean  Print the greeting in lower case [default: false]
```
````

## Example: additions only

````markdown
# Surface Spec: MCP
The set of tool and tool argument declarations the resulting combined
diff adds must equal the declarations under `## Additions`, and the set
it deletes must equal the declarations under `## Deletions`.

## Additions

### SayHello
```
color: auto|always|never  Colorize the greeting [default: auto]
```

## Deletions

No deletions.
````
