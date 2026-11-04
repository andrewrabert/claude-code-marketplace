# jev

A Claude Code plugin that reviews code and text against my standards with jev: each file against the question sets whose `when` matches it: the text rules on every file, and the Rust, Python, sh and justfile standards on those files too.

## What it adds

- `jev:edit`: an edit agent. Its prompt's first line is exactly `{"scope": ["<absolute path>", ...]}`, then the edit instructions; the hook strips the line. After each write to any file, the hook runs `scripts/jev-scan.py --root <the scope directory holding it> --base HEAD --evaluate file` on it and attaches the findings to the tool result.
- `jev:audit`: reviews code with the `scan` tool and reports the jev findings it verifies. Its prompt is exactly `{"path": "<absolute path>", "base": "<git revision>", "scope": ["<absolute path>", ...]}`, base optional, path inside a scope directory; the hook refuses any other prompt and runs the scan with these values, rooted at the deepest scope directory holding path.
- `mcp__jev__scan`: runs `scripts/jev-scan.py` on `root`, or on a file or directory `path` relative to it, or on the hunks changed since `base`. One scan per agent.
- `mcp__jev__bash`, `mcp__jev__read`, `mcp__jev__write`, `mcp__jev__edit`: each call runs `scripts/jev-bash.py` once in a bashkit sandbox that mounts the calling agent's `scope` read-write at its host paths, and the agent's own `claude-code-jev.XXXXXX` temp directory, made at spawn and removed when the session ends, at `/tmp`; everything else is in memory and gone after the call. The hook records each jev agent's `scope` at spawn and refuses calls from any agent without one. `jev:edit` has all four; `jev:audit` only `read`.

## Layout

- `hooks/register.ts`: the edit review, the `scan` tool, the jev agents' prompt checks, and the sandbox tools.
- `agents/`: `edit.md`, `audit.md`.
- `scripts/jev-scan.py`: the scanner, also usable on its own.
- `scripts/jev-bash.py`: runs one sandbox tool call: `--root <dir>`... `--tmp <dir>` `<tool>`, the arguments as JSON on stdin.
- `scripts/jev-ask.py`: asks TypeSafe's Jev a question set about stdin through `typesafe-sdk`.
- `questions/`: the question sets, every `*.yaml` at any depth; `jev-scan.py --config DIR` reads another directory of them instead. A set says what it covers under `description:`, holds its questions under `questions:`, picks its files under `when:`, and says which answers are findings under `decision:`:

  ```yaml
  description: POSIX sh standards that need judgment.
  when:
    language: [sh]       # the file's detected language: rust, python, sh, just or markdown
    pattern: [".envrc"]  # gitignore(5) patterns, matched against the path from --root
  decision:
    threshold: 0.75      # an answer at or above this is a finding; default 0.75
    gate: 0.5            # default 0.5
    gates:               # a question is suppressed when all its gate questions are at or above `gate`
      silent-failure: [absence-expected]
  questions:
    bashism: ...
  ```

  A file matches when either key matches. A set without `when` (`prose.yaml`) reviews only what `--set` gives it. A file's sets apply in path order, and a question two sets both ask is reported once, from the first.
  - Languages are detected in `scripts/jev-scan.py`: `rust` is `*.rs`; `python` is `*.py` or a shebang running `python`, a versioned `python3.x` or `uv run`; `sh` is a shebang running `sh`; `just` is `justfile`, `Justfile`, `.justfile` or `*.just`; `markdown` is `*.md`.
- `calibration/standards/`: 139 labeled code cases; `run.py --variants … [--from results.json]` scores a question set.
- `calibration/surface/`: labeled surface findings from jellium-desktop `menu-refactor`, and `surface.yaml`, the surface spec questions they were tuned on. Nothing runs them; `jev-scan.py` no longer reviews surface specs.
- `calibration/history/`: earlier question sets that `run.py` compares against.

## Requirements

- `TYPESAFE_API_KEY` in the environment, or in the dotenv file `TYPESAFE_ENV_FILE` names. `TYPESAFE_DEFAULT_MODEL` and `TYPESAFE_BASE_URL` override the model and API root, read the same way.
- `uv` and `git`.

## Use

```
scripts/jev-scan.py --base main                    # the repository holding the current directory
scripts/jev-scan.py -- src/main.rs docs           # paths relative to that repository's top
scripts/jev-scan.py --root ~/notes -- a/b.md      # outside git, or any other root
```
