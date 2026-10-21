#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     'bashkit>=0.18.2,<0.19',
#     'fastmcp>=4,<5',
#     'pydantic>=2,<3',
#     'pyyaml>=6,<7',
# ]
# ///
import argparse
import asyncio
import collections.abc
import datetime
import fnmatch
import json
import os
import pathlib
import re
import secrets
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

PREPARED = "prepared"
GIT_DIR = "repo.git"
HEAD = "head"
BASE = "base"
DIFF = "diff.txt"
USERNAME = "agent"
HOME_DIR = pathlib.PurePosixPath("/sandbox")
SCRATCH_DIR = pathlib.PurePosixPath("/tmp")
REVIEW_HEAD = HOME_DIR / HEAD
REVIEW_BASE = HOME_DIR / BASE
REVIEW_DIFF = HOME_DIR / DIFF
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
    "Sandbox for PR review. Call start_github_review for a pull request "
    "or start_local_review for two revisions of a local git dir; it "
    f"mounts the head at {REVIEW_HEAD}, the base at "
    f"{REVIEW_BASE}, and the full diff between them at {REVIEW_DIFF}. "
    f"{HOME_DIR} is read-only; {SCRATCH_DIR} is writable scratch space "
    "that never leaves the sandbox. The bash, read, write, and edit tools "
    "work only between the start and finish_review or cancel_review. "
    f"Standards files are in {STANDARDS_DIR}. List them with "
    "list_standards, read them with read_standard, and find them with "
    "search_standards. read_standard without a path, after the start, "
    "reads every standard that applies to the reviewed repo. Call "
    "record_violation once per violation, with path relative to head, then "
    "finish_review. Call cancel_review to end a review that cannot be "
    "finished."
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


class GithubSource(pydantic.BaseModel):
    kind: typing.Literal["github"] = "github"
    host: str
    org: str
    repo: str
    pr: int
    head_sha: str
    target: str
    target_sha: str
    merge_base: str

    def base_label(self) -> str:
        return f"merge base with {self.target}"


class LocalSource(pydantic.BaseModel):
    kind: typing.Literal["local"] = "local"
    git_dir: pathlib.Path
    base_rev: str
    head_rev: str
    base_commit: str
    head_commit: str

    def base_label(self) -> str:
        return self.base_rev


class Violation(pydantic.BaseModel):
    rule: str
    path: str
    line: int
    reason: str


class ReviewResult(pydantic.BaseModel):
    session: str
    started: datetime.datetime
    finished: datetime.datetime
    violations: list[Violation]


def now():
    return datetime.datetime.now(datetime.UTC)


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
                        "args": [f"--{name.replace('_', '-')}={{{{value}}}}"],
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
        "start_github_review": tool(
            None,
            "Start the review of a pull request: clone it, then mount its "
            f"head at {REVIEW_HEAD}, its merge base with the target branch "
            f"at {REVIEW_BASE}, and the diff between them at {REVIEW_DIFF}. "
            "Fails while this session has a review in progress.",
            pr="Pull request number",
        ),
        "start_local_review": tool(
            None,
            "Start the review of two revisions of a git dir on the host: "
            f"mount the head at {REVIEW_HEAD}, the base at {REVIEW_BASE}, "
            f"and the diff between them at {REVIEW_DIFF}. Fails while this "
            "session has a review in progress.",
            repo=False,
            git_dir="Path of the git dir on the host",
            base="Revision to compare from",
            head="Revision to review",
        ),
        "record_violation": tool(
            None,
            "Record one rule violation in the started review's head",
            repo=False,
            rule="Name of the rule the code breaks",
            path="File path relative to head",
            line="Line number of the violation",
            reason="One sentence on how the code breaks the rule",
        ),
        "finish_review": tool(
            None,
            "Finish the review: print a token for read_review. Ends the "
            "sandbox and deletes the prepared files.",
            repo=False,
        ),
        "cancel_review": tool(
            None,
            "Cancel the review: end the sandbox and delete the prepared "
            "files without a token.",
            repo=False,
        ),
        "read_review": tool(
            None,
            "Read the finished review of a token: its metadata as YAML "
            "front matter, then its violations grouped by file.",
            repo=False,
            token="Token from finish_review",
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
            "Read standards. Without path, after the start: every "
            "standard that applies to the reviewed repo, concatenated with "
            "a '==> /path <==' header per file. For a pull request that is "
            f"every .md file in {STANDARDS_REPOS}/<host>/<org>/<repo> and in "
            "each parent directory up to and including the top; for a local "
            "review, every .md file in the top only. That result is "
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
    def __init__(self, prepared, standards):
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
            bashkit.FileSystem.real(str(prepared), writable=False),
            read_only=True,
        )
        if standards.is_dir():
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


def host_tool_handler(spec, base=list):
    async def handler(arguments):
        argv = host_tool_argv(spec, arguments)
        try:
            proc = await asyncio.create_subprocess_exec(
                str(SCRIPT),
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


def int_arg(arguments, name):
    value = scalar(name, arguments.get(name))
    try:
        return int(value)
    except ValueError:
        raise UserError(
            f"{name}: expected an integer, got {json.dumps(value)}"
        )


class ActiveReview:
    def __init__(
        self,
        source: GithubSource | LocalSource,
        tmpdir: tempfile.TemporaryDirectory,
        sandbox: Sandbox,
    ):
        self.source = source
        self.tmpdir = tmpdir
        self.sandbox = sandbox
        self.started = now()
        self.violations: list[Violation] = []

    @property
    def prepared(self) -> pathlib.Path:
        return pathlib.Path(self.tmpdir.name) / PREPARED


class Session:
    def __init__(self, session_id, standards, reviews):
        self.session_id = session_id
        self.standards = standards
        self.reviews = reviews
        self.lock = asyncio.Lock()
        self.active: ActiveReview | None = None

    def require_active(self) -> ActiveReview:
        if self.active is None:
            raise UserError(
                "No review in progress. Call start_github_review or "
                "start_local_review first."
            )
        return self.active

    def sandbox_tool(self, method):
        async def handler(arguments):
            return await method(self.require_active().sandbox, arguments)

        return handler

    def host_tool(self, name, spec):
        match name:
            case "start_github_review":
                return self.start_github_review
            case "start_local_review":
                return self.start_local_review
            case "record_violation":
                return self.record_violation
            case "finish_review":
                return self.finish_review
            case "cancel_review":
                return self.cancel_review
            case "read_review":
                return self.read_review
            case "read_standard":
                return self.read_standard(
                    host_tool_handler(spec, self.standards_args)
                )
            case _:
                return host_tool_handler(spec)

    def read_standard(self, handler):
        async def run(arguments):
            if arguments.get("path") is None:
                self.require_active()
            return await handler(arguments)

        return run

    def standards_args(self):
        match self.active:
            case ActiveReview(source=GithubSource() as source):
                return [
                    f"--host={source.host}",
                    f"--org={source.org}",
                    f"--repo={source.repo}",
                ]
            case _:
                return []

    async def start_github_review(self, arguments):
        host = string_arg(arguments, "host")
        org = string_arg(arguments, "org")
        repo = string_arg(arguments, "repo")
        pr = int_arg(arguments, "pr")
        check_segments((host, org, repo))
        return await self.start(
            lambda root: prepare_github_review(root, host, org, repo, pr)
        )

    async def start_local_review(self, arguments):
        git_dir = pathlib.Path(string_arg(arguments, "git_dir"))
        base = string_arg(arguments, "base")
        head = string_arg(arguments, "head")
        return await self.start(
            lambda root: prepare_local_review(root, git_dir, base, head)
        )

    async def start(self, prepare):
        async with self.lock:
            if self.active is not None:
                raise UserError(
                    "Review in progress. Call finish_review or "
                    "cancel_review first."
                )
            tmpdir = tempfile.TemporaryDirectory(prefix="code-review-")
            try:
                root = pathlib.Path(tmpdir.name)
                source = await prepare(root)
                sandbox = await Sandbox(
                    root / PREPARED, self.standards
                ).start()
            except BaseException:
                tmpdir.cleanup()
                raise
            self.active = ActiveReview(source, tmpdir, sandbox)
        return text_result(
            "\n".join(
                (
                    str(REVIEW_HEAD),
                    f"{REVIEW_BASE} ({source.base_label()})",
                    str(REVIEW_DIFF),
                )
            )
        )

    async def record_violation(self, arguments):
        rule = string_arg(arguments, "rule")
        path = string_arg(arguments, "path")
        line = int_arg(arguments, "line")
        reason = string_arg(arguments, "reason")
        async with self.lock:
            active = self.require_active()
            head = (active.prepared / HEAD).resolve()
            file = (head / path).resolve()
            if not file.is_relative_to(head) or not file.is_file():
                raise UserError("path is not a file in head")
            lines = len(file.read_text(errors="replace").splitlines())
            if not 1 <= line <= lines:
                raise UserError(f"line {line} is not in 1..{lines} of {path}")
            violation = Violation(
                rule=rule,
                path=str(file.relative_to(head)),
                line=line,
                reason=reason,
            )
            active.violations.append(violation)
        return text_result(f"Recorded {violation.path}:{violation.line}")

    async def finish_review(self, arguments):
        async with self.lock:
            active = self.require_active()
            result = ReviewResult(
                session=self.session_id,
                started=active.started,
                finished=now(),
                violations=active.violations,
            )
            self.active = None
            active.tmpdir.cleanup()
        token = secrets.token_urlsafe(16)
        self.reviews[token] = review_text(active.source, result)
        return text_result(token)

    async def cancel_review(self, arguments):
        async with self.lock:
            active = self.require_active()
            self.active = None
            active.tmpdir.cleanup()
        return text_result("Review cancelled.")

    async def read_review(self, arguments):
        token = string_arg(arguments, "token")
        try:
            return text_result(self.reviews[token])
        except KeyError:
            raise UserError(f"unknown token {token}")

    def close(self):
        if self.active is not None:
            self.active.tmpdir.cleanup()
            self.active = None


class Sessions:
    def __init__(self, standards):
        self.standards = standards
        self.reviews: dict[str, str] = {}
        self.sessions = {}
        self.lock = asyncio.Lock()

    async def get(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            raise UserError("missing session_id")
        async with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = Session(
                    session_id, self.standards, self.reviews
                )
            return self.sessions[session_id]

    def tool(self, make):
        async def handler(arguments):
            arguments = dict(arguments)
            session = await self.get(arguments.pop("session_id", None))
            return await make(session)(arguments)

        return handler

    def close(self):
        for session in self.sessions.values():
            session.close()


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
                    sessions.tool(
                        lambda s, name=name, spec=spec: s.host_tool(name, spec)
                    )
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
    sessions = Sessions(args.standards)
    server = mcp_server(sessions)

    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGHUP):
        loop.add_signal_handler(signum, task.cancel)
    try:
        await server.run_async(transport="stdio", show_banner=False)
    except asyncio.CancelledError:
        pass
    finally:
        sessions.close()
    return 0


async def export(git_dir, rev, dest):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = await git(git_dir, "archive", "--format=tar", rev, text=False)
    await run("tar", "-x", "-f", "-", "-C", str(dest), input=archive)


async def fetch(git_dir, host, org, repo, pr):
    name = f"{host}/{org}/{repo}"
    await run(
        "gh",
        "repo",
        "clone",
        name,
        str(git_dir),
        "--",
        "--bare",
        "--quiet",
    )
    target = (
        await run(
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            name,
            "--json",
            "baseRefName",
            "--jq",
            ".baseRefName",
        )
    ).strip()
    head_ref = f"refs/pr/{pr}/head"
    target_ref = f"refs/pr/{pr}/target"
    await git(
        git_dir,
        "fetch",
        "--quiet",
        "origin",
        f"+refs/pull/{pr}/head:{head_ref}",
        f"+refs/heads/{target}:{target_ref}",
    )
    head_sha, target_sha = (
        await git(git_dir, "rev-parse", head_ref, target_ref)
    ).split()
    merge_base = (
        await git(git_dir, "merge-base", head_sha, target_sha)
    ).strip()
    return GithubSource(
        host=host,
        org=org,
        repo=repo,
        pr=pr,
        head_sha=head_sha,
        target=target,
        target_sha=target_sha,
        merge_base=merge_base,
    )


async def export_review(
    git_dir: pathlib.Path, base: str, head: str, prepared: pathlib.Path
) -> None:
    await export(git_dir, head, prepared / HEAD)
    await export(git_dir, base, prepared / BASE)
    diff = await git(
        git_dir,
        "diff",
        "--no-color",
        "--no-ext-diff",
        base,
        head,
        text=False,
    )
    (prepared / DIFF).write_bytes(diff)


async def prepare_github_review(
    root: pathlib.Path, host: str, org: str, repo: str, pr: int
) -> GithubSource:
    git_dir = root / GIT_DIR
    source = await fetch(git_dir, host, org, repo, pr)
    await export_review(
        git_dir, source.merge_base, source.head_sha, root / PREPARED
    )
    return source


async def prepare_local_review(
    root: pathlib.Path, git_dir: pathlib.Path, base: str, head: str
) -> LocalSource:
    git_dir = git_dir.resolve()
    base_commit, head_commit = [
        (
            await git(
                git_dir,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{rev}^{{commit}}",
            )
        ).strip()
        for rev in (base, head)
    ]
    await export_review(git_dir, base_commit, head_commit, root / PREPARED)
    return LocalSource(
        git_dir=git_dir,
        base_rev=base,
        head_rev=head,
        base_commit=base_commit,
        head_commit=head_commit,
    )


def report(violations: list[Violation]) -> str:
    if not violations:
        return "No violations."
    by_path: dict[str, list[Violation]] = {}
    for v in sorted(violations, key=lambda v: (v.path, v.line)):
        by_path.setdefault(v.path, []).append(v)
    blocks = []
    for path, vs in by_path.items():
        lines = [f"**{path}**"]
        for v in vs:
            lines.append(f"- line {v.line}: {v.rule}")
            lines.append(f"  - {v.reason}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def review_text(
    source: GithubSource | LocalSource, result: ReviewResult
) -> str:
    front = {
        **source.model_dump(mode="json"),
        **result.model_dump(mode="json", exclude={"violations"}),
        "violations": len(result.violations),
    }
    return "\n".join(
        (
            "---",
            yaml.safe_dump(front, allow_unicode=True, sort_keys=True).rstrip(
                "\n"
            ),
            "---",
            "",
            report(result.violations),
        )
    )


def standards_root(args):
    root = args.standards
    if not any(p.is_file() for p in root.rglob("*.md")):
        raise UserError("no standards files")
    return root


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
    directory = root
    if args.host is not None:
        directory /= STANDARDS_REPOS / check_segments(
            (args.host, args.org, args.repo)
        )
    files = []
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


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Serve the review tools as a bxwrp MCP on stdio over the data dir",
    )
    commands = parser.add_subparsers(dest="command")

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
        help="Read a standards file by relative path, or every standard "
        "for a repo",
    )
    read_standard_parser.add_argument("--host", help="GitHub host")
    read_standard_parser.add_argument(
        "--org", help="Organization or user that owns the repo"
    )
    read_standard_parser.add_argument("--repo", help="Repository name")
    read_standard_parser.add_argument(
        "--path",
        type=pathlib.Path,
        help="Relative path [default: every standard for --host, --org, "
        "and --repo, or every standard in the top without them]",
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
    if args.command == "read-standard":
        repo_args = (args.host, args.org, args.repo)
        if any(a is not None for a in repo_args) and None in repo_args:
            parser.error("pass --host, --org, and --repo together")
    standards = os.environ.get("STANDARDS_DIR")
    if standards:
        args.standards = pathlib.Path(standards).resolve()
    else:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        if not data:
            parser.error("set STANDARDS_DIR or CLAUDE_PLUGIN_DATA")
        args.standards = pathlib.Path(data).resolve() / STANDARDS
    if args.mcp:
        return await mcp(args)
    match args.command:
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
