# Claude Marketplace Repository

This is a Claude plugin marketplace. Personal skills go in the `andrewrabert-personal` plugin unless user explicitly requests a new plugin.

## Structure

```
.claude-plugin/marketplace.json    # Marketplace catalog
plugins/
  <plugin-name>/
    .claude-plugin/plugin.json     # Plugin manifest
    skills/<skill-name>/SKILL.md   # Skills
```

## Adding Skills

Add new skills to `plugins/andrewrabert-personal/skills/<skill-name>/SKILL.md`.

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

## Validation

Always run after changes:

```sh
claude plugin validate .
```
