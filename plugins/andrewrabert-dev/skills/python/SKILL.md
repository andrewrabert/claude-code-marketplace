---
name: python
description: Use when writing or editing Python scripts/code, or when file has python shebang or .py extension - uv script mode when deps needed, module-only imports, pathlib for paths, asyncio.subprocess for processes (user)
---

# Python Preferences

**Project conventions take precedence unless user says otherwise.**

## After Writing Python

Run ruff on every Python file after writing/editing:

```sh
ruff format <file>
ruff check <file>
```

Fix all errors reported by ruff check. Re-run until clean.

## Script Format

**With dependencies:** use uv script mode + PEP 723 metadata:

```python
#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "package-name",
# ]
# ///
"""One-line summary of what the script does."""
```

The PEP 723 `# /// script` block stays in `#` comments above the docstring - never move it inside the docstring.

**No dependencies:** standard shebang, no metadata block:

```python
#!/usr/bin/env python3
```

## Imports

- **NEVER** import functions/classes/etc - only import modules
- All imports at top, alphabetical within groups
- Stdlib first, blank line, then third-party

```python
# WRONG - never import classes/functions
from yarl import URL
from pathlib import Path

# CORRECT - import modules
import pathlib
import yarl

url = yarl.URL("https://example.com")
p = pathlib.Path("/tmp")
```

## Standard Library Choices

| Task | Use | Not |
|------|-----|-----|
| Paths | `pathlib` | strings |
| CLI args | `argparse` | - |
| Subprocesses | `asyncio.subprocess` | `subprocess` |

## Preferred Third-Party Libraries

| Task | Use | Not |
|------|-----|-----|
| HTTP client | `httpx` | `requests`, `urllib` |
| URL handling | `yarl` | `urllib.parse` |

## Style

- **Double blank lines** between top-level definitions (classes, functions)
- **Named arguments** in function calls when >2 args
- **Match statements** (Python 3.10+) for multi-branch conditionals
- **Context managers** (`with`) for file handles, connections

## argparse Patterns

- Use `add_argument_group()` to organize related args
- Use `dest=` to rename args (e.g., `--from` → `from_address`)
- Use `type=pathlib.Path` for path arguments

```python
parser = argparse.ArgumentParser()
group = parser.add_argument_group("server")
group.add_argument("--host", required=True)
group.add_argument("--port", type=int, required=True)
```

### Subcommands

- Create with `add_subparsers(dest="command", required=True)`
- Per subcommand: `x_parser = subparsers.add_parser("name", help="...")`, then
  add its args. Subcommands with no args use a bare `subparsers.add_parser(...)`
- Dispatch with `match args.command:`, one `case` per subcommand
- Handlers named `cmd_<name>`, take `args` (plus shared objects), pull what they
  need off `args`

```python
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="start library scan")
    scan_parser.add_argument("-w", "--wait", action="store_true", help="wait for scan")

    subparsers.add_parser("list", help="list libraries")  # bare: no args

    search_parser = subparsers.add_parser("search", help="search items")
    search_parser.add_argument("query", help="search term")

    args = parser.parse_args()
    match args.command:
        case "scan":
            cmd_scan(args)
        case "list":
            cmd_list(args)
        case "search":
            cmd_search(args)
```

## CLI Tool Wrapper Classes

Group external CLI tool calls in a class with `@staticmethod`/`@classmethod` methods:

```python
class exiftool:
    @staticmethod
    async def to_json(path):
        proc = await asyncio.create_subprocess_exec(
            "exiftool", "-json", "--", path,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return json.loads(stdout)

    @staticmethod
    async def from_json(path, data):
        ...
```

## Multi-Command Scripts

Use `sys.argv[0]` with match statement for multi-personality scripts (symlinked to different names):

```python
if __name__ == "__main__":
    match pathlib.Path(sys.argv[0]).name:
        case "imgconvert":
            asyncio.run(main_convert())
        case "imgoptim" | _:
            asyncio.run(main_optim())
```

## Classes

- Simple `__init__` with direct attribute assignment
- `@classmethod` for alternate constructors/utilities
- Class-level constants for configuration (e.g., ANSI codes, mappings)

## Common Patterns

**TempPath context manager** - returns `pathlib.Path`, suppresses missing file on cleanup:

```python
@contextlib.contextmanager
def TempPath(**kwargs):
    with tempfile.NamedTemporaryFile(**kwargs, delete=False) as tmp:
        temp_path = pathlib.Path(tmp.name)
        try:
            yield temp_path
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
```

**Iterative directory traversal** - explicit stack instead of recursion:

```python
def all_files(*paths):
    stack = []
    files = set()
    for path in paths:
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            stack.append(path)
    while stack:
        for path in stack.pop().iterdir():
            if path.is_dir():
                stack.append(path)
            else:
                files.add(path)
    return sorted(files)
```

**UserError for CLI scripts** - raise for user-facing errors, catch in main:

```python
class UserError(Exception):
    pass

# In command functions:
raise UserError(f"invalid date format '{args.date}', expected YYYY-MM-DD")

# In main guard:
if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
```

**Process error with context**:

```python
class ProcessError(Exception):
    def __init__(self, process, message=None):
        self.process = process
        self.message = message

    def __str__(self):
        text = f"exit {self.process.returncode}"
        if self.message:
            text = f"{text} - {self.message}"
        return text
```

**Safe file write** - temp file, preserve permissions/ownership, atomic rename:

```python
def safe_write_bytes(path, data):
    stat = path.stat() if path.exists() else None
    with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as handle:
        temp_path = pathlib.Path(handle.name)
        try:
            temp_path.write_bytes(data)
            if stat:
                for ids in ((stat.st_uid, -1), (-1, stat.st_gid)):
                    try:
                        os.chown(temp_path, *ids)
                    except PermissionError:
                        pass
                temp_path.chmod(stat.st_mode)
            temp_path.replace(path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
```

## JSON Output

```python
def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


print(json_dumps(data))
```

## Executable Scripts

Always use a main guard:

```python
if __name__ == "__main__":
    asyncio.run(main())
```

## Common Mistakes

- Importing `from pathlib import Path` instead of `import pathlib`
- Using `subprocess.run()` instead of `asyncio.create_subprocess_exec()`
- Missing PEP 723 block when script has dependencies
- Missing `if __name__ == "__main__":` guard
- Putting imports inside functions instead of at top of file
