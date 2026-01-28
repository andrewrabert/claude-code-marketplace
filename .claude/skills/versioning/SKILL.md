---
name: versioning
description: "Use when changing plugin versions, bumping versions, updating plugin.json, or creating new plugins in this marketplace."
---

# Plugin Versioning

**All plugins in this marketplace use date-based versioning.**

## Format

```
YYYY.MM.DD.SERIAL
```

Example: `2026.01.21.0`

- `YYYY.MM.DD` = date of change (today's date)
- `.SERIAL` = 0 for first change that day, 1 for second, etc.

## Rules

1. **Always use today's date** when bumping a version
2. **Check existing version** - if already updated today, increment the serial
3. **Never use semver** (1.0.0, 1.1.0, etc.) in this marketplace

## Examples

First change on Jan 21, 2026:
```json
"version": "2026.01.21.0"
```

Second change same day:
```json
"version": "2026.01.21.1"
```

Next day:
```json
"version": "2026.01.22.0"
```
