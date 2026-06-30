# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

| Plugin             | Description                                                                                                                                                                                                                                                                                                                                                                    |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `andrewrabert-dev` | Development conventions for Python, shell scripting, terminal UIs, and code comments, plus a design-architect agent that reviews and advises on code-organization quality: separation of concerns, leaky abstractions, RAII/lifecycle, interface design, change resilience, dependency strategy, delivery sequencing                                                           |
| `handoff-verifier` | Self-verification hooks managed by MCP tools: a Stop reminder that forces one more reasoning turn before a turn ends, plus ExitPlanMode and AskUserQuestion gates that block the tool until you self-certify the constraints are met via a token confirm. Each check is set per global, project, or session scope, and the hook concatenates the active scopes broad-to-narrow |
| `terse`            | Mirror of the global Stop-hook verifier: answer only what was asked, lead with the direct answer, drop all filler                                                                                                                                                                                                                                                              |

### andrewrabert-dev

| Skill                     | Description                                                                                                                                                                                                                                                                                                     |
|---------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `boundaries-and-coupling` | Use when reviewing a plan, diff, or existing code for separation of concerns, leaky abstractions, cohesion, coupling, dependency direction, layering violations, or Law of Demeter.                                                                                                                             |
| `change-resilience`       | Use when reviewing a plan, diff, or existing code for how well it absorbs change — DRY vs YAGNI balance, open/closed extension points, testability seams, and reversibility of decisions.                                                                                                                       |
| `comments`                | Use before adding comments to code, or after writing/editing code that contains comments                                                                                                                                                                                                                        |
| `delivery-sequencing`     | Use when reviewing a plan, diff, or existing code for the order it ships work in — de-risking the approach early vs merely doing the hardest part first, shipping a thin end-to-end validating slice, and not gating shippable wins behind unsolved problems.                                                   |
| `dependency-strategy`     | Use when reviewing a plan, diff, or existing code for how it depends on third-party code — version single-source-of-truth across the workspace, API stability of the chosen dep, blast radius on currently-working/fallback paths, and reversibility of the dependency choice.                                  |
| `design-audit`            | Use to apply ONE design lens (e.g. resource-lifecycle/RAII, boundaries-and-coupling) exhaustively across a whole codebase or large subtree — fan out one design-architect pass per module, then aggregate and dedup. For repo-wide structural audits too big for a single review.                               |
| `interface-design`        | Use when reviewing a plan, diff, or existing code for interface and API quality — least privilege, narrow surfaces, command/query separation, and error-handling strategy.                                                                                                                                      |
| `justfile`                | Use when creating or editing a justfile or `.just` file, or adding/changing recipes for the `just` task runner. Covers the conventions to follow - the first recipe is a private `list` that runs `just --list`, recipes are kebab-case and documented with a `#` comment, and multi-line bodies use a shebang. |
| `python`                  | Use when writing or editing Python scripts/code, or when file has python shebang or .py extension - uv script mode when deps needed, module-only imports, pathlib for paths, asyncio.subprocess for processes (user)                                                                                            |
| `python-tui`              | Use when building or editing terminal UIs (TUIs) in Python - Textual app with tabbed DataTables, filter-as-you-type, vim keys, rich-styled cells, async workers, modal detail screens, $EDITOR for multi-line text input                                                                                        |
| `resource-lifecycle`      | Use when reviewing a plan, diff, or existing code for resource management and state — RAII/ownership, cleanup tied to lifetime, single source of truth for state, and making invalid states unrepresentable.                                                                                                    |
| `shell`                   | Use when writing shell scripts - POSIX sh default, 4-space indent, set -eu, uppercase constants, printf over echo, explicit error handling (user)                                                                                                                                                               |

### handoff-verifier

_No skills._

### terse

| Skill   | Description                                                                                                                                                  |
|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `terse` | Restate your previous response per the terse rules — answer only what was asked, lead with the answer, telegraphic fragments, symbols over words, no filler. |

## Usage

```
/plugin marketplace add andrewrabert/claude-code-marketplace
/plugin install <plugin>@andrewrabert-marketplace
```
