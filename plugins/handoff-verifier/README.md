# handoff-verifier

Self-verification hooks you manage from inside the session through the mod's
own tools. Each verifier is a piece of text a hook injects (or a gate it
enforces) at a specific moment in the turn. Kept in the mod's `$.store`, not in
the repo.

## Modes

The moment a verifier fires:

- `submit` — injected when you submit a prompt (start of a turn).
- `stop` — fed back when a turn ends, forcing one more reasoning turn.
- `plan` — gates `ExitPlanMode` until you self-certify (see Gates).
- `ask` — gates `AskUserQuestion` the same way.
- `all` — merged into every mode above at runtime.

## Scopes

Where a verifier lives. The hooks concatenate active scopes broad→narrow:

- `global` — every project on this machine.
- `project` — this project root, across sessions (outside the repo; not shared).
- `session` — this session only (the default, zero blast radius).

## Gates (plan / ask)

A gate denies the tool call and shows its constraints plus a one-time token.
Once you've satisfied every constraint, call `confirm` with that token; it
unlocks exactly one retry of the gated tool. A stale or wrong token is rejected.

## Commands

- `/hv` — opens a pane listing every active verifier by its
  `scope/mode/index` address; it redraws as entries change. Esc closes it.
- `/hv-add [scope/]<mode> <text>` — append an entry; scope defaults to
  `session` (`/hv-add stop run the tests`, `/hv-add project/plan check scope`).
- `/hv-rm <scope>/<mode>/<index>` — remove the entry at an address `/hv` shows.

A change logs one dim transcript row and the pane is drawn outside the
conversation, so the model reads neither. A mistake (bad scope or mode, missing
text, no such entry) is answered as the command's text in the error colour;
the model reads that row.

## Tools

The tools Claude calls to manage verifiers, registered at session start:

`list` · `read` · `write` · `edit` · `remove` · `confirm` — entries are
addressed by `(scope, mode, index)`; indices renumber after a `remove`.

## Files

- `hooks/register.tsx` — the hooks module: hooks, gates, tools, commands.
- `tests/register.test.ts` — run with `claude plugin test <plugin dir>`.
