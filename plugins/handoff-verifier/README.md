# handoff-verifier

Self-verification hooks you manage from inside the session via MCP tools. Each
verifier is a piece of text the hook injects (or a gate it enforces) at a
specific moment in the turn. Stored on disk, not in the repo.

## Modes

The moment a verifier fires:

- `submit` — injected when you submit a prompt (start of a turn).
- `stop` — fed back when a turn ends, forcing one more reasoning turn.
- `plan` — gates `ExitPlanMode` until you self-certify (see Gates).
- `ask` — gates `AskUserQuestion` the same way.

## Scopes

Where a verifier lives. The hook concatenates active scopes broad→narrow:

- `global` — every project on this machine.
- `project` — this project, across sessions (stored outside the repo; not shared).
- `session` — this session only (the default, zero blast radius).

## Gates (plan / ask)

A gate denies the tool call and shows its constraints plus a one-time token.
Once you've satisfied every constraint, call `confirm` with that token; it
unlocks exactly one retry of the gated tool. A stale or wrong token is rejected.

## MCP tools

`list` · `read` · `write` · `edit` · `remove` · `confirm` — entries are
addressed by `(scope, mode, index)`; indices renumber after a `remove`.

## CLI

Same store, outside the harness (`session` scope needs `--session <id>`):

```sh
handoff-verifier.py ls [--session ID]
handoff-verifier.py path  -s <scope>              # print the scope dir path
handoff-verifier.py add   -s <scope> <mode> [text]   # text from stdin if omitted
handoff-verifier.py edit  -s <scope>              # open scope dir in $EDITOR
handoff-verifier.py clear -s <scope> <mode> [--index N]
```

`hook` and `mcp` subcommands are invoked by `hooks.json` / `.mcp.json`, not by hand.
