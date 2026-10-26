# jev

A Claude Code plugin that reviews Rust code and Rust surface specs against my standards with jev.

## What it adds

- `jev:edit`: an edit agent. After each write to a `.rs` or `.md` file, the hook asks jev about the change and attaches the findings to the tool result.
- `jev:audit`: reviews code with the `scan` tool and reports the jev findings it verifies. Its prompt is exactly `{"path": "<absolute path>", "base": "<git revision>"}`, base optional; the hook refuses any other prompt and runs the scan with these values.
- `mcp__jev__scan`: runs `scripts/jev-scan` on a file or directory, or on the hunks changed since `base`. One scan per agent.

## Layout

- `hooks/register.ts`: the edit review, the `scan` tool, and the `jev:audit` prompt check.
- `agents/`: `edit.md`, `audit.md`.
- `scripts/jev-scan`: the scanner, also usable on its own.
- `scripts/standards.yaml`, `scripts/surface.yaml`, `scripts/prose.yaml`: the question sets, each with a `.gates.json` holding its threshold and gates where it has one.
- `calibration/standards/`: 139 labeled code cases; `run.py --variants … [--from results.json]` scores a question set.
- `calibration/surface/`: labeled surface findings from jellium-desktop `menu-refactor`.
- `calibration/history/`: earlier question sets that `run.py` compares against.

## Requirements

- `jev` from [jevkit](https://github.com/jonathanavis96/jev-kit) on `PATH`, with auth it resolves: `TYPESAFE_API_KEY` in the environment or `jev auth login`.
- `uv` and `git`.
- `surface-spec` for surface specs.

## Use

```
scripts/jev-scan --base main /path/to/repo
surface-spec --git main -l rust -e '*test*' | scripts/jev-scan --spec - --description "<what the change is for>"
```
