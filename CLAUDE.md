# Claude Marketplace Repository

This is a Claude plugin marketplace. Plugins are topical and prefixed with `andrewrabert-`. Add a skill to the plugin whose topic fits; create a new plugin only when none fits or the user requests it.

## Structure

```
.claude/skills/<skill-name>/SKILL.md   # Repo-specific skills (not distributed)
.claude-plugin/marketplace.json        # Marketplace catalog
plugins/
  <plugin-name>/
    .claude-plugin/plugin.json         # Plugin manifest
    skills/<skill-name>/SKILL.md       # Skills
```

## Repo-Specific Skills

Skills in `.claude/skills/` are local to this repo and not distributed via the marketplace:
- `versioning` - Use when changing plugin versions

## Plugins

All plugin names are prefixed with `andrewrabert-`:
- `andrewrabert-dev` - Python and shell scripting conventions
- `andrewrabert-spinner-verbs` - reference for Claude Code's default spinner verbs

## Adding Skills

Add a skill to the topical plugin that fits: `plugins/<plugin>/skills/<skill-name>/SKILL.md`.

## Creating New Plugins

Only create a new plugin when explicitly requested. Steps:

1. Create `plugins/<name>/.claude-plugin/plugin.json`:
   ```json
   {
     "name": "<name>",
     "description": "<description>",
     "version": "1.0.0",
     "author": { "name": "Andrew Rabert" }
   }
   ```

2. Add to `.claude-plugin/marketplace.json` plugins array:
   ```json
   {
     "name": "<name>",
     "source": "./plugins/<name>",
     "description": "<description>"
   }
   ```

3. Add skills in `plugins/<name>/skills/`

## Versioning

Plugin versions use format `YYYY.MM.DD.N` where N is incremented int for same-day releases.

Examples: `2026.01.13.0`, `2026.01.13.1`

Update version in `plugins/<name>/.claude-plugin/plugin.json` when releasing changes.

## Validation

Always run after changes:

```sh
claude plugin validate .
```
