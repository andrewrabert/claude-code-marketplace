# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

| Plugin             | Description                                                                                                                                                                                                                                                                                                                                                                    |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `andrewrabert-dev` | Development conventions for Python, shell scripting, terminal UIs, and code comments, plus a design-architect agent that reviews and advises on code-organization quality: separation of concerns, leaky abstractions, RAII/lifecycle, interface design, change resilience, dependency strategy, delivery sequencing                                                           |
| `handoff-verifier` | Self-verification hooks managed by MCP tools: a Stop reminder that forces one more reasoning turn before a turn ends, plus ExitPlanMode and AskUserQuestion gates that block the tool until you self-certify the constraints are met via a token confirm. Each check is set per global, project, or session scope, and the hook concatenates the active scopes broad-to-narrow |
| `noted`            | noted - https://github.com/andrewrabert/noted                                                                                                                                                                                                                                                                                                                                  |
| `session-findings` | Mine Claude Code session transcripts into self-contained per-session findings notes (bugs, development friction, reusable learnings) via a deterministic digest pass plus model classification; includes the digest/render scripts and a resumable sweep harness that writes findings.json and findings.md keyed by deterministic session id                                   |
| `terse`            | Mirror of the global Stop-hook verifier: answer only what was asked, lead with the direct answer, drop all filler                                                                                                                                                                                                                                                              |

### andrewrabert-dev

| Skill        | Description                                                                                                                                                                                                                                                                                                     |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `comments`   | Use before adding comments to code, or after writing/editing code that contains comments                                                                                                                                                                                                                        |
| `justfile`   | Use when creating or editing a justfile or `.just` file, or adding/changing recipes for the `just` task runner. Covers the conventions to follow - the first recipe is a private `list` that runs `just --list`, recipes are kebab-case and documented with a `#` comment, and multi-line bodies use a shebang. |
| `python`     | Use when writing or editing Python scripts/code, or when file has python shebang or .py extension - uv script mode when deps needed, module-only imports, pathlib for paths, asyncio.subprocess for processes (user)                                                                                            |
| `python-tui` | Use when building or editing terminal UIs (TUIs) in Python - Textual app with tabbed DataTables, filter-as-you-type, vim keys, rich-styled cells, async workers, modal detail screens, $EDITOR for multi-line text input                                                                                        |
| `shell`      | Use when writing shell scripts - POSIX sh default, 4-space indent, set -eu, uppercase constants, printf over echo, explicit error handling (user)                                                                                                                                                               |

### handoff-verifier

_No skills._

### noted

| Skill   | Description                                                                                                                                                                                                              |
|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `log`   | Use when explicitly asked to journal or log the conversation (e.g. /log) — capture an immutable, timestamped entry via the noted MCP LogNote tool.                                                                       |
| `plan`  | Use when explicitly asked to plan a task into notes (e.g. /plan) — work a task through read-only explore → design → review, then persist the plan as a noted note under dev/plans/ and open a noted task referencing it. |

### session-findings

| Skill              | Description                                                                                                                                                                                                                                                                                                     |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze-sessions` | Use when analyzing Claude Code session history to learn what bugs were fixed, where development got stuck, or what lessons recur — mines transcripts into self-contained per-session findings notes (bugs, friction, learnings) and supports a resumable multi-session sweep whose learnings can feed verifiers |

### terse

| Skill   | Description                                                                                                                                                  |
|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `terse` | Restate your previous response per the terse rules — answer only what was asked, lead with the answer, telegraphic fragments, symbols over words, no filler. |

## Usage

```
/plugin marketplace add andrewrabert/claude-code-marketplace
/plugin install <plugin>@andrewrabert-marketplace
```
