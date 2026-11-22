#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     'bashkit>=0.18.2,<0.19',
# ]
# ///
"""Run one bash, read, write, or edit tool call in a bashkit sandbox.

Each --root is mounted read-write at its own host path, and --tmp at /tmp;
everything else is in-memory and gone when the call exits. The tool's
arguments are a JSON object on stdin. The result is printed to stdout; a
failed call exits 1 with the reason on stderr.
"""

import argparse
import asyncio
import json
import pathlib
import sys

import bashkit

MAX_BYTES = 256 * 1024


class UserError(Exception):
    pass


def joined_output(stdout, stderr, exit_code):
    parts = [part for part in (stdout, stderr) if part]
    if exit_code != 0:
        parts.append(f"(exit code {exit_code})")
    return "\n".join(parts)


def text_lines(text):
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def string_arg(arguments, name):
    value = arguments.get(name)
    if not isinstance(value, str):
        raise UserError(f"{name}: expected a string")
    return value


def uint_arg(arguments, name):
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UserError(f"{name}: expected a non-negative integer")
    return value


def bool_arg(arguments, name):
    value = arguments.get(name, False)
    if not isinstance(value, bool):
        raise UserError(f"{name}: expected a boolean")
    return value


def absolute_path_arg(arguments):
    path = string_arg(arguments, "file_path")
    if not path.startswith("/"):
        raise UserError("file_path must be absolute")
    return str(pathlib.PurePosixPath(path))


class Sandbox:
    def __init__(self, roots, tmp):
        self.bash = bashkit.Bash(cwd=str(roots[0]))
        self.bash.mount(
            "/tmp",
            bashkit.FileSystem.real(str(tmp), writable=True),
            read_only=False,
        )
        for root in roots:
            self.bash.mount(
                str(root),
                bashkit.FileSystem.real(str(root), writable=True),
                read_only=False,
            )
        self.fs = self.bash.fs()

    def read_text(self, path):
        if not self.fs.exists(path):
            raise UserError("File does not exist.")
        if self.fs.stat(path)["file_type"] != "file":
            raise UserError("Illegal operation on a directory")
        return self.fs.read_file(path).decode(errors="replace")

    def write_text(self, path, content):
        existed = self.fs.exists(path)
        if existed and self.fs.stat(path)["file_type"] != "file":
            raise UserError("Illegal operation on a directory")
        try:
            self.fs.mkdir(
                str(pathlib.PurePosixPath(path).parent), recursive=True
            )
            self.fs.write_file(path, content.encode())
        except Exception as e:
            raise UserError(f"{path}: {e}") from e
        return existed

    async def bash_tool(self, arguments):
        command = string_arg(arguments, "command")
        string_arg(arguments, "description")
        result = await self.bash.execute(command)
        return joined_output(result.stdout, result.stderr, result.exit_code)

    async def read_tool(self, arguments):
        path = absolute_path_arg(arguments)
        offset = uint_arg(arguments, "offset")
        limit = uint_arg(arguments, "limit")
        if offset == 0:
            raise UserError("offset: line numbers start at 1")
        text = self.read_text(path)
        if not text:
            raise UserError("File exists but has empty contents.")
        size = len(text.encode())
        if offset in (None, 1) and limit is None and size > MAX_BYTES:
            raise UserError(
                f"File content ({size / 1024:.1f}KB) exceeds maximum allowed "
                f"size ({MAX_BYTES // 1024}KB). Use offset and limit to read "
                "specific portions of the file."
            )
        start = (offset or 1) - 1
        end = None if limit is None else start + limit
        return "\n".join(
            f"{start + i + 1:>6}\t{line}"
            for i, line in enumerate(text_lines(text)[start:end])
        )

    async def write_tool(self, arguments):
        path = absolute_path_arg(arguments)
        content = string_arg(arguments, "content")
        if self.write_text(path, content):
            return f"The file {path} has been updated successfully."
        return f"File created successfully at: {path}"

    async def edit_tool(self, arguments):
        path = absolute_path_arg(arguments)
        old = string_arg(arguments, "old_string")
        new = string_arg(arguments, "new_string")
        replace_all = bool_arg(arguments, "replace_all")
        if old == new:
            raise UserError(
                "No changes to make: old_string and new_string are exactly the same."
            )
        text = self.read_text(path)
        count = text.count(old)
        if count == 0:
            raise UserError("String to replace not found in file.")
        if not replace_all and count > 1:
            raise UserError(
                f"Found {count} matches of the string to replace, but "
                "replace_all is false. Set replace_all to true, or give "
                "more context to identify one instance."
            )
        self.write_text(path, text.replace(old, new))
        return f"The file {path} has been updated successfully."


TOOLS = {
    "bash": Sandbox.bash_tool,
    "read": Sandbox.read_tool,
    "write": Sandbox.write_tool,
    "edit": Sandbox.edit_tool,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        type=pathlib.Path,
        help="a directory to mount read-write; repeatable",
    )
    parser.add_argument(
        "--tmp",
        required=True,
        type=pathlib.Path,
        help="a directory to mount read-write at /tmp",
    )
    parser.add_argument("tool", choices=TOOLS)
    args = parser.parse_args()
    roots = []
    for root in args.root:
        if not root.is_absolute():
            parser.error(f"{root}: not an absolute path")
        if not root.is_dir():
            parser.error(f"{root}: not a directory")
        roots.append(root.resolve())
    if not args.tmp.is_absolute() or not args.tmp.is_dir():
        parser.error(f"{args.tmp}: not an absolute path of a directory")
    try:
        arguments = json.load(sys.stdin)
        if not isinstance(arguments, dict):
            raise UserError("the arguments are not a JSON object")
        result = asyncio.run(
            TOOLS[args.tool](Sandbox(roots, args.tmp.resolve()), arguments)
        )
    except (UserError, json.JSONDecodeError) as e:
        print(e, file=sys.stderr)
        return 1
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
