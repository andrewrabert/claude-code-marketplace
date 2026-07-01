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
- `verify` — no hook; stored only to be fanned out by `generate-workflow`.

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

`generate-workflow` — turn the verifiers into a fan-out review. Given a
required `mode`, it writes a Claude Code Workflow script (one agent per stored
verifier, each auditing the working tree read-only against that verifier's
text) and returns `{scriptPath, count, mode}`. Run it with the `Workflow` tool:
`Workflow({ scriptPath, args: { files } })` (`files` optionally narrows the
audit). The script lives only while the MCP server does. The CLI exposes the
full generator (other loop engines, all modes).

## CLI

Same store, outside the harness (`session` scope needs `--session <id>`):

```sh
handoff-verifier.py ls [--session ID]
handoff-verifier.py path  -s <scope>              # print the scope dir path
handoff-verifier.py add   -s <scope> (-m <mode> ... | -a) [-n NAME] [-f] [text]   # text from stdin if omitted; -n names the entry file, -f overwrites
handoff-verifier.py edit  -s <scope>              # open scope dir in $EDITOR
handoff-verifier.py clear -s <scope> (-m <mode> ... | -a) [--index N]
handoff-verifier.py generate-workflow [-l audit|fix|plan] [-m <mode>] [-n ROUNDS] [-o PATH]   # emit a Workflow script (stdout unless -o)
```

`hook` and `mcp` subcommands are invoked by `hooks.json` / `.mcp.json`, not by hand.
