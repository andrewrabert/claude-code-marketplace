---
name: python-tui
description: Use when building or editing terminal UIs (TUIs) in Python - Textual app with tabbed DataTables, filter-as-you-type, vim keys, rich-styled cells, async workers, modal detail screens, $EDITOR for multi-line text input
---

# TUI Preferences

**Project conventions take precedence unless user says otherwise.**

**Invoke the python skill first** - code style (quotes, type hints, line
length) comes from it and project conventions; this skill covers TUI
architecture only.

## Framework Choice

| Task | Use | Not |
|------|-----|-----|
| Interactive TUI | `textual` | curses, urwid, prompt_toolkit |
| Styled cell content | `rich.text.Text` | ANSI escapes, CSS |
| One-shot progress (non-TUI commands) | `rich.progress` | tqdm |

uv script deps: `"rich>=13", "textual>=3"`.

## App Shape

One `App` subclass per TUI. The preferred shape is a **tabbed data
browser**: each tab is a filterable, sortable `DataTable` over a query
method on a data layer.

Keep `CSS` minimal - layout only, no colors or borders:

```python
class MyApp(App):
    TITLE = 'my-tool'
    CSS = """
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; }
    DataTable { height: 1fr; }
    """
```

All color happens at runtime per-cell via `rich.text.Text`, never in CSS.

## Layout: Tabs of Tables

`compose()` yields `Header()`, a `TabbedContent` of `TabPane`s (nested
`with` blocks), `Footer()`. Each pane contains one filter `Input`
(hidden until `/`) and one `DataTable`.

ID conventions: `tab-<name>`, `<name>-table`, `filter-<name>`.

Always use `cursor_type='row'` - row selection, not cell selection.

`on_mount` hides every filter (`input.display = False`), adds columns,
runs each populate once, and focuses the first table.

Bindings target "the current tab's widget" via dispatch helpers
(`_active_table()`, `_active_filter()`): a dict maps
`self.query_one(TabbedContent).active` (the pane id) to the widget id,
which goes to `query_one`.

Column sets may be data-driven: when a tab pivots a dimension into
columns (e.g. one column per environment), compute the column list from
the data layer in `on_mount`, never hardcode it. A pivot populate
collapses rows on a key, spreads the dimension across columns, and can
detect conflicts with `collections.Counter` on the collapsed keys.

## Data Layer Separation

The App never holds SQL or HTTP. A data class (e.g. `Database`) exposes
one query method per view, each taking a `query` substring filter:
lowercase both sides and `LIKE '%…%'`-match across the user-visible text
columns, with a stable `ORDER BY`.

One `_populate_<tab>()` method per tab: clear, add rows, update the tab
label with a row count. Tab labels always show counts: `Matched (137)`.

## Filter-as-You-Type

- `/` shows and focuses the current tab's filter input
- `escape` clears it, hides it, and refocuses the table
- `on_input_changed` dispatches by `event.input.id` to the matching
  populate method with `event.value`, so the table refilters on every
  keystroke

## Key Bindings

Footer-visible bindings for real actions, hidden bindings for navigation:

```python
BINDINGS = [
    Binding('q', 'quit', 'Quit'),
    Binding('/', 'focus_filter', 'Filter', show=True),
    Binding('escape', 'clear_filter', 'Clear', show=False),
    Binding('o', 'open_repo', 'Open in browser', show=True),
    Binding('h', 'vim("left")', show=False),
    Binding('j', 'vim("down")', show=False),
    Binding('k', 'vim("up")', show=False),
    Binding('l', 'vim("right")', show=False),
]
```

Always include vim keys. `action_vim()` dispatches on `self.focused`:
`Tabs` focused, h/k call `action_previous_tab()` and l/j
`action_next_tab()`; `DataTable` focused, hjkl move the cursor
(`getattr(focused, f'action_cursor_{direction}')()`). Inputs swallow
printable keys before app bindings run, so typing in a filter is
unaffected.

`o` opens the selected row's URL via `webbrowser.open()`.

Actions shared across tabs read their target from a per-table column
map; actions that only make sense on one tab guard on the table id and
no-op elsewhere:

```python
# Column index holding the action target per table.
_TARGET_COLUMN = {'matched-table': 1, 'diff-table': 1, 'jobs-table': 3}
```

The action no-ops when the table id isn't in the map or the table is
empty, and `notify(..., severity='warning')`s when the cell under the
cursor is blank.

## Cell Styling

Wrap values in `rich.text.Text(value, style=...)`. Use module-level style
dicts for enumerated states:

```python
_VERDICT_STYLES = {'yes': 'red', 'review': 'yellow', 'no': 'dim'}
```

Semantic palette:

| Style | Meaning |
|-------|---------|
| `red` | problem, conflict, lagging |
| `yellow` | warning, needs attention |
| `green` | done, healthy |
| `dim` | ignored, inactive |
| `cyan` | in-progress (ephemeral) |
| `bold red` | prominent alert |

When a column mirrors another system's states, match that system's UI
colors instead of the generic palette so the TUI reads the same way.

Conditional styling happens in the populate method: build the plain cell
list, then replace the offending cell with a styled `rich.text.Text`
before `add_row`. To highlight a whole row, wrap every cell in the same
style.

When several code paths render the same row (populate, in-place updates,
worker callbacks), centralize the row→cells mapping in one classmethod so
all paths agree:

```python
@classmethod
def _item_cells(cls, status, name, value, detail):
    values = [status, name, value, detail]
    style = cls._LIFECYCLE_STYLES.get(status)  # whole-row, wins
    if style:
        return [rich.text.Text(str(v), style=style) for v in values]
    if cls._is_anomaly(status, value):         # row red, key cell bold
        cells = [rich.text.Text(str(v), style='red') for v in values]
        cells[0] = rich.text.Text(str(status), style='bold red')
        return cells
    state_style = cls._STATE_STYLES.get(status)  # single cell
    if state_style:
        values[0] = rich.text.Text(str(status), style=state_style)
    return values
```

Style precedence: transient lifecycle (whole row) > anomaly highlight >
per-cell state style.

## Sorting

Header click sorts; re-click toggles direction. Cache sort state per
table - `(column_index, reverse)` keyed by table id - so it survives
refilters.

Append `↓`/`↑` to the sorted column's label. Cache the original labels
in `_init_table` (the helper that calls `add_columns`) and rebuild every
label from the originals on each header click - otherwise arrows
accumulate.

Reapply the cached sort at the end of every populate method. When a view
has a meaningful default order, make the populate's default sort produce
the same order a header click would, so toggling between them is
seamless.

A clicked column may sort by several columns (e.g. status, then name).
Keep the rules in a per-table map; columns not listed sort by themselves:

```python
# {table_id: {clicked_col_idx: [sort_col_idx, ...]}}
_SORT_RULES = {'items-table': {0: [0, 1]}}
```

Sort key functions must normalize: cells mix `str` and `rich.text.Text`,
which don't compare, so always sort on `str(value)`. Add per-column keys
for numeric columns (`int(...)`), version columns (`(major, minor)`
tuples), and enumerated states (a workflow-order rank dict). Note that
textual passes the key fn a tuple of cell values for multi-column sorts
and a single value otherwise - handle both:

```python
def key(value):
    if isinstance(value, tuple):
        return tuple(str(v) for v in value)
    return str(value)
```

## In-Place Updates vs Repopulate

Mutations update the affected row's cells in place rather than
repopulating, so sort order and cursor position are preserved.
Repopulate only when the row would become hidden by a view filter.

Address rows by **row key**, not coordinates - key-addressed updates
survive sorts and cursor moves. Capture the key before dispatching a
worker:

```python
row_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0)).row_key
```

Update helpers no-op when the row is gone (the table was repopulated by
a filter change meanwhile) - the data layer already holds the truth and
the next populate agrees:

```python
def _update_item_row(self, table, row_key, *row):
    if row_key not in table.rows:
        return
    cells = self._item_cells(*row)
    for col, cell in zip(table.ordered_columns, cells, strict=True):
        table.update_cell(row_key, col.key, cell)
```

When a repopulate is unavoidable, preserve the cursor: remember the key
value under the cursor, scan for its new row index afterwards, fall back
to the old index clamped to the new row count, and `move_cursor` there.

Views over workflow data hide completed/ignored rows by default behind a
toggle binding that flips a bool and repopulates - but anomaly rows the
view exists to surface stay visible regardless of the toggle. `notify()`
the new mode on each flip.

## Detail Modal

Row selection pushes a `Screen` showing key-value details; `escape`/`q`
dismisses. Focus the modal's table in `on_mount`:

```python
class FactsScreen(Screen):
    BINDINGS = [Binding('escape,q', 'dismiss', 'Back')]

# in the App:
def on_data_table_row_selected(self, event):
    if event.data_table.id == 'matched-table':
        row = event.data_table.get_row(event.row_key)
        self.push_screen(FactsScreen(row[1], self._db.facts_for(row[2])))
```

## $EDITOR for Text Input

Multi-line or structured text input (a query, a message body, a config
edit) goes through `$EDITOR`, not a TUI text widget - bind `e` to it.
Seed a temp file with the current value or a template, use a meaningful
suffix (syntax highlighting), suspend, read the result back as the
input:

```python
async def action_edit(self):
    editor = os.environ.get('EDITOR') or os.environ.get('VISUAL')
    if not editor:
        self.notify('$EDITOR is not set', severity='warning')
        return
    with TempPath(suffix='.sql') as path:
        path.write_text(self._text)
        with self.app.suspend():
            process = await asyncio.create_subprocess_exec(
                *shlex.split(editor), str(path)
            )
            await process.communicate()
        if process.returncode:
            self.notify(f'editor exited with {process.returncode}',
                        severity='error')
            return
        self._text = path.read_text()
        self.query_one(Static).update(self._text)
```

`shlex.split` handles editors with flags (`code -w`). Awaiting an
asyncio subprocess inside `suspend()` is fine - nothing renders while
suspended. Treat a non-zero exit as cancel: discard the file, keep the
old value.

## Async: Never Block the UI

The event loop only does instant work. Anything that could take
perceptible time - network calls, subprocesses, disk I/O, heavy
computation - goes in a `@work(group=...)` async worker so the UI stays
responsive: the cursor moves, filters refilter, tabs switch, all while
work runs. Use async libraries and `asyncio.create_subprocess_exec`
inside workers; wrap unavoidable sync calls in `@work(thread=True)`.

For mutations, the action validates before dispatching (target already
processed? already in flight?), captures the row key, and hands off to
the worker:

- Track in-flight keys in a set to prevent double-dispatch
- Optimistically update the row in place before the call, with the
  `cyan` in-progress style
- On failure, recompute the row's true status via a `_status_for()`
  helper that mirrors the data layer's logic, and write it back
- `self.notify()` on start and success; `severity='error'` on failure
- Write results back to the data layer so the next populate agrees

API clients that only mutation actions need are built lazily on first
use (with instance-dict caches for their lookups) - browsing the TUI
never requires credentials.

## CLI Integration

The TUI is one subcommand among several, and the **default** when no
subcommand is given (the `match` on the command falls through to
`cmd_tui`). Import textual lazily inside `cmd_tui()` so other
subcommands never pay for it - the one exception to the imports-at-top
rule. Check the data file exists before launching: friendly message to
stderr ("run sync first"), return 1.

## Common Mistakes

- Styling via CSS instead of `rich.text.Text` cells
- Importing textual at module top in multi-command scripts
- Putting SQL or HTTP calls inside the App class
- Forgetting to reapply cached sort after repopulating a table
- Appending sort arrows without restoring from cached original labels
  (arrows accumulate)
- Comparing styled `rich.text.Text` cells in sort keys instead of
  normalizing to `str`
- Addressing rows by coordinate after a sort instead of by row key
- Leaving the optimistic in-progress cell behind when a worker fails
- Repopulating (losing sort and cursor) when an in-place cell update
  suffices
- Blocking the event loop with anything slow (network, subprocess, disk,
  compute) instead of a `@work` worker
- Omitting row counts from tab labels
- Using `cursor_type='cell'` when rows are the unit of selection
- No vim keys
- Collecting multi-line text input in a TUI widget instead of `$EDITOR`
- Launching `$EDITOR` without `app.suspend()` (garbles the terminal)
