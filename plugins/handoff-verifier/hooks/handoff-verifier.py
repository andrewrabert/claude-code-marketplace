#!/usr/bin/env python3
"""Run handoff-verifier submit/stop/plan/ask hooks and serve their MCP management server."""

import argparse
import asyncio
import base64
import json
import os
import pathlib
import secrets
import sys

# Friendly presets the MCP tools expose, each mapped to the (event, tool) tuple the generic
# Store and hook actually key on. Only the MCP layer consults this; the hook matches blindly.
MODES = {
    "submit": {"event": "UserPromptSubmit"},
    "stop": {"event": "Stop"},
    "plan": {"event": "PreToolUse", "tool": "ExitPlanMode"},
    "ask": {"event": "PreToolUse", "tool": "AskUserQuestion"},
}
GATE_MODES = tuple(mode for mode, key in MODES.items() if "tool" in key)


def mode_name(entry):
    """Name the friendly MODES mode for a stored {event, tool} entry, else its tool/event."""
    for mode, key in MODES.items():
        if key == entry:
            return mode
    return entry.get("tool", entry["event"])


# Constant install path under the Claude config dir; the harness sets CLAUDE_PLUGIN_DATA
# to exactly this, and the manual edit/add subcommands reconstruct it when it is unset.
PLUGIN_DATA_DIR = "handoff-verifier-andrewrabert-marketplace"


def prepare_env():
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(
        pathlib.Path.home() / ".claude"
    )
    os.environ.setdefault(
        "CLAUDE_PLUGIN_DATA",
        str(pathlib.Path(config_dir) / "plugins" / "data" / PLUGIN_DATA_DIR),
    )


def resolve_session(explicit=None):
    return explicit or os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def resolve_project(explicit=None):
    # Kept absolute so an explicit relative --project still keys to the same
    # base64 the hook recorded from its (absolute) cwd.
    path = (
        pathlib.Path(explicit).absolute() if explicit else pathlib.Path.cwd()
    )
    return base64.urlsafe_b64encode(str(path).encode()).decode()


class ClaudeCode:
    @staticmethod
    async def session_ids(cwd=None):
        cwd = str(cwd or pathlib.Path.cwd())
        try:
            process = await asyncio.create_subprocess_exec(
                "claude",
                "agents",
                "--json",
                "--cwd",
                cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await process.communicate()
        except OSError:
            return []
        if process.returncode:
            return []
        try:
            sessions = json.loads(stdout)
        except json.JSONDecodeError:
            return []
        return sorted({s["sessionId"] for s in sessions if s.get("sessionId")})


async def pick_session(explicit, required):
    if explicit:
        return explicit
    ids = await ClaudeCode.session_ids()
    match ids:
        case [only]:
            return only
        case _ if not required:
            return None
        case []:
            raise UserError(
                "no active Claude session in this directory; pass --session ID"
            )
        case _:
            listing = "\n".join(f"  {i}" for i in ids)
            raise UserError(
                "multiple active Claude sessions in this directory; "
                f"pass --session ID to choose one:\n{listing}"
            )


class UserError(Exception):
    pass


class Store:
    """Disk scope dirs; get/set/list a (scope, event, tool)."""

    GLOBAL = "global"
    PROJECT = "project"
    SESSION = "session"
    # Scopes the hook concatenates and the MCP tools expose, broad->narrow.
    SCOPES = (GLOBAL, PROJECT, SESSION)
    _SUFFIX = ".md"

    def __init__(self, session, project):
        plugin_data = pathlib.Path(os.environ["CLAUDE_PLUGIN_DATA"])
        context = plugin_data / "context"
        self.dirs = {
            self.GLOBAL: context / "global",
            self.PROJECT: context / "project" / project,
            self.SESSION: context / "session" / session,
        }
        self.state_dir = plugin_data / "state" / "session" / session
        for directory in (*self.dirs.values(), self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for scope in self.dirs:
            for key in MODES.values():
                self._dir(scope, **key).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _encode(event, tool):
        return ".".join(part for part in (event, tool) if part)

    @staticmethod
    def _decode(stem):
        event, _, tool = stem.partition(".")
        return {"event": event, **({"tool": tool} if tool else {})}

    def _dir(self, scope, event, tool=None):
        return self.dirs[scope] / self._encode(event, tool)

    def _entry_files(self, scope, event, tool=None):
        directory = self._dir(scope, event, tool)
        try:
            return sorted(
                (p for p in directory.iterdir() if p.suffix == self._SUFFIX),
                key=lambda p: p.name,
            )
        except FileNotFoundError:
            return []

    def _token_path(self, event, tool=None):
        return self.state_dir / f"{self._encode(event, tool)}.token"

    def get_token(self, event, tool=None):
        path = self._token_path(event, tool)
        try:
            return json.loads(path.read_text())["token"]
        except FileNotFoundError:
            token = secrets.token_hex(8)
            path.write_text(json.dumps({"token": token, "verified": False}))
            return token

    def confirm_token(self, token, event, tool=None):
        path = self._token_path(event, tool)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return False
        if not token or data["token"] != token:
            return False
        path.write_text(json.dumps({"token": token, "verified": True}))
        return True

    def is_token_verified(self, event, tool=None):
        path = self._token_path(event, tool)
        try:
            return json.loads(path.read_text())["verified"]
        except FileNotFoundError:
            return False

    def clear_token(self, event, tool=None):
        self._token_path(event, tool).unlink(missing_ok=True)

    def _load(self, scope, event, tool=None):
        return [
            p.read_text().strip()
            for p in self._entry_files(scope, event, tool)
        ]

    def _auto_name(self, directory):
        n = 0
        while (directory / f"{n}{self._SUFFIX}").exists():
            n += 1
        return f"{n}{self._SUFFIX}"

    @staticmethod
    def _check_index(entries, index):
        if not entries:
            raise UserError("no entries")
        if not isinstance(index, int) or index < 0 or index >= len(entries):
            raise UserError(
                f"index {index} out of range (0..{len(entries) - 1})"
            )

    def entries(self, scope, event, tool=None):
        return self._load(scope, event, tool)

    def add_entry(self, scope, text, event, tool=None):
        text = text.strip()
        if not text:
            raise UserError("entry text must not be empty")
        directory = self._dir(scope, event, tool)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / self._auto_name(directory)).write_text(text + "\n")

    def replace_entry(self, scope, index, text, event, tool=None):
        text = text.strip()
        if not text:
            raise UserError("entry text must not be empty")
        files = self._entry_files(scope, event, tool)
        self._check_index(files, index)
        files[index].write_text(text + "\n")

    def remove_entry(self, scope, index, event, tool=None):
        files = self._entry_files(scope, event, tool)
        self._check_index(files, index)
        files[index].unlink()
        return self._load(scope, event, tool)

    def clear_context(self, scope, event, tool=None):
        for path in self._entry_files(scope, event, tool):
            path.unlink()

    def joined(self, event, tool=None, scope=None):
        if scope is None:
            return "\n\n".join(
                text
                for s in self.SCOPES
                if (text := self.joined(event, tool, s))
            )
        return "\n\n".join(self._load(scope, event, tool))

    def list_context(self):
        out = {}
        for scope, directory in self.dirs.items():
            items = []
            for p in directory.iterdir():
                if not p.is_dir():
                    continue
                key = self._decode(p.name)
                count = len(self._entry_files(scope, **key))
                if count:
                    items.append({"key": key, "count": count})
            out[scope] = items
        return out


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def dump_context(store):
    listing = store.list_context()
    out = {}
    for scope in Store.SCOPES:
        for item in listing.get(scope, []):
            key = item["key"]
            entries = store.entries(scope, **key)
            out.setdefault(mode_name(key), {}).update(
                {f"{scope}/{i}": text for i, text in enumerate(entries)}
            )
    return out


class HookRunner:
    """Generic hook handler: matches verifiers by (event, tool) and emits the right shape.

    Stop -> a block decision carrying the concatenated reminders. PreToolUse -> a deny
    decision plus a session gate the confirm tool must clear before the call is retried.
    """

    def __init__(self, store):
        self.store = store

    def run(self, data):
        event = data.get("hook_event_name")
        tool = data.get("tool_name")
        match event:
            case "UserPromptSubmit":
                self.context(event, tool)
            case "Stop":
                if not data.get("stop_hook_active"):
                    self.block(event, tool)
            case "PreToolUse":
                self.deny(event, tool)

    def texts(self, event, tool):
        out = []
        for scope in Store.SCOPES:
            text = self.store.joined(event, tool, scope)
            if text:
                out.append(text)
        return out

    def context(self, event, tool):
        texts = self.texts(event, tool)
        if texts:
            json.dump(
                {
                    "suppressOutput": True,
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": "\n\n".join(texts),
                    },
                },
                sys.stdout,
            )

    def block(self, event, tool):
        texts = self.texts(event, tool)
        if texts:
            json.dump(
                {
                    "decision": "block",
                    "reason": "\n\n".join(texts),
                    "suppressOutput": True,
                },
                sys.stdout,
            )

    def deny(self, event, tool):
        texts = self.texts(event, tool)
        if not texts:
            return
        if self.store.is_token_verified(event, tool):
            self.store.clear_token(event, tool)
            return
        token = self.store.get_token(event, tool)
        reason = "\n\n".join(texts) + "\n\n" + self.proceed(tool, token)
        json.dump(
            {
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            },
            sys.stdout,
        )

    @staticmethod
    def proceed(tool, token):
        return (
            "TO PROCEED: only after you have audited every constraint above and judge ZERO "
            "violations remain, call the `mcp__handoff-verifier__confirm` tool with token "
            f'"{token}" to confirm this {tool} gate. That confirmation unlocks exactly one '
            f"{tool} call — retry {tool} immediately after. Do not confirm while any "
            "constraint is still violated."
        )


class McpStdioServer:
    """Reusable JSON-RPC-over-stdio MCP server. Subclass, implement register() to
    declare tools via register_tool(), and set TOOL_ERROR to the exception handlers
    raise for user-facing failures. All MCP protocol — framing, lifecycle, response
    envelope, tool-descriptor shape — lives here; subclasses hold only app logic."""

    PROTOCOL_VERSION = "2025-06-18"
    TOOL_ERROR = Exception  # handlers raise this for a user-facing tool error

    def __init__(self, name, version="1"):
        self.server_info = {"name": name, "version": version}
        self._tools = {}
        self.register()

    def register(self):
        """Override: declare tools by calling register_tool() once per tool."""
        raise NotImplementedError

    def register_tool(self, name, description, input_schema, handler):
        """Register one MCP tool. handler(arguments) -> str. MCP envelope shape lives here."""
        self._tools[name] = {
            "descriptor": {
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            },
            "handler": handler,
        }

    @staticmethod
    def send(message):
        sys.stdout.write(f"{json.dumps(message)}\n")
        sys.stdout.flush()

    def dispatch(self, name, arguments):
        """Return the text result for a tools/call; raise TOOL_ERROR on failure."""
        tool = self._tools.get(name)
        if tool is None:
            raise self.TOOL_ERROR(f"unknown tool: {name}")
        return tool["handler"](arguments or {})

    def handle(self, message):
        method = message.get("method")
        rid = message.get("id")
        if (
            method is None or rid is None
        ):  # response or notification: nothing to reply
            return

        response = {
            "jsonrpc": "2.0",
            "id": rid,
        }

        match method:
            case "initialize":
                params = message.get("params") or {}
                response["result"] = {
                    "protocolVersion": params.get(
                        "protocolVersion", self.PROTOCOL_VERSION
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": self.server_info,
                }
            case "tools/list":
                response["result"] = {
                    "tools": [t["descriptor"] for t in self._tools.values()]
                }
            case "tools/call":
                params = message.get("params") or {}
                try:
                    text = self.dispatch(
                        params.get("name"), params.get("arguments")
                    )
                    response["result"] = {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    }
                except self.TOOL_ERROR as error:
                    response["result"] = {
                        "content": [
                            {"type": "text", "text": f"error: {error}"}
                        ],
                        "isError": True,
                    }
            case "ping":
                response["result"] = {}
            case _:
                response["error"] = {
                    "code": -32601,
                    "message": f"method not found: {method}",
                }
        self.send(response)

    def serve(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.handle(message)


class VerifierMcpServer(McpStdioServer):
    """Maps the verifier list/read/write/edit/confirm tools onto a Store.

    Tools speak the friendly `mode` enum (stop/plan/ask); this layer translates each mode
    to the (event, tool) tuple the Store keys on via MODES.
    """

    TOOL_ERROR = UserError

    SCOPE_PROP = {
        "type": "string",
        "enum": list(Store.SCOPES),
        "description": (
            "Where the verifier lives. global = every project on this machine; project = "
            "this project on this machine, persisting across sessions (stored outside the "
            "repo, so it is NOT shared with collaborators or committed); session = this "
            "session only, vanishes when it ends. The hook concatenates the active scopes "
            "broad->narrow (global, then project, then session). "
            "DEFAULTS TO session, and session is the only safe default: its blast radius is "
            "zero and a wrong guess costs nothing, whereas project and global persist and are "
            "messy to discover and undo. Use a broader scope ONLY on an explicit instruction "
            "— project for 'for this project / across my sessions here', global for 'all my "
            "projects / everywhere on this machine'. Do NOT infer breadth from tone, "
            "repetition, or words like 'always'; 'always remind yourself' still means session "
            "unless they say where."
        ),
    }
    MODE_PROP = {
        "type": "string",
        "enum": list(MODES),
        "description": (
            "Which self-check. submit = a reminder injected each time you submit a prompt, at "
            "the start of a turn (the mirror of stop). stop = a reminder fed back when Claude "
            "finishes a turn, forcing one more reasoning turn before the turn ends. plan = a "
            "gate that blocks "
            "ExitPlanMode until the agent self-certifies via the confirm tool. ask = a gate "
            "that blocks AskUserQuestion the same way, forcing a real attempt before "
            "interrupting the user."
        ),
    }
    INDEX_PROP = {
        "type": "integer",
        "description": (
            "Zero-based position of the entry, as shown by read/list. Indices are "
            "EPHEMERAL — they renumber whenever an entry is removed. Re-read the "
            "verifier before targeting an index, and make one mutation at a time."
        ),
    }

    def __init__(self, store):
        self.store = (
            store  # register() runs inside super().__init__, so set first
        )
        super().__init__("handoff-verifier")

    def register(self):
        self.register_tool(
            name="list",
            description=(
                "List every active verifier across all scopes — use this whenever the user "
                "asks what handoff verifiers are on ('are any verifiers active?', 'list my "
                "handoff verifiers', 'what's set for this project / globally?'). Returns JSON "
                '{mode: {"scope/index": text}} with the full text of every entry, so you can '
                "read and target entries by their scope/index. Takes no arguments."
            ),
            input_schema={"type": "object", "properties": {}},
            handler=self._list,
        )
        self.register_tool(
            name="read",
            description=(
                "Read a verifier's entries for one (scope, mode); errors if it is not set. "
                "Returns each entry on its own line prefixed by its current index "
                "(`0: ...`). Use those indices to target edit/remove. Use list first to see "
                "what exists, then read the specific combination whose entries you need."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                },
                "required": ["scope", "mode"],
            },
            handler=self._read,
        )
        self.register_tool(
            name="write",
            description=(
                "Append a new entry to a verifier — use this to add a stop reminder, plan "
                "gate, or ask gate ('remind yourself to run tests before finishing', 'gate "
                "plan mode so you double-check', 'add an ask verifier so you try first'). "
                "Each entry is independent; the hook joins all entries for the mode. Creates "
                "the verifier if it does not exist. Returns the new entry's index and the "
                "re-numbered list. To change existing text use edit; to delete use remove."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                    "content": {
                        "type": "string",
                        "description": "Text of the entry to append; must not be empty.",
                    },
                },
                "required": ["mode", "content"],
            },
            handler=self._write,
        )
        self.register_tool(
            name="edit",
            description=(
                "Exact-string replace within a single verifier entry — like the native Edit "
                "tool, but addressed by (scope, mode, index) instead of a file path. Use it "
                "to tweak existing text ('soften the global stop reminder') without "
                "rewriting it. old_string must be present and unique within that entry "
                "unless replace_all is set. Re-read first: indices renumber after a remove."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                    "index": self.INDEX_PROP,
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to replace; must be unique unless replace_all.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence (default false).",
                    },
                },
                "required": ["mode", "index", "old_string", "new_string"],
            },
            handler=self._edit,
        )
        self.register_tool(
            name="remove",
            description=(
                "Remove a single entry from a verifier, addressed by (scope, mode, index). "
                "Use list/read to see current indices first. Returns the re-numbered list; "
                "removing the last entry turns the verifier off entirely. Indices are "
                "ephemeral — remove one entry at a time and re-read before the next."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                    "index": self.INDEX_PROP,
                },
                "required": ["mode", "index"],
            },
            handler=self._remove,
        )
        self.register_tool(
            name="confirm",
            description=(
                "Confirm you have satisfied a plan or ask gate's constraints, using the token "
                "shown in the gate's denial message. Call this only AFTER the gated tool "
                "(ExitPlanMode or AskUserQuestion) has been blocked and shown its constraints "
                "and token, and only once you genuinely comply. Unlocks exactly one retry of "
                "that gated call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": list(GATE_MODES),
                        "description": "plan (ExitPlanMode gate) or ask (AskUserQuestion gate).",
                    },
                    "token": {
                        "type": "string",
                        "description": (
                            "The token shown in the gate's denial message. Proves you saw "
                            "this specific gate; a stale or wrong token is rejected."
                        ),
                    },
                },
                "required": ["mode", "token"],
            },
            handler=self._confirm,
        )

    def _resolve(self, arguments, require_scope=False):
        """Resolve (scope, mode, key) from raw tool arguments, validating each."""
        if require_scope and not arguments.get("scope"):
            raise UserError("read requires scope")
        scope = arguments.get("scope") or Store.SESSION
        if scope not in Store.SCOPES:
            raise UserError(f"unknown scope: {scope!r}")
        mode = arguments.get("mode")
        if mode not in MODES:
            raise UserError(f"unknown mode: {mode!r}")
        return scope, mode, MODES[mode]

    @staticmethod
    def _index(arguments):
        index = arguments.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise UserError("index must be an integer")
        return index

    def _list(self, arguments):
        return self.do_list()

    def _read(self, arguments):
        scope, mode, key = self._resolve(arguments, require_scope=True)
        return self.do_read(scope=scope, mode=mode, key=key)

    def _write(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_write(
            scope=scope,
            mode=mode,
            key=key,
            content=arguments.get("content", ""),
        )

    def _edit(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_edit(
            scope=scope,
            mode=mode,
            key=key,
            index=self._index(arguments),
            old_string=arguments.get("old_string", ""),
            new_string=arguments.get("new_string", ""),
            replace_all=bool(arguments.get("replace_all")),
        )

    def _remove(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_remove(
            scope=scope, mode=mode, key=key, index=self._index(arguments)
        )

    def _confirm(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_confirm(
            mode=mode, key=key, token=arguments.get("token", "")
        )

    @staticmethod
    def _render(entries):
        return "\n".join(f"{i}: {text}" for i, text in enumerate(entries))

    def do_list(self):
        return json_dumps(dump_context(self.store))

    def do_read(self, scope, mode, key):
        entries = self.store.entries(scope, **key)
        if not entries:
            raise UserError(f"no {mode} verifier at {scope} scope")
        return self._render(entries)

    def do_write(self, scope, mode, key, content):
        if not content.strip():
            raise UserError("content must not be empty")
        self.store.add_entry(scope, content, **key)
        entries = self.store.entries(scope, **key)
        return f"added {mode} entry at {scope} scope\n{self._render(entries)}"

    def do_edit(
        self, scope, mode, key, index, old_string, new_string, replace_all
    ):
        if not old_string:
            raise UserError("old_string must not be empty")
        if old_string == new_string:
            raise UserError("old_string and new_string are identical")
        entries = self.store.entries(scope, **key)
        Store._check_index(entries, index)
        text = entries[index]
        count = text.count(old_string)
        if count == 0:
            raise UserError(
                f"old_string not found in {scope} {mode} entry {index}"
            )
        if count > 1 and not replace_all:
            raise UserError(
                f"old_string is not unique in {scope} {mode} entry {index} "
                f"({count} matches); pass replace_all to replace every match"
            )
        new_text = text.replace(old_string, new_string)
        self.store.replace_entry(
            scope=scope, index=index, text=new_text, **key
        )
        return f"edited {mode} entry {index} at {scope} scope\n{index}: {new_text}"

    def do_remove(self, scope, mode, key, index):
        entries = self.store.remove_entry(scope, index, **key)
        if not entries:
            return (
                f"removed {mode} entry {index} at {scope} scope — "
                "verifier now empty"
            )
        return (
            f"removed {mode} entry {index} at {scope} scope\n"
            f"{self._render(entries)}"
        )

    def do_confirm(self, mode, key, token):
        if "tool" not in key:
            raise UserError(
                f"confirm applies to {' or '.join(GATE_MODES)} (got {mode!r})"
            )
        if not self.store.confirm_token(token, **key):
            raise UserError(
                f"no matching pending {mode} verification — make the gated call first so its "
                "constraints and token are shown, then confirm with that exact token"
            )
        return f"{mode} verification confirmed — now retry your call once"


def cmd_hook(args):
    HookRunner(Store(resolve_session(), resolve_project())).run(
        json.load(sys.stdin)
    )


def cmd_mcp(args):
    VerifierMcpServer(Store(resolve_session(), resolve_project())).serve()


async def cmd_edit(args):
    editor = os.environ.get("EDITOR")
    if not editor:
        raise UserError("EDITOR is not set")
    session = await pick_session(args.session, args.scope == Store.SESSION)
    prepare_env()
    directory = Store(
        resolve_session(session), resolve_project(args.project)
    ).dirs[args.scope]
    process = await asyncio.create_subprocess_exec(editor, str(directory))
    await process.wait()
    if process.returncode:
        raise UserError(f"editor exited with status {process.returncode}")


async def cmd_add(args):
    session = await pick_session(args.session, args.scope == Store.SESSION)
    text = args.text
    if text is None:
        if sys.stdin.isatty():
            raise UserError(
                "text is required (pass an argument or pipe via stdin)"
            )
        text = sys.stdin.read()
    prepare_env()
    key = MODES[args.mode]
    Store(resolve_session(session), resolve_project(args.project)).add_entry(
        args.scope, text, **key
    )
    print(f"added {args.mode} entry at {args.scope} scope")


async def cmd_ls(args):
    session = await pick_session(args.session, required=False)
    prepare_env()
    print(
        json_dumps(
            dump_context(
                Store(resolve_session(session), resolve_project(args.project))
            )
        )
    )


async def cmd_path(args):
    session = await pick_session(args.session, args.scope == Store.SESSION)
    prepare_env()
    print(
        Store(resolve_session(session), resolve_project(args.project)).dirs[
            args.scope
        ]
    )


async def cmd_clear(args):
    session = await pick_session(args.session, args.scope == Store.SESSION)
    prepare_env()
    key = MODES[args.mode]
    store = Store(resolve_session(session), resolve_project(args.project))
    if not store.entries(args.scope, **key):
        print(f"no {args.mode} verifier at {args.scope} scope")
        return
    if args.index is not None:
        store.remove_entry(args.scope, args.index, **key)
        print(f"removed {args.mode} entry {args.index} at {args.scope} scope")
    else:
        store.clear_context(args.scope, **key)
        print(f"cleared {args.mode} verifier at {args.scope} scope")


def add_scope_argument(subparser):
    subparser.add_argument(
        "-s",
        "--scope",
        choices=list(Store.SCOPES),
        required=True,
        help="verifier scope to act on",
    )


def add_session_argument(subparser):
    subparser.add_argument(
        "--session",
        metavar="ID",
        help="session id; auto-resolved from this directory if omitted",
    )


def add_project_argument(subparser):
    subparser.add_argument(
        "-p",
        "--project",
        metavar="DIR",
        help="project directory; defaults to the current directory",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{hook,mcp,ls,path,edit,add,clear}",
    )
    subparsers.add_parser(
        "hook", help="run as a Claude Code hook (invoked by hooks.json)"
    )
    subparsers.add_parser("mcp", help="run as an MCP stdio server")
    show = subparsers.add_parser(
        "ls", help="list active verifiers across scopes"
    )
    add_session_argument(show)
    add_project_argument(show)
    path = subparsers.add_parser(
        "path", help="print the filesystem path of a scope's verifiers"
    )
    add_scope_argument(path)
    add_session_argument(path)
    add_project_argument(path)
    edit = subparsers.add_parser(
        "edit", help="open a scope's verifiers in $EDITOR"
    )
    add_scope_argument(edit)
    add_session_argument(edit)
    add_project_argument(edit)
    add = subparsers.add_parser(
        "add", help="append an entry to one scope's verifier"
    )
    add_scope_argument(add)
    add.add_argument("mode", choices=list(MODES))
    add.add_argument(
        "text", nargs="?", help="entry text; read from stdin if omitted"
    )
    add_session_argument(add)
    add_project_argument(add)
    clear = subparsers.add_parser(
        "clear", help="remove one scope's verifier for a mode"
    )
    add_scope_argument(clear)
    clear.add_argument("mode", choices=list(MODES))
    clear.add_argument(
        "--index",
        type=int,
        help="entry index to remove; omit to clear the whole mode",
    )
    add_session_argument(clear)
    add_project_argument(clear)

    args = parser.parse_args()
    match args.command:
        case "hook":
            cmd_hook(args)
        case "mcp":
            cmd_mcp(args)
        case "ls":
            asyncio.run(cmd_ls(args))
        case "path":
            asyncio.run(cmd_path(args))
        case "edit":
            asyncio.run(cmd_edit(args))
        case "add":
            asyncio.run(cmd_add(args))
        case "clear":
            asyncio.run(cmd_clear(args))


if __name__ == "__main__":
    try:
        main()
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
