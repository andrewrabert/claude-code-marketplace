#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ['bashkit>=0.18.2,<0.19', 'fastmcp>=4,<5', 'pyyaml>=6,<7']
# ///
import argparse
import asyncio
import collections.abc
import contextlib
import datetime
import fcntl
import fnmatch
import json
import os
import pathlib
import re
import shutil
import signal
import sys
import tempfile
import typing

import bashkit
import fastmcp
import fastmcp.tools
import mcp.types as mcp_types
import pydantic
import pydantic.json_schema
import yaml

SCRIPT = pathlib.Path(__file__).resolve()

STANDARDS_COMMANDS = ("list-standards", "read-standard", "search-standards")
REVIEW_COMMANDS = (
    "start-review",
    "record-violation",
    "finish-review",
    "read-review",
)

SESSIONS = "sessions"
PRS = "prs"
HEAD = "head"
BASE = "base"
DIFF = "diff.txt"
META = "meta.json"
VIOLATIONS = "violations.jsonl"
REPORT = "report.md"
USERNAME = "agent"
HOME_DIR = pathlib.PurePosixPath("/sandbox")
SCRATCH_DIR = pathlib.PurePosixPath("/tmp")
REVIEW_DIR = HOME_DIR / PRS / "<host>/<org>/<repo>/<pr>"
REVIEW_HEAD = REVIEW_DIR / HEAD
REVIEW_BASE = REVIEW_DIR / BASE
REVIEW_DIFF = REVIEW_DIR / DIFF
STANDARDS = "standards"
STANDARDS_DIR = HOME_DIR / STANDARDS
STANDARDS_REPOS = "repos"
SEGMENT = re.compile(r"[A-Za-z0-9._-]+")

MAX_BYTES = 256 * 1024
JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"

BUILD_ONLY_ENV = (
    "BASHKIT_ALLOW_INPROCESS_PYTHON",
    "BASHKIT_ALLOW_INPROCESS_SQLITE",
)

INSTRUCTIONS = (
    f"Sandbox for PR review. {HOME_DIR} is read-only; {SCRATCH_DIR} is "
    "writable scratch space that never leaves the sandbox. Call start_review "
    "with the host, org, repo, and pr; it writes the pull request to "
    f"{REVIEW_HEAD}, its merge base with the target branch to "
    f"{REVIEW_BASE}, and the full diff between them to {REVIEW_DIFF}. "
    f"Standards files are in {STANDARDS_DIR}. List them with "
    "list_standards, read them with read_standard, and find them with "
    "search_standards. read_standard without a path, after start_review, "
    "reads every standard that applies to the reviewed repo. Call record_violation once per violation, with path "
    "relative to head, then finish_review."
)


async def run(*args, cwd=None, text=True, input=None):
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL
        if input is None
        else asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input)
    if proc.returncode != 0:
        raise ProcessError(
            proc,
            f"{' '.join(args[:3])}\n{stderr.decode().strip()}",
        )
    return stdout.decode() if text else stdout


async def git(git_dir, *argv, text=True):
    return await run(
        "git", "--no-pager", f"--git-dir={git_dir}", *argv, text=text
    )


def check_segments(parts):
    for part in parts:
        if not SEGMENT.fullmatch(part) or part in (".", ".."):
            raise UserError("invalid path segment")
    return pathlib.Path(*parts)


def review_dir(state, host, org, repo, pr):
    return state / PRS / check_segments((host, org, repo, str(pr)))


def session_dir(data, session_id):
    # Flat, so a session's sandbox never sees its subagents' dirs
    parts = session_id.split("/")
    check_segments(parts)
    return data / SESSIONS / "+".join(parts)


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def read_meta(review):
    try:
        return json.loads((review / META).read_text())
    except FileNotFoundError:
        return None


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


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def write_meta(review, meta):
    safe_write_bytes(review / META, (json_dumps(meta) + "\n").encode())


def tool_specs():
    def tool(
        command, description, repo=True, flags={}, remainder=None, **extra_args
    ):
        repo_args = {
            "host": {
                "description": "GitHub host",
                "args": ["--host={{value}}"],
            },
            "org": {
                "description": "Organization or user that owns the repo",
                "args": ["--org={{value}}"],
            },
            "repo": {
                "description": "Repository name",
                "args": ["--repo={{value}}"],
            },
        }
        return {
            "command": command,
            "description": description,
            "arg": {
                **(repo_args if repo else {}),
                **{
                    name: {
                        "description": text,
                        "args": [f"--{name}={{{{value}}}}"],
                    }
                    for name, text in extra_args.items()
                },
                **{
                    name: {"description": text, "args": [f"--{name}"]}
                    for name, text in flags.items()
                },
            },
            **({"args": remainder} if remainder else {}),
        }

    return {
        "start_review": tool(
            "start-review",
            f"Start a review: write a pull request to {REVIEW_HEAD}, its "
            f"merge base with the target branch to {REVIEW_BASE}, and the "
            f"diff between them to {REVIEW_DIFF}. Clears any earlier review "
            "of the pull request.",
            pr="Pull request number",
        ),
        "record_violation": tool(
            "record-violation",
            "Record one rule violation in the started review's head",
            repo=False,
            rule="Name of the rule the code breaks",
            path="File path relative to head",
            line="Line number of the violation",
            reason="One sentence on how the code breaks the rule",
        ),
        "finish_review": tool(
            "finish-review",
            "Finish the review: save the report from the recorded "
            "violations, then print it exactly as read_review does.",
            repo=False,
        ),
        "read_review": tool(
            "read-review",
            "Read a review: its metadata as YAML front matter, then its "
            "violations grouped by file. A review in progress shows the "
            "violations recorded so far.",
            pr="Pull request number",
        ),
        "list_standards": tool(
            "list-standards",
            "List standards files by relative path. sort: "
            "'path' or 'modified' (newest first).",
            repo=False,
            remainder={
                "description": (
                    "Paths to list: a bare name scopes to that "
                    "subtree or file, a '!' prefix excludes"
                ),
                "prefix": ["--"],
            },
            sort="path or modified [default: path]",
        ),
        "read_standard": tool(
            "read-standard",
            "Read standards. Without path, after start_review: every "
            "standard that applies to the reviewed repo, which is every .md "
            f"file in {STANDARDS_REPOS}/<host>/<org>/<repo> and in each "
            "parent directory up to and including the top, concatenated "
            "with a '==> /path <==' header per file. That result is "
            "complete; do not read its files again by path. With path: one "
            "standards file by relative path. Use offset/limit to page.",
            repo=False,
            path="Relative path of one file [default: every standard for "
            "the reviewed repo]",
            offset="First line to print, 0-based [default: 0]",
            limit="Maximum lines to print [default: all]",
        ),
        "search_standards": tool(
            "search-standards",
            "Find standards files by regular expression. pattern is "
            "smart-case (case-insensitive unless it has an uppercase "
            "letter) and defaults to '.', which lists every file. mode: "
            "'any' files matching by contents or path, 'line' "
            "'path:lineno:text' matches with context lines, 'file' "
            "files whose contents match, 'path' files whose path "
            "matches. sort: 'path' or 'modified' (newest first).",
            repo=False,
            pattern="Regular expression [default: .]",
            mode="any, line, file, or path [default: any]",
            flags={"fixed": "Match the pattern literally"},
            remainder={
                "description": (
                    "Paths to search: a bare name scopes to that "
                    "subtree or file, a '!' prefix excludes"
                ),
                "prefix": ["--"],
            },
            context="Context lines in line mode [default: 1]",
            sort="path or modified [default: path]",
        ),
    }


class UserError(Exception):
    pass


class ProcessError(Exception):
    def __init__(self, process, message=None):
        self.process = process
        self.message = message

    def __str__(self):
        text = f"exit {self.process.returncode}"
        if self.message:
            text = f"{text} - {self.message}"
        return text


class SandboxTool(fastmcp.tools.Tool):
    handler: typing.Annotated[
        pydantic.json_schema.SkipJsonSchema[
            collections.abc.Callable[
                [dict], collections.abc.Awaitable[fastmcp.tools.ToolResult]
            ]
        ],
        pydantic.Field(exclude=True),
    ]

    def to_mcp_tool(self, **overrides):
        tool = super().to_mcp_tool(**overrides)
        tool.title = None
        tool.meta = None
        return tool

    async def run(self, arguments):
        return await self.handler(arguments)


def text_result(text, error=False):
    return fastmcp.tools.ToolResult(
        content=[mcp_types.TextContent(type="text", text=text)], is_error=error
    )


def joined_output(stdout, stderr, exit_code):
    parts = [part for part in (stdout, stderr) if part]
    if exit_code != 0:
        parts.append(f"(exit code {exit_code})")
    return "\n".join(parts)


def invalid_type(value, expected):
    return UserError(f"invalid type: {json.dumps(value)}, expected {expected}")


def string_arg(arguments, name, required=True):
    value = arguments.get(name)
    if value is None:
        if required:
            raise UserError(f"missing field `{name}`")
        return None
    if not isinstance(value, str):
        raise invalid_type(value, "a string")
    return value


def uint_arg(arguments, name):
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid_type(value, "u64")
    return value


def bool_arg(arguments, name):
    value = arguments.get(name, False)
    if not isinstance(value, bool):
        raise invalid_type(value, "a boolean")
    return value


def absolute_path_arg(arguments):
    path = string_arg(arguments, "file_path")
    if not pathlib.PurePosixPath(path).is_absolute():
        raise UserError("file_path must be an absolute path, not relative")
    return path


def text_lines(text):
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


class Sandbox:
    def __init__(self, state, standards):
        self.lock = asyncio.Lock()
        self.bash = bashkit.Bash(
            username=USERNAME,
            hostname="sandbox",
            cwd=str(HOME_DIR),
            env={"HOME": str(HOME_DIR)},
            python=True,
            sqlite=True,
            profile=bashkit.ExecutionProfile.Interactive,
        )
        self.bash.mount(
            str(HOME_DIR),
            bashkit.FileSystem.real(str(state), writable=False),
            read_only=True,
        )
        self.bash.mount(
            str(STANDARDS_DIR),
            bashkit.FileSystem.real(str(standards), writable=False),
            read_only=True,
        )
        self.fs = self.bash.fs()

    async def start(self):
        await self.bash.execute(f"unset {' '.join(BUILD_ONLY_ENV)}")
        return self

    def resolve(self, path):
        return str(pathlib.PurePosixPath(path))

    def read_text(self, path):
        if not self.fs.exists(path):
            raise UserError("File does not exist.")
        if self.fs.stat(path)["file_type"] != "file":
            raise UserError("Illegal operation on a directory")
        return self.fs.read_file(path).decode(errors="replace")

    def write_text(self, path, content):
        existed = self.fs.exists(path)
        self.fs.mkdir(str(pathlib.PurePosixPath(path).parent), recursive=True)
        if existed and self.fs.stat(path)["file_type"] != "file":
            raise UserError("Illegal operation on a directory")
        self.fs.write_file(path, content.encode())
        return existed

    async def bash_tool(self, arguments):
        command = string_arg(arguments, "command")
        string_arg(arguments, "description")
        async with self.lock:
            result = await self.bash.execute(command)
        return text_result(
            joined_output(result.stdout, result.stderr, result.exit_code)
        )

    async def read_tool(self, arguments):
        path = self.resolve(absolute_path_arg(arguments))
        offset = uint_arg(arguments, "offset")
        limit = uint_arg(arguments, "limit")
        if offset == 0:
            raise UserError("offset: line numbers start at 1")
        async with self.lock:
            text = self.read_text(path)
        if not text:
            return text_result("File exists but has empty contents.", True)
        size = len(text.encode())
        if offset in (None, 1) and limit is None and size > MAX_BYTES:
            return text_result(
                f"File content ({size / 1024:.1f}KB) exceeds maximum allowed "
                f"size ({MAX_BYTES // 1024}KB). Use offset and limit "
                "parameters to read specific portions of the file, or search "
                "for specific content instead of reading the whole file.",
                True,
            )
        start = (offset or 1) - 1
        end = None if limit is None else start + limit
        lines = text_lines(text)[start:end]
        return text_result(
            "\n".join(
                f"{start + i + 1:>6}\t{line}" for i, line in enumerate(lines)
            )
        )

    async def write_tool(self, arguments):
        path = self.resolve(absolute_path_arg(arguments))
        content = string_arg(arguments, "content")
        async with self.lock:
            existed = self.write_text(path, content)
        if existed:
            return text_result(
                f"The file {path} has been updated successfully."
            )
        return text_result(f"File created successfully at: {path}")

    async def edit_tool(self, arguments):
        path = self.resolve(absolute_path_arg(arguments))
        old = string_arg(arguments, "old_string")
        new = string_arg(arguments, "new_string")
        replace_all = bool_arg(arguments, "replace_all")
        if old == new:
            raise UserError(
                "No changes to make: old_string and new_string are exactly the same."
            )
        async with self.lock:
            text = self.read_text(path)
            count = text.count(old)
            if count == 0:
                return text_result(
                    "String to replace not found in file.", True
                )
            if not replace_all and count > 1:
                return text_result(
                    f"Found {count} matches of the string to replace, but "
                    "replace_all is false. To replace all occurrences, set "
                    "replace_all to true. To replace only one occurrence, "
                    "please provide more context to uniquely identify the "
                    "instance.",
                    True,
                )
            self.write_text(path, text.replace(old, new))
        return text_result(f"The file {path} has been updated successfully.")


def takes_value(template):
    return any("{{value}}" in arg for arg in template)


def host_tool_schema(spec):
    properties = {}
    for name, arg in spec["arg"].items():
        if takes_value(arg["args"]):
            prop = {"type": "string"}
        else:
            prop = {"type": "boolean", "default": False}
        properties[name] = {**prop, "description": arg["description"]}
    if remainder := spec.get("args"):
        properties["args"] = {
            "type": "array",
            "items": {"type": "string"},
            "description": remainder["description"],
        }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def scalar(name, value):
    match value:
        case str():
            return value
        case int() | float() if not isinstance(value, bool):
            return json.dumps(value)
        case _:
            raise UserError(
                f"{name}: expected a string, got {json.dumps(value)}"
            )


def host_tool_argv(spec, arguments):
    argv = []
    for name, arg in spec["arg"].items():
        value = arguments.get(name)
        match takes_value(arg["args"]), value:
            case (_, None) | (False, False):
                pass
            case True, _:
                text = scalar(name, value)
                argv += [a.replace("{{value}}", text) for a in arg["args"]]
            case False, True:
                argv += arg["args"]
            case False, _:
                raise UserError(
                    f"{name}: expected a boolean, got {json.dumps(value)}"
                )
    if remainder := spec.get("args"):
        items = arguments.get("args")
        if items is not None and not isinstance(items, list):
            raise UserError(
                f"args: expected an array, got {json.dumps(items)}"
            )
        if items:
            argv += [*remainder["prefix"], *(scalar("args", i) for i in items)]
    return argv


def pr_args(host, org, repo, pr):
    return [f"--host={host}", f"--org={org}", f"--repo={repo}", f"--pr={pr}"]


def host_tool_handler(spec, session_id, base=list):
    async def handler(arguments):
        argv = host_tool_argv(spec, arguments)
        try:
            proc = await asyncio.create_subprocess_exec(
                str(SCRIPT),
                "--sandbox",
                f"--session={session_id}",
                spec["command"],
                *base(),
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return text_result(str(e), True)
        stdout, stderr = await proc.communicate()
        exit_code = proc.returncode if proc.returncode >= 0 else 1
        output = joined_output(
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            exit_code,
        )
        return text_result(output, exit_code != 0)

    return handler


class Session:
    def __init__(self, session_id, state, sandbox):
        self.session_id = session_id
        self.state = state
        self.sandbox = sandbox
        self.review = None

    def sandbox_tool(self, method):
        async def handler(arguments):
            return await method(self.sandbox, arguments)

        return handler

    def host_tool(self, spec):
        command = spec["command"]
        match command:
            case "start-review":
                return self.start_review(spec)
            case "finish-review":
                return self.finish_review(spec)
            case "read-standard":
                base = lambda: (
                    [] if self.review is None else pr_args(*self.review)
                )
            case "read-review":
                base = list
            case _ if command in STANDARDS_COMMANDS:
                base = list
            case _:
                base = self.review_args
        return host_tool_handler(spec, self.session_id, base)

    def review_args(self):
        if self.review is None:
            raise UserError("No review in progress. Call start_review first.")
        return pr_args(*self.review)

    def start_review(self, spec):
        async def handler(arguments):
            pr = scalar("pr", arguments.get("pr"))
            try:
                pr = int(pr)
            except ValueError:
                raise UserError(
                    f"pr: expected an integer, got {json.dumps(pr)}"
                )
            review = (
                string_arg(arguments, "host"),
                string_arg(arguments, "org"),
                string_arg(arguments, "repo"),
                pr,
            )
            review_dir(self.state, *review)
            result = await host_tool_handler(spec, self.session_id)(arguments)
            if not result.is_error:
                self.review = review
            return result

        return handler

    def finish_review(self, spec):
        async def handler(arguments):
            review = self.review
            result = await host_tool_handler(
                spec, self.session_id, self.review_args
            )(arguments)
            if self.review is review:
                self.review = None
            return result

        return handler


class Sessions:
    def __init__(self, data, standards):
        self.data = data
        self.standards = standards
        self.sessions = {}
        self.lock = asyncio.Lock()

    async def get(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            raise UserError("missing session_id")
        async with self.lock:
            if session_id not in self.sessions:
                state = session_dir(self.data, session_id)
                (state / PRS).mkdir(parents=True, exist_ok=True)
                sandbox = await Sandbox(state, self.standards).start()
                self.sessions[session_id] = Session(session_id, state, sandbox)
            return self.sessions[session_id]

    def tool(self, make):
        async def handler(arguments):
            arguments = dict(arguments)
            session = await self.get(arguments.pop("session_id", None))
            return await make(session)(arguments)

        return handler


def guarded(handler):
    async def run(arguments):
        try:
            return await handler(arguments)
        except Exception as e:
            return text_result(str(e), True)

    return run


def builtin_schema(title, properties, required):
    return {
        "$schema": JSON_SCHEMA,
        "properties": properties,
        "required": required,
        "title": title,
        "type": "object",
    }


def mcp_server(sessions):
    uint = {"format": "uint64", "minimum": 0, "type": ["integer", "null"]}
    tools = [
        SandboxTool(
            name="bash",
            description=(
                "Run a shell command. Standard output and standard error are "
                "returned together, followed by the exit code when it is "
                "nonzero. The bash and file tools share the same filesystem."
            ),
            parameters=builtin_schema(
                "BashArgs",
                {
                    "command": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["command", "description"],
            ),
            handler=guarded(
                sessions.tool(lambda s: s.sandbox_tool(Sandbox.bash_tool))
            ),
        ),
        SandboxTool(
            name="read",
            description=(
                "Read a text file with numbered lines. The path must be "
                "absolute. Use offset and limit to select a range of lines."
            ),
            parameters=builtin_schema(
                "ReadArgs",
                {
                    "file_path": {"type": "string"},
                    "limit": uint,
                    "offset": uint,
                },
                ["file_path"],
            ),
            handler=guarded(
                sessions.tool(lambda s: s.sandbox_tool(Sandbox.read_tool))
            ),
        ),
        SandboxTool(
            name="write",
            description=(
                "Write a text file. The path must be absolute, and missing "
                "parent directories are created automatically."
            ),
            parameters=builtin_schema(
                "WriteArgs",
                {
                    "content": {"type": "string"},
                    "file_path": {"type": "string"},
                },
                ["file_path", "content"],
            ),
            handler=guarded(
                sessions.tool(lambda s: s.sandbox_tool(Sandbox.write_tool))
            ),
        ),
        SandboxTool(
            name="edit",
            description=(
                "Replace exact text in a file. By default the old text must "
                "occur exactly once; set replace_all to replace every occurrence."
            ),
            parameters=builtin_schema(
                "EditArgs",
                {
                    "file_path": {"type": "string"},
                    "new_string": {"type": "string"},
                    "old_string": {"type": "string"},
                    "replace_all": {"default": False, "type": "boolean"},
                },
                ["file_path", "old_string", "new_string"],
            ),
            handler=guarded(
                sessions.tool(lambda s: s.sandbox_tool(Sandbox.edit_tool))
            ),
        ),
        *(
            SandboxTool(
                name=name,
                description=spec["description"],
                parameters=host_tool_schema(spec),
                handler=guarded(
                    sessions.tool(lambda s, spec=spec: s.host_tool(spec))
                ),
            )
            for name, spec in tool_specs().items()
        ),
    ]
    return fastmcp.FastMCP(
        name="bxwrp",
        instructions=INSTRUCTIONS,
        tools=tools,
        strict_input_validation=False,
    )


async def mcp(args):
    args.standards.mkdir(parents=True, exist_ok=True)
    server = mcp_server(Sessions(args.data, args.standards))

    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(signum, task.cancel)
    try:
        await server.run_async(transport="stdio", show_banner=False)
    except asyncio.CancelledError:
        pass
    return 0


async def export(git_dir, rev, dest):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = await git(git_dir, "archive", "--format=tar", rev, text=False)
    await run("tar", "-x", "-f", "-", "-C", str(dest), input=archive)


async def fetch(args):
    name = f"{args.host}/{args.org}/{args.repo}"
    git_dir = args.cache / args.host / args.org / f"{args.repo}.git"
    with locked(git_dir):
        if not git_dir.exists():
            tmp = git_dir.with_name(git_dir.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            await run(
                "gh",
                "repo",
                "clone",
                name,
                str(tmp),
                "--",
                "--bare",
                "--quiet",
            )
            tmp.rename(git_dir)
        target = (
            await run(
                "gh",
                "pr",
                "view",
                str(args.pr),
                "--repo",
                name,
                "--json",
                "baseRefName",
                "--jq",
                ".baseRefName",
            )
        ).strip()
        head_ref = f"refs/pr/{args.pr}/head"
        target_ref = f"refs/pr/{args.pr}/target"
        await git(
            git_dir,
            "fetch",
            "--quiet",
            "origin",
            f"+refs/pull/{args.pr}/head:{head_ref}",
            f"+refs/heads/{target}:{target_ref}",
        )
        head_sha, target_sha = (
            await git(git_dir, "rev-parse", head_ref, target_ref)
        ).split()
        merge_base = (
            await git(git_dir, "merge-base", head_sha, target_sha)
        ).strip()
    heads = {
        "head_sha": head_sha,
        "target": target,
        "target_sha": target_sha,
        "merge_base": merge_base,
    }
    return git_dir, heads


async def cmd_start_review(args):
    review = review_dir(args.state, args.host, args.org, args.repo, args.pr)
    with locked(review):
        git_dir, heads = await fetch(args)
        old = read_meta(review) or {}
        if all(old.get(k) == v for k, v in heads.items()):
            for name in (VIOLATIONS, REPORT):
                (review / name).unlink(missing_ok=True)
            dest = review
        else:
            dest = review.with_name(review.name + ".tmp")
            shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir()
            await export(git_dir, heads["head_sha"], dest / HEAD)
            await export(git_dir, heads["merge_base"], dest / BASE)
            diff = await git(
                git_dir,
                "diff",
                "--no-color",
                "--no-ext-diff",
                heads["merge_base"],
                heads["head_sha"],
                text=False,
            )
            (dest / DIFF).write_bytes(diff)
        write_meta(
            dest,
            {
                **heads,
                "status": "in_progress",
                "started": now(),
                "finished": None,
            },
        )
        if dest != review:
            shutil.rmtree(review, ignore_errors=True)
            dest.rename(review)
    if args.sandbox:
        review = HOME_DIR / review.relative_to(args.state)
    print(review / HEAD)
    print(f"{review / BASE} (merge base with {heads['target']})")
    print(review / DIFF)
    return 0


def started_review(args):
    review = review_dir(args.state, args.host, args.org, args.repo, args.pr)
    if read_meta(review) is None:
        raise UserError(
            f"No review of {args.host}/{args.org}/{args.repo} pull request "
            f"{args.pr}. Run start-review first."
        )
    return review


async def cmd_record_violation(args):
    review = started_review(args)
    repo = (review / HEAD).resolve()
    path = (repo / args.path).resolve()
    if not path.is_relative_to(repo) or not path.is_file():
        raise UserError("path is not a file in head")
    lines = len(path.read_text(errors="replace").splitlines())
    if not 1 <= args.line <= lines:
        raise UserError(
            f"line {args.line} is not in 1..{lines} of {args.path}"
        )
    record = {
        "rule": args.rule,
        "path": str(path.relative_to(repo)),
        "line": args.line,
        "reason": args.reason,
    }
    with locked(review), (review / VIOLATIONS).open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Recorded {record['path']}:{record['line']}")
    return 0


def read_violations(review):
    try:
        text = (review / VIOLATIONS).read_text()
    except FileNotFoundError:
        text = ""
    return [json.loads(line) for line in text.splitlines()]


def report(records):
    if not records:
        return "No violations."
    by_path = {}
    for r in sorted(records, key=lambda r: (r["path"], r["line"])):
        by_path.setdefault(r["path"], []).append(r)
    blocks = []
    for path, rs in by_path.items():
        lines = [f"**{path}**"]
        for r in rs:
            lines.append(f"- line {r['line']}: {r['rule']}")
            lines.append(f"  - {r['reason']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def cmd_finish_review(args):
    review = started_review(args)
    with locked(review):
        text = report(read_violations(review))
        safe_write_bytes(review / REPORT, (text + "\n").encode())
        meta = read_meta(review)
        write_meta(review, {**meta, "status": "done", "finished": now()})
    print_review(args, review)
    return 0


async def cmd_read_review(args):
    print_review(args, started_review(args))
    return 0


def print_review(args, review):
    with locked(review):
        meta = read_meta(review)
        records = read_violations(review)
    head = review / HEAD
    if args.sandbox:
        head = HOME_DIR / head.relative_to(args.state)
    front = {
        **meta,
        "host": args.host,
        "org": args.org,
        "repo": args.repo,
        "pr": args.pr,
        "head": str(head),
        "violations": len(records),
    }
    print("---")
    print(yaml.safe_dump(front, allow_unicode=True, sort_keys=True), end="")
    print("---")
    print()
    print(report(records))


def standards_root(args):
    return args.standards


def standards_files(args):
    root = standards_root(args)
    includes = [g for g in args.paths if not g.startswith("!")]
    excludes = [g[1:] for g in args.paths if g.startswith("!")]
    files = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if not path.is_file():
            continue
        if includes and not any(glob_match(rel, g) for g in includes):
            continue
        if any(glob_match(rel, g) for g in excludes):
            continue
        files.append((rel, path))
    files.sort(key=lambda f: str(f[0]).lower())
    if args.sort == "modified":
        files.sort(key=lambda f: f[1].stat().st_mtime, reverse=True)
    return files


async def cmd_list_standards(args):
    files = standards_files(args)
    print(
        "\n".join(str(pathlib.Path("/") / rel) for rel, _ in files)
        if files
        else "No files."
    )
    return 0


def repo_standards(args):
    root = standards_root(args)
    if None in (args.host, args.org, args.repo, args.pr):
        raise UserError(
            "No review in progress. Call start_review first, or pass path."
            if args.sandbox
            else "Pass --host, --org, --repo, and --pr, or --path."
        )
    files = []
    directory = (
        root
        / STANDARDS_REPOS
        / check_segments((args.host, args.org, args.repo))
    )
    while True:
        if directory.is_dir():
            files.extend(
                sorted(
                    (p for p in directory.glob("*.md") if p.is_file()),
                    key=lambda p: p.name.lower(),
                )
            )
        if directory == root:
            return files
        directory = directory.parent


async def cmd_read_standard(args):
    root = standards_root(args)
    if args.path is None:
        files = repo_standards(args)
        if not files:
            print("No files.")
            return 0
        text = "\n".join(
            f"==> /{path.relative_to(root)} <==\n{path.read_text()}"
            for path in files
        )
    else:
        rel = args.path.relative_to(args.path.anchor)
        path = (root / rel).resolve()
        if not path.is_file() and path.suffix != ".md":
            path = path.with_name(path.name + ".md")
        if not path.is_relative_to(root) or not path.is_file():
            raise UserError("path is not a standards file")
        text = path.read_text()
    lines = text.splitlines(keepends=True)
    end = None if args.limit is None else args.offset + args.limit
    sys.stdout.write("".join(lines[args.offset : end]))
    return 0


def glob_match(rel, pattern):
    pattern = pathlib.Path(pattern.strip("/"))
    return rel.is_relative_to(pattern) or fnmatch.fnmatchcase(
        str(rel), str(pattern)
    )


async def cmd_search_standards(args):
    root = standards_root(args)
    pattern = re.escape(args.pattern) if args.fixed else args.pattern
    flags = 0 if any(c.isupper() for c in args.pattern) else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        raise UserError(f"invalid pattern: {e}")

    out = []
    for rel, path in standards_files(args):
        name = str(pathlib.Path("/") / rel)
        match args.mode:
            case "path":
                if regex.search(str(rel)):
                    out.append(name)
            case "line":
                lines = path.read_text(errors="replace").splitlines()
                hits = [
                    i for i, line in enumerate(lines) if regex.search(line)
                ]
                if not hits:
                    continue
                if out:
                    out.append("--")
                shown = sorted(
                    {
                        j
                        for i in hits
                        for j in range(
                            max(0, i - args.context),
                            min(len(lines), i + args.context + 1),
                        )
                    }
                )
                for j in shown:
                    sep = ":" if j in hits else "-"
                    out.append(f"{name}{sep}{j + 1}{sep}{lines[j]}")
            case "file":
                lines = path.read_text(errors="replace").splitlines()
                if any(regex.search(line) for line in lines):
                    out.append(name)
            case "any":
                lines = path.read_text(errors="replace").splitlines()
                if regex.search(str(rel)) or any(
                    regex.search(line) for line in lines
                ):
                    out.append(name)
    print("\n".join(out) if out else "No matches.")
    return 0


def pr_parser(required):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", required=required, help="GitHub host")
    parser.add_argument(
        "--org",
        required=required,
        help="Organization or user that owns the repo",
    )
    parser.add_argument("--repo", required=required, help="Repository name")
    parser.add_argument(
        "--pr", required=required, type=int, help="Pull request number"
    )
    return parser


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Serve the review tools as a bxwrp MCP on stdio over the state dir",
    )
    parser.add_argument(
        "--sandbox", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--session",
        help="Session ID, as <session> or <session>/<agent>, whose state "
        "dir holds the pull requests",
    )
    commands = parser.add_subparsers(dest="command")

    review = pr_parser(required=True)

    commands.add_parser(
        "start-review",
        parents=[review],
        help="Write a pull request, its merge base, and their diff, and "
        "clear any earlier review of it",
    )

    record_violation_parser = commands.add_parser(
        "record-violation",
        parents=[review],
        help="Record one rule violation in the review's head",
    )
    record_violation_parser.add_argument(
        "--rule", required=True, help="Rule name"
    )
    record_violation_parser.add_argument(
        "--path", required=True, help="File path relative to head"
    )
    record_violation_parser.add_argument(
        "--line", required=True, type=int, help="Line number"
    )
    record_violation_parser.add_argument(
        "--reason", required=True, help="How the code breaks the rule"
    )

    commands.add_parser(
        "finish-review",
        parents=[review],
        help="Save the review report from the recorded violations",
    )

    commands.add_parser(
        "read-review",
        parents=[review],
        help="Print a review's metadata as YAML front matter and its "
        "violations",
    )

    list_standards_parser = commands.add_parser(
        "list-standards",
        help="List standards files by relative path",
    )
    list_standards_parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Paths to list; '!' prefix excludes",
    )
    list_standards_parser.add_argument(
        "--sort", default="path", choices=["path", "modified"]
    )

    read_standard_parser = commands.add_parser(
        "read-standard",
        parents=[pr_parser(required=False)],
        help="Read a standards file by relative path, or every standard "
        "for the pull request's repo",
    )
    read_standard_parser.add_argument(
        "--path",
        type=pathlib.Path,
        help="Relative path [default: every standard for the --host/--org/--repo "
        "pull request]",
    )
    read_standard_parser.add_argument(
        "--offset", default=0, type=int, help="First line, 0-based"
    )
    read_standard_parser.add_argument(
        "--limit", type=int, help="Maximum lines"
    )

    search_standards_parser = commands.add_parser(
        "search-standards",
        help="Find standards files by regular expression",
    )
    search_standards_parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Paths to search; '!' prefix excludes",
    )
    search_standards_parser.add_argument(
        "--pattern", default=".", help="Regular expression"
    )
    search_standards_parser.add_argument(
        "--mode", default="any", choices=["any", "line", "file", "path"]
    )
    search_standards_parser.add_argument(
        "--fixed", action="store_true", help="Match the pattern literally"
    )
    search_standards_parser.add_argument(
        "--context", default=1, type=int, help="Context lines in line mode"
    )
    search_standards_parser.add_argument(
        "--sort", default="path", choices=["path", "modified"]
    )

    args = parser.parse_args()
    if args.mcp == (args.command is not None):
        parser.error("pass either --mcp or a command")
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        parser.error("CLAUDE_PLUGIN_DATA is not set")
    data = pathlib.Path(data).resolve()
    args.data = data
    if args.session is not None:
        try:
            args.state = session_dir(data, args.session)
        except UserError as e:
            parser.error(f"--session: {e}")
    elif args.command in REVIEW_COMMANDS:
        parser.error(f"{args.command} requires --session")
    args.cache = data / "cache"
    args.standards = data / STANDARDS
    if args.mcp:
        return await mcp(args)
    match args.command:
        case "start-review":
            return await cmd_start_review(args)
        case "record-violation":
            return await cmd_record_violation(args)
        case "finish-review":
            return await cmd_finish_review(args)
        case "read-review":
            return await cmd_read_review(args)
        case "list-standards":
            return await cmd_list_standards(args)
        case "read-standard":
            return await cmd_read_standard(args)
        case "search-standards":
            return await cmd_search_standards(args)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except (UserError, ProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
