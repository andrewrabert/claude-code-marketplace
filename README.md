# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

| Plugin                       | Description                                                                                                                                                                                                                                                                                                                            |
|------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `andrewrabert-design-review` | Design-reviewer agent and language-agnostic code-organization review lenses: separation of concerns, leaky abstractions, RAII/lifecycle, interface design, change resilience, dependency strategy, delivery sequencing. Every finding is adversarially verified against the code by a per-finding verifier agent before it is returned |
| `andrewrabert-dev`           | Development conventions for Python, shell scripting, terminal UIs, and code comments                                                                                                                                                                                                                                                   |

### andrewrabert-design-review

| Skill                     | Description                                                                                                                                                                                                                                                                          |
|---------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `boundaries-and-coupling` | Use when reviewing an implementation plan, design doc, or proposed module structure for separation of concerns, leaky abstractions, cohesion, coupling, dependency direction, layering violations, or Law of Demeter.                                                                |
| `change-resilience`       | Use when reviewing an implementation plan or design doc for how well it absorbs change — DRY vs YAGNI balance, open/closed extension points, testability seams, and reversibility of decisions.                                                                                      |
| `delivery-sequencing`     | Use when reviewing an implementation plan or design doc for the order it ships work in — de-risking the approach early vs merely doing the hardest part first, shipping a thin end-to-end validating slice, and not gating shippable wins behind unsolved problems.                  |
| `dependency-strategy`     | Use when reviewing an implementation plan or design doc for how it depends on third-party code — version single-source-of-truth across the workspace, API stability of the chosen dep, blast radius on currently-working/fallback paths, and reversibility of the dependency choice. |
| `interface-design`        | Use when reviewing an implementation plan or design doc for interface and API quality — least privilege, narrow surfaces, command/query separation, and error-handling strategy.                                                                                                     |
| `resource-lifecycle`      | Use when reviewing an implementation plan or design doc for resource management and state — RAII/ownership, cleanup tied to lifetime, single source of truth for state, and making invalid states unrepresentable.                                                                   |

### andrewrabert-dev

| Skill        | Description                                                                                                                                                                                                                                                                                                     |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `comments`   | Use before adding comments to code, or after writing/editing code that contains comments                                                                                                                                                                                                                        |
| `justfile`   | Use when creating or editing a justfile or `.just` file, or adding/changing recipes for the `just` task runner. Covers the conventions to follow - the first recipe is a private `list` that runs `just --list`, recipes are kebab-case and documented with a `#` comment, and multi-line bodies use a shebang. |
| `python`     | Use when writing or editing Python scripts/code, or when file has python shebang or .py extension - uv script mode when deps needed, module-only imports, pathlib for paths, asyncio.subprocess for processes (user)                                                                                            |
| `python-tui` | Use when building or editing terminal UIs (TUIs) in Python - Textual app with tabbed DataTables, filter-as-you-type, vim keys, rich-styled cells, async workers, modal detail screens, $EDITOR for multi-line text input                                                                                        |
| `shell`      | Use when writing shell scripts - POSIX sh default, 4-space indent, set -eu, uppercase constants, printf over echo, explicit error handling (user)                                                                                                                                                               |

## Usage

```
/plugin marketplace add andrewrabert/claude-code-marketplace
/plugin install <plugin>@andrewrabert-marketplace
```
