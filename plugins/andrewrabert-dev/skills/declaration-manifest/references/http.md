# HTTP Declaration Manifest

A manifest for one change, stated as an equation: the set of HTTP endpoint declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- Both direction sections are always present. An empty `## Additions` section holds the phrase `No additions.` in place of endpoint sections. An empty `## Deletions` section holds the phrase `No deletions.`
- Constrained declaration kinds: endpoint, path parameter, query parameter, header, request body field. Behavior, response bodies, status codes, and implementation sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any surface beyond declarations.
- Begins with a title, `# Declaration Manifest: HTTP`, followed by the equation as one binding sentence.
- Each direction section holds one `### <METHOD> <path>` section per endpoint that holds a constrained declaration; each endpoint section holds one plain fenced block.
- The endpoint declaration is the first line of the endpoint's block: the endpoint's description. A section that only adds or deletes parameters on an existing endpoint has no description line.
- Parameters sit under a location label — `PATH:`, `QUERY:`, `HEADER:`, or `BODY (<media type>):` — one label per location the endpoint declares, in that order.
- A parameter line is `<name>: <type>  Description`. A required parameter appends `(required)` after the type; a path parameter is always required and omits the marker. A default appends `[default: <value>]`. An enum type is its values joined by `|`. A nested body field is dotted: `parent.child`.
- A new endpoint is its own section with its description line and every parameter it holds.
- A deleted endpoint mirrors a new endpoint: its own section with its description line and every parameter it held.

## Format

````markdown
# Declaration Manifest: HTTP
The set of endpoint, path parameter, query parameter, header, and
request body field declarations the resulting combined diff adds must
equal the declarations under `## Additions`, and the set it deletes
must equal the declarations under `## Deletions`.

## Additions

### <METHOD> <path>
```
<declarations>
```

## Deletions

### <METHOD> <path>
```
<declarations>
```
````

## Example

````markdown
# Declaration Manifest: HTTP
The set of endpoint, path parameter, query parameter, header, and
request body field declarations the resulting combined diff adds must
equal the declarations under `## Additions`, and the set it deletes
must equal the declarations under `## Deletions`.

## Additions

### POST /greetings
```
Create a greeting for one person.

HEADER:
  X-Request-Id: string  Idempotency key

BODY (application/json):
  name: string (required)  The person's name
  times: integer  Repeat the greeting [default: 1]
  style.color: auto|always|never  Colorize the greeting [default: auto]
```

### GET /greetings/{id}
```
QUERY:
  format: text|json  Response encoding [default: json]
```

## Deletions

### GET /greetings/{id}
```
QUERY:
  whisper: boolean  Return the greeting in lower case [default: false]
```
````

## Example: additions only

````markdown
# Declaration Manifest: HTTP
The set of endpoint, path parameter, query parameter, header, and
request body field declarations the resulting combined diff adds must
equal the declarations under `## Additions`, and the set it deletes
must equal the declarations under `## Deletions`.

## Additions

### GET /greetings/{id}
```
QUERY:
  format: text|json  Response encoding [default: json]
```

## Deletions

No deletions.
````
