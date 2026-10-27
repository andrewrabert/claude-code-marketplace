# jev

A Claude Code plugin that reviews code, text and Rust surface specs against my standards with jev: the text rules on every file, and the Rust standards on Rust too.

## What it adds

- `jev:edit`: an edit agent. Its prompt's first line is exactly `{"scope": ["<absolute path>", ...]}`, then the edit instructions; the hook strips the line. After each write to any file, the hook asks jev about the change and attaches the findings to the tool result.
- `jev:audit`: reviews code with the `scan` tool and reports the jev findings it verifies. Its prompt is exactly `{"path": "<absolute path>", "base": "<git revision>", "scope": ["<absolute path>", ...]}`, base optional; the hook refuses any other prompt and runs the scan with these values.
- `mcp__jev__scan`: runs `scripts/jev-scan.py` on a file or directory, or on the hunks changed since `base`. One scan per agent.
- `mcp__jev__bash`, `mcp__jev__read`, `mcp__jev__write`, `mcp__jev__edit`: each call runs `scripts/jev-bash.py` once in a bashkit sandbox that mounts the calling agent's `scope` read-write at its host paths, and the agent's own `claude-code-jev.XXXXXX` temp directory, made at spawn and removed when the session ends, at `/tmp`; everything else is in memory and gone after the call. The hook records each jev agent's `scope` at spawn and refuses calls from any agent without one. `jev:edit` has all four; `jev:audit` only `read`.

## Layout

- `hooks/register.ts`: the edit review, the `scan` tool, the jev agents' prompt checks, and the sandbox tools.
- `agents/`: `edit.md`, `audit.md`.
- `scripts/jev-scan.py`: the scanner, also usable on its own.
- `scripts/jev-bash.py`: runs one sandbox tool call: `--root <dir>`... `--tmp <dir>` `<tool>`, the arguments as JSON on stdin.
- `scripts/jev-ask.py`: asks TypeSafe's Jev a question set about stdin through `typesafe-sdk`.
- `scripts/text.yaml` (every file), `scripts/standards.yaml` (Rust), `scripts/surface.yaml` (surface specs): the question sets, each with a `.gates.json` holding its threshold and gates where it has one; without one, a set flags at 0.75.
- `calibration/standards/`: 139 labeled code cases; `run.py --variants … [--from results.json]` scores a question set.
- `calibration/surface/`: labeled surface findings from jellium-desktop `menu-refactor`.
- `calibration/history/`: earlier question sets that `run.py` compares against.

## Requirements

- `TYPESAFE_API_KEY` in the environment, or in the dotenv file `TYPESAFE_ENV_FILE` names. `TYPESAFE_DEFAULT_MODEL` and `TYPESAFE_BASE_URL` override the model and API root, read the same way.
- `uv` and `git`.
- `surface-spec` for surface specs.

## Use

```
scripts/jev-scan.py --base main /path/to/repo
surface-spec --git main -l rust -e '*test*' | scripts/jev-scan.py --spec - --description "<what the change is for>"
```
