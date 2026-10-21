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
import contextlib
import datetime
import fcntl
import fnmatch
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import sys
import typing

import bashkit
import fastmcp
import fastmcp.tools
import mcp.types as mcp_types
import pydantic
import pydantic.json_schema
import yaml

SCRIPT = pathlib.Path(__file__).resolve()

TOKENS = "tokens"
PREPARED = "prepared"
REVIEWS = "reviews"
SOURCE = "source.json"
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
    "Sandbox for PR review. Call start_review with the token you were "
    f"given; it mounts the head at {REVIEW_HEAD}, the base at "
    f"{REVIEW_BASE}, and the full diff between them at {REVIEW_DIFF}. "
    f"{HOME_DIR} is read-only; {SCRATCH_DIR} is writable scratch space "
    "that never leaves the sandbox. The bash, read, write, and edit tools "
    "work only between start_review and finish_review. "
    f"Standards files are in {STANDARDS_DIR}. List them with "
    "list_standards, read them with read_standard, and find them with "
    "search_standards. read_standard without a path, after start_review, "
    "reads every standard that applies to the reviewed repo. Call "
    "record_violation once per violation, with path relative to head, then "
    "finish_review."
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

    def standards_dir(self, root: pathlib.Path) -> pathlib.Path:
        return (
            root
            / STANDARDS_REPOS
            / check_segments((self.host, self.org, self.repo))
        )


class LocalSource(pydantic.BaseModel):
    kind: typing.Literal["local"] = "local"
    git_dir: pathlib.Path
    base_rev: str
    head_rev: str
    base_commit: str
    head_commit: str

    def base_label(self) -> str:
        return self.base_rev

    def standards_dir(self, root: pathlib.Path) -> pathlib.Path:
        return root


Source = typing.Annotated[
    GithubSource | LocalSource, pydantic.Field(discriminator="kind")
]
SOURCE_ADAPTER: pydantic.TypeAdapter[GithubSource | LocalSource] = (
    pydantic.TypeAdapter(Source)
)


class Violation(pydantic.BaseModel):
    rule: str
    path: str
    line: int
    reason: str


class ReviewResult(pydantic.BaseModel):
    token: str
    session: str
    started: datetime.datetime
    finished: datetime.datetime
    violations: list[Violation]


class Review(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True)

    token: str

    def token_dir(self, tokens: pathlib.Path) -> pathlib.Path:
        return tokens / check_segments((self.token,))

    def prepared(self, tokens: pathlib.Path) -> pathlib.Path:
        return self.token_dir(tokens) / PREPARED

    def source(self, tokens: pathlib.Path) -> GithubSource | LocalSource:
        try:
            text = (self.token_dir(tokens) / SOURCE).read_text()
        except FileNotFoundError:
            raise UserError(f"unknown {self}")
        return SOURCE_ADAPTER.validate_json(text)

    def save(self, tokens: pathlib.Path, result: ReviewResult) -> None:
        reviews = self.token_dir(tokens) / REVIEWS
        reviews.mkdir(exist_ok=True)
        name = result.finished.strftime("%Y%m%dT%H%M%S.%fZ") + ".json"
        with (reviews / name).open("x") as f:
            f.write(json_dumps(result.model_dump(mode="json")) + "\n")

    def latest(self, tokens: pathlib.Path) -> ReviewResult:
        paths = sorted((self.token_dir(tokens) / REVIEWS).glob("*.json"))
        if not paths:
            raise UserError(f"No finished review of {self}.")
        return ReviewResult.model_validate_json(paths[-1].read_text())

    def __str__(self) -> str:
        return f"token {self.token}"


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def now():
    return datetime.datetime.now(datetime.UTC)


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


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
        "prepare_github_review": tool(
            "prepare-github-review",
            "Prepare a review of a pull request: its head, its merge base "
            "with the target branch, and the diff between them. Print a "
            "token for start_review. The review is prepared now; later "
            "pushes do not change it.",
            pr="Pull request number",
        ),
        "prepare_local_review": tool(
            "prepare-local-review",
            "Prepare a review of two revisions of a git dir on the host, "
            "then print a token for start_review. The review is prepared "
            "now; later changes to the git dir do not change it.",
            repo=False,
            git_dir="Path of the git dir on the host",
            base="Revision to compare from",
            head="Revision to review",
        ),
        "start_review": tool(
            None,
            f"Start the review of a token: mount its head at {REVIEW_HEAD}, "
            f"its base at {REVIEW_BASE}, and the diff between them at "
            f"{REVIEW_DIFF}. Fails while this session has a review in "
            "progress.",
            repo=False,
            token="Token from prepare_github_review or prepare_local_review",
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
            "Finish the review: save it, then print it exactly as "
            "read_review does. Ends the sandbox.",
            repo=False,
        ),
        "read_review": tool(
            None,
            "Read the most recent finished review of a token: its metadata "
            "as YAML front matter, then its violations grouped by file.",
            repo=False,
            token="Token of the review",
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
                "--sandbox",
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
        review: Review,
        source: GithubSource | LocalSource,
        sandbox: Sandbox,
    ):
        self.review = review
        self.source = source
        self.sandbox = sandbox
        self.started = now()
        self.violations: list[Violation] = []


class Session:
    def __init__(self, session_id, tokens, standards):
        self.session_id = session_id
        self.tokens = tokens
        self.standards = standards
        self.lock = asyncio.Lock()
        self.active: ActiveReview | None = None

    def require_active(self) -> ActiveReview:
        if self.active is None:
            raise UserError("No review in progress. Call start_review first.")
        return self.active

    def sandbox_tool(self, method):
        async def handler(arguments):
            return await method(self.require_active().sandbox, arguments)

        return handler

    def host_tool(self, name, spec):
        match name:
            case "start_review":
                return self.start_review
            case "record_violation":
                return self.record_violation
            case "finish_review":
                return self.finish_review
            case "read_review":
                return self.read_review
            case "read_standard":
                return host_tool_handler(spec, self.standards_args)
            case _:
                return host_tool_handler(spec)

    def standards_args(self):
        if self.active is None:
            return []
        return [f"--token={self.active.review.token}"]

    async def start_review(self, arguments):
        review = Review(token=string_arg(arguments, "token"))
        async with self.lock:
            if self.active is not None:
                raise UserError(
                    f"Review of {self.active.review} in progress. Call "
                    "finish_review first."
                )
            source = review.source(self.tokens)
            sandbox = await Sandbox(
                review.prepared(self.tokens), self.standards
            ).start()
            self.active = ActiveReview(review, source, sandbox)
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
            head = (active.review.prepared(self.tokens) / HEAD).resolve()
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
                token=active.review.token,
                session=self.session_id,
                started=active.started,
                finished=now(),
                violations=active.violations,
            )
            active.review.save(self.tokens, result)
            self.active = None
        return text_result(review_text(active.source, result))

    async def read_review(self, arguments):
        review = Review(token=string_arg(arguments, "token"))
        source = review.source(self.tokens)
        return text_result(review_text(source, review.latest(self.tokens)))


class Sessions:
    def __init__(self, tokens, standards):
        self.tokens = tokens
        self.standards = standards
        self.sessions = {}
        self.lock = asyncio.Lock()

    async def get(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            raise UserError("missing session_id")
        async with self.lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = Session(
                    session_id, self.tokens, self.standards
                )
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
    args.standards.mkdir(parents=True, exist_ok=True)
    server = mcp_server(Sessions(args.tokens, args.standards))

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


async def prepare_review(
    tokens: pathlib.Path,
    git_dir: pathlib.Path,
    base: str,
    head: str,
    source: GithubSource | LocalSource,
) -> str:
    token = secrets.token_urlsafe(16)
    dest = tokens / token
    tmp = dest.with_name(dest.name + ".tmp")
    prepared = tmp / PREPARED
    prepared.mkdir(parents=True)
    try:
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
        (tmp / SOURCE).write_text(
            json_dumps(source.model_dump(mode="json")) + "\n"
        )
        tmp.rename(dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return token


async def cmd_prepare_github_review(args):
    check_segments((args.host, args.org, args.repo))
    git_dir, heads = await fetch(args)
    source = GithubSource(
        host=args.host, org=args.org, repo=args.repo, pr=args.pr, **heads
    )
    print(
        await prepare_review(
            args.tokens,
            git_dir,
            heads["merge_base"],
            heads["head_sha"],
            source,
        )
    )
    return 0


async def cmd_prepare_local_review(args):
    git_dir = args.git_dir.resolve()
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
        for rev in (args.base, args.head)
    ]
    source = LocalSource(
        git_dir=git_dir,
        base_rev=args.base,
        head_rev=args.head,
        base_commit=base_commit,
        head_commit=head_commit,
    )
    print(
        await prepare_review(
            args.tokens, git_dir, base_commit, head_commit, source
        )
    )
    return 0


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
    if args.review is None:
        raise UserError(
            "No review in progress. Call start_review first, or pass path."
            if args.sandbox
            else "Pass --token or --path."
        )
    directory = args.review.source(args.tokens).standards_dir(root)
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
    parser.add_argument(
        "--sandbox", action="store_true", help=argparse.SUPPRESS
    )
    commands = parser.add_subparsers(dest="command")

    prepare_github_review_parser = commands.add_parser(
        "prepare-github-review",
        help="Prepare a review of a pull request and print a token for "
        "start-review",
    )
    prepare_github_review_parser.add_argument(
        "--host", required=True, help="GitHub host"
    )
    prepare_github_review_parser.add_argument(
        "--org",
        required=True,
        help="Organization or user that owns the repo",
    )
    prepare_github_review_parser.add_argument(
        "--repo", required=True, help="Repository name"
    )
    prepare_github_review_parser.add_argument(
        "--pr", required=True, type=int, help="Pull request number"
    )

    prepare_local_review_parser = commands.add_parser(
        "prepare-local-review",
        help="Prepare a review of two revisions of a git dir and print a "
        "token for start-review",
    )
    prepare_local_review_parser.add_argument(
        "--git-dir", required=True, type=pathlib.Path, help="Git dir"
    )
    prepare_local_review_parser.add_argument(
        "--base", required=True, help="Revision to compare from"
    )
    prepare_local_review_parser.add_argument(
        "--head", required=True, help="Revision to review"
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
        help="Read a standards file by relative path, or every standard "
        "for the token's repo",
    )
    read_standard_parser.add_argument(
        "--token",
        help="Token from prepare-github-review or prepare-local-review",
    )
    read_standard_parser.add_argument(
        "--path",
        type=pathlib.Path,
        help="Relative path [default: every standard for the --token review]",
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
    if "token" in vars(args):
        args.review = None if args.token is None else Review(token=args.token)
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        parser.error("CLAUDE_PLUGIN_DATA is not set")
    data = pathlib.Path(data).resolve()
    args.cache = data / "cache"
    args.tokens = data / TOKENS
    args.standards = data / STANDARDS
    if args.mcp:
        return await mcp(args)
    match args.command:
        case "prepare-github-review":
            return await cmd_prepare_github_review(args)
        case "prepare-local-review":
            return await cmd_prepare_local_review(args)
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
