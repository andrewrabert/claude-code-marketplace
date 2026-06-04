# Claude Marketplace Repository

This is a Claude plugin marketplace. Plugins are topical and prefixed with `andrewrabert-`. Add a skill to the plugin whose topic fits; create a new plugin only when none fits or the user requests it.

## Structure

```
.claude-plugin/marketplace.json        # Marketplace catalog
plugins/
  <plugin-name>/
    .claude-plugin/plugin.json         # Plugin manifest
    skills/<skill-name>/SKILL.md       # Skills
justfile                               # Task runner — see `just --list`
```

## Plugins

All plugin names are prefixed with `andrewrabert-`:
- `andrewrabert-dev` - Python and shell scripting conventions

## Adding Skills

Add a skill to the topical plugin that fits: `plugins/<plugin>/skills/<skill-name>/SKILL.md`.

## Creating New Plugins

Only create a new plugin when explicitly requested:

```sh
just new-plugin <name> "<description>"
```

This scaffolds `plugins/<name>/.claude-plugin/plugin.json` and registers the
plugin in `.claude-plugin/marketplace.json`. The `andrewrabert-` prefix is added
if absent. Then add skills in `plugins/<name>/skills/`.

### plugin.json is fully script-managed

Only `description` is hand-edited. Everything else is owned by the scripts:
`name` always equals the plugin directory, `version` is date-based (`YYYY.MM.DD.N`,
defaulting to today and bumped by the pre-commit hook), and `author` is fixed.
Run `just check-plugin` to normalize every manifest back to the canonical shape
(it drops stray keys and fixes drifted fields).

## Versioning

Plugin versions use format `YYYY.MM.DD.N` where N is incremented int for same-day releases.

Examples: `2026.01.13.0`, `2026.01.13.1`

The git pre-commit hook (installed automatically by any `just` recipe) bumps
the version of every plugin with staged changes, regenerates `README.md`, and
runs `just lint`. No manual steps needed.
