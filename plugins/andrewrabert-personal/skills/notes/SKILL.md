---
name: notes
description: Use when searching Obsidian notes, creating new notes, updating existing notes, or managing daily notes and tasks - understands vault structure, dataview syntax, and tag system
---

# Obsidian Notes Skill

Notes vault: `~/src/notes`

**MANDATORY: Always use the `notes` CLI for searching/finding notes. NEVER use Grep/Glob/Read directly on the vault to locate notes. Use `notes search`, `notes find`, or `notes tags` first, then Read/Edit the specific file paths returned.**

## CLI Tool

Use the `notes` command for all note operations:

```sh
notes search <pattern>   # search note contents (rg wrapper)
notes find <pattern>     # find notes by filename (fd wrapper)
notes tags <tag>         # find notes with tag (auto-adds # if missing)
notes daily [YYYY-MM-DD] # get daily note path (default: today), creates dir
notes daily --dir        # return directory path only
notes fzf                # fuzzy find and open note (default when interactive)
notes fzf -p             # print path instead of opening
notes fzf -a             # search all files, not just .md/.txt
notes clean              # remove empty notes and empty directories
```

When run without subcommand in interactive terminal, defaults to `notes fzf`.

### Examples

```sh
notes search "home assistant"     # content search
notes find "Raspberry"            # filename search
notes tags "project/home-assistant"  # tag search (# optional)
notes tags shopping               # also works
notes daily                       # prints path like .../2025-11-28/2025-11-28.md
notes daily 2025-01-15            # specific date
notes daily --dir                 # prints dir like .../2025-11-28/
notes fzf                         # interactive fuzzy search, opens in editor
notes fzf -p                      # fuzzy search, print path only
notes clean                       # removes empty/template-only notes
```

## Daily Notes

Location: `Daily/YYYY/YYYY-MM/YYYY-MM-DD/YYYY-MM-DD.md` (folder note pattern)

Template:
```markdown
# YYYY-MM-DD

## Journal
-

## Tasks
- [ ]
```

Use `notes daily` to get path and create directory.

## Adding to Journal

When user says "add to journal" or "journal this":

1. Run `notes daily` to get path (creates dir if needed)
2. Read the file, or create with template if missing
3. Find `## Journal` section, append entry after existing bullets
4. Format: `- HH:MM: <content>` (24-hour time)

Example:
```markdown
## Journal
- 14:32: Finished setting up home assistant automation
- 16:45: Had idea about improving backup script
```

## Topic Notes

Use **folder notes pattern**:
- Main note: `Topic/Topic.md` (e.g., `Hardware/Raspberry Pi/Raspberry Pi.md`)
- Related content in subfolders

Content areas:
- `Hardware/` - devices, vehicles, PC components
- Create new top-level folders for distinct categories

## Updating Topic Notes

When user says "update my X notes" or "add to my X notes":

1. Find the note: `notes find "X"` or `notes search "X"`
2. Read the file at the folder note path (e.g., `~/notes/Tech/SSH/SSH.md`)
3. Edit to append/modify the requested content
4. Preserve existing structure and formatting

Example prompt: "update my ssh notes with an example of ssh-keygen"
-> Find SSH note -> Read -> Append the example

## Tasks

Dataview syntax for metadata:

```markdown
- [ ] Task description [due:: 2024-01-15]
- [ ] Another task [scheduled:: 2024-01-10]
- [ ] Task with start date [start:: 2024-01-08]
- [ ] Tagged task #project/home-assistant [due:: 2024-01-20]
```

### Task Queries

```sh
notes search "- \[ \]"              # all incomplete tasks
notes search "\[due::"              # tasks with due dates
notes search "- \[ \].*#shopping"   # tasks by tag
```

## Tag Categories

| Category | Examples |
|----------|----------|
| Projects | `#project/home-assistant`, `#project/editor`, `#project/tmux` |
| Reading | `#read`, `#read/claude`, `#read/paper` |
| Admin | `#money`, `#phone`, `#shopping`, `#expires` |
| Returns | `#return/amazon`, `#return/staples` |
| Tech | `#testing`, `#patterns`, `#docker`, `#python` |
| Downloads | `#download/music`, `#download/movie/horror` |

## Formatting Rules

- **Dates**: YYYY-MM-DD
- **Times**: 24-hour (HH:MM)
- **Links**: `[[Note Name]]` or `[[folder/Note Name|Display Text]]`
- **Tags**: lowercase, use `/` for hierarchy
