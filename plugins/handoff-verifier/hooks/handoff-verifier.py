#!/usr/bin/env python3
"""Run handoff-verifier submit/stop/plan/ask hooks and serve their MCP management server."""

import argparse
import json
import os
import pathlib
import secrets
import subprocess
import sys
import urllib.parse

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


def prepare_env(session):
    """Populate the env vars Store reads so manual subcommands work outside the harness:
    derive CLAUDE_PLUGIN_DATA from CLAUDE_CONFIG_DIR (or ~/.claude) when unset, force the
    session id from the caller. Project stays cwd, which Store already derives."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(
        pathlib.Path.home() / ".claude"
    )
    os.environ.setdefault(
        "CLAUDE_PLUGIN_DATA",
        str(pathlib.Path(config_dir) / "plugins" / "data" / PLUGIN_DATA_DIR),
    )
    os.environ["CLAUDE_CODE_SESSION_ID"] = session or ""


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

    def __init__(self):
        plugin_data = pathlib.Path(os.environ["CLAUDE_PLUGIN_DATA"])
        session = os.environ["CLAUDE_CODE_SESSION_ID"]
        project = urllib.parse.quote(str(pathlib.Path.cwd()), safe="")
        context = plugin_data / "context"
        self.dirs = {
            self.GLOBAL: context / "global",
            self.PROJECT: context / "project" / project,
            self.SESSION: context / "session" / session,
        }
        self.state_dir = plugin_data / "state" / "session" / session
        for directory in (*self.dirs.values(), self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _encode(event, tool):
        return ".".join(part for part in (event, tool) if part)

    @staticmethod
    def _decode(stem):
        event, _, tool = stem.partition(".")
        return {"event": event, **({"tool": tool} if tool else {})}

    def _file(self, scope, event, tool):
        return self.dirs[scope] / f"{self._encode(event, tool)}{self._SUFFIX}"

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

    def get_context(self, event, tool=None, scope=None):
        if scope is None:
            return "\n".join(
                text
                for s in self.SCOPES
                if (text := self.get_context(event, tool, s))
            )
        try:
            return self._file(scope, event, tool).read_text().strip()
        except FileNotFoundError:
            return ""

    def set_context(self, scope, data, event, tool=None):
        data = data.strip()
        path = self._file(scope, event, tool)
        if data:
            path.write_text(data + "\n")
        else:
            path.unlink(missing_ok=True)

    def list_context(self):
        return {
            scope: [
                self._decode(p.stem)
                for p in directory.iterdir()
                if p.suffix == self._SUFFIX
            ]
            for scope, directory in self.dirs.items()
        }


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
            text = self.store.get_context(event, tool, scope)
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

    def __init__(self, store):
        self.store = (
            store  # register() runs inside super().__init__, so set first
        )
        super().__init__("handoff-verifier")

    def register(self):
        self.register_tool(
            "list",
            (
                "List every active verifier across all scopes — use this whenever the user "
                "asks what handoff verifiers are on ('are any verifiers active?', 'list my "
                "handoff verifiers', 'what's set for this project / globally?'). Returns each "
                "scope with the modes set there. Takes no arguments."
            ),
            {"type": "object", "properties": {}},
            self._list,
        )
        self.register_tool(
            "read",
            (
                "Read a verifier's full text for one (scope, mode); errors if it is not set. "
                "Use list first to see what exists, then read the specific combination whose "
                "text you need."
            ),
            {
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                },
                "required": ["scope", "mode"],
            },
            self._read,
        )
        self.register_tool(
            "write",
            (
                "Set or replace a verifier — use this to add/turn on a stop reminder, plan "
                "gate, or ask gate ('remind yourself to run tests before finishing', 'gate "
                "plan mode so you double-check', 'add an ask verifier so you try first'). "
                "Overwrites the WHOLE verifier, so pass the full text, not a fragment; for a "
                "small tweak to existing text use edit instead. Empty or whitespace-only "
                "content DELETES (turns off) the verifier — this is how you disable one."
            ),
            {
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
                    "content": {
                        "type": "string",
                        "description": "Full verifier text; empty disables the mode.",
                    },
                },
                "required": ["mode", "content"],
            },
            self._write,
        )
        self.register_tool(
            "edit",
            (
                "Exact-string replace within an existing verifier — like the native Edit "
                "tool, but addressed by (scope, mode) instead of a file path. Use it to "
                "tweak existing text ('soften the global stop reminder', 'add a line to the "
                "project plan gate') without rewriting the whole thing. old_string must be "
                "present and unique unless replace_all is set."
            ),
            {
                "type": "object",
                "properties": {
                    "scope": self.SCOPE_PROP,
                    "mode": self.MODE_PROP,
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
                "required": ["mode", "old_string", "new_string"],
            },
            self._edit,
        )
        self.register_tool(
            "confirm",
            (
                "Confirm you have satisfied a plan or ask gate's constraints, using the token "
                "shown in the gate's denial message. Call this only AFTER the gated tool "
                "(ExitPlanMode or AskUserQuestion) has been blocked and shown its constraints "
                "and token, and only once you genuinely comply. Unlocks exactly one retry of "
                "that gated call."
            ),
            {
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
            self._confirm,
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

    def _list(self, arguments):
        return self.do_list()

    def _read(self, arguments):
        scope, mode, key = self._resolve(arguments, require_scope=True)
        return self.do_read(scope, mode, key)

    def _write(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_write(scope, mode, key, arguments.get("content", ""))

    def _edit(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_edit(
            scope,
            mode,
            key,
            arguments.get("old_string", ""),
            arguments.get("new_string", ""),
            bool(arguments.get("replace_all")),
        )

    def _confirm(self, arguments):
        scope, mode, key = self._resolve(arguments)
        return self.do_confirm(mode, key, arguments.get("token", ""))

    def do_list(self):
        listing = self.store.list_context()
        lines = []
        for scope in Store.SCOPES:
            entries = listing.get(scope, [])
            if entries:
                modes = ", ".join(sorted(mode_name(e) for e in entries))
                lines.append(f"{scope}: {modes}")
        return "\n".join(lines) if lines else "no verifiers set"

    def do_read(self, scope, mode, key):
        text = self.store.get_context(scope=scope, **key)
        if not text:
            raise UserError(f"no {mode} verifier at {scope} scope")
        return text

    def do_write(self, scope, mode, key, content):
        if not content.strip():
            if not self.store.get_context(scope=scope, **key):
                return f"no {mode} verifier at {scope} scope to remove"
            self.store.set_context(scope, "", **key)
            return f"removed {mode} verifier at {scope} scope"
        self.store.set_context(scope, content, **key)
        return f"wrote {mode} verifier at {scope} scope"

    def do_edit(self, scope, mode, key, old_string, new_string, replace_all):
        if not old_string:
            raise UserError("old_string must not be empty")
        if old_string == new_string:
            raise UserError("old_string and new_string are identical")
        text = self.store.get_context(scope=scope, **key)
        if not text:
            raise UserError(f"no {mode} verifier at {scope} scope")
        count = text.count(old_string)
        if count == 0:
            raise UserError(f"old_string not found in {scope} {mode} verifier")
        if count > 1 and not replace_all:
            raise UserError(
                f"old_string is not unique in {scope} {mode} verifier "
                f"({count} matches); pass replace_all to replace every match"
            )
        self.store.set_context(
            scope, text.replace(old_string, new_string), **key
        )
        return f"edited {mode} verifier at {scope} scope"

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
    HookRunner(Store()).run(json.load(sys.stdin))


def cmd_mcp(args):
    VerifierMcpServer(Store()).serve()


def cmd_edit(args):
    editor = os.environ.get("EDITOR")
    if not editor:
        raise UserError("EDITOR is not set")
    if args.scope == Store.SESSION and not args.session:
        raise UserError("--session is required to edit the session scope")
    prepare_env(args.session)
    directory = Store().dirs[args.scope]
    subprocess.run([editor, str(directory)], check=True)


def cmd_add(args):
    if args.scope == Store.SESSION and not args.session:
        raise UserError("--session is required to add to the session scope")
    prepare_env(args.session)
    key = MODES[args.mode]
    store = Store()
    existing = store.get_context(scope=args.scope, **key)
    store.set_context(
        args.scope,
        f"{existing}\n{args.text}" if existing else args.text,
        **key,
    )


def cmd_list(args):
    prepare_env(args.session)
    listing = Store().list_context()
    lines = []
    for scope in Store.SCOPES:
        entries = listing.get(scope, [])
        if entries:
            modes = ", ".join(sorted(mode_name(e) for e in entries))
            lines.append(f"{scope}: {modes}")
    print("\n".join(lines) if lines else "no verifiers set")


def cmd_clear(args):
    if args.scope == Store.SESSION and not args.session:
        raise UserError("--session is required to clear the session scope")
    prepare_env(args.session)
    key = MODES[args.mode]
    store = Store()
    if not store.get_context(scope=args.scope, **key):
        print(f"no {args.mode} verifier at {args.scope} scope")
        return
    store.set_context(args.scope, "", **key)
    print(f"cleared {args.mode} verifier at {args.scope} scope")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="{hook,mcp,list,edit,add,clear}"
    )
    subparsers.add_parser("hook")  # invoked by hooks.json
    subparsers.add_parser("mcp")  # invoked as an MCP stdio server
    show = subparsers.add_parser("list")  # list active verifiers across scopes
    show.add_argument(
        "--session", help="session id; include the session scope's verifiers"
    )
    edit = subparsers.add_parser("edit")  # open a scope's verifiers in $EDITOR
    edit.add_argument("scope", choices=list(Store.SCOPES))
    edit.add_argument(
        "--session", help="session id; required when scope is session"
    )
    add = subparsers.add_parser("add")  # append a line to one scope's verifier
    add.add_argument("scope", choices=list(Store.SCOPES))
    add.add_argument("mode", choices=list(MODES))
    add.add_argument("text")
    add.add_argument(
        "--session", help="session id; required when scope is session"
    )
    clear = subparsers.add_parser(
        "clear"
    )  # remove one scope's verifier for a mode
    clear.add_argument("scope", choices=list(Store.SCOPES))
    clear.add_argument("mode", choices=list(MODES))
    clear.add_argument(
        "--session", help="session id; required when scope is session"
    )

    args = parser.parse_args()
    match args.command:
        case "hook":
            cmd_hook(args)
        case "mcp":
            cmd_mcp(args)
        case "list":
            cmd_list(args)
        case "edit":
            cmd_edit(args)
        case "add":
            cmd_add(args)
        case "clear":
            cmd_clear(args)


if __name__ == "__main__":
    try:
        main()
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
