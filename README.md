# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

| Plugin             | Description                                                                          |
|--------------------|--------------------------------------------------------------------------------------|
| `andrewrabert-dev` | Development conventions for Python, shell scripting, terminal UIs, and code comments |

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
