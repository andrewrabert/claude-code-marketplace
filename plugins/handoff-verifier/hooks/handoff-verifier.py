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
import tempfile
import uuid

# Friendly presets the MCP tools expose, each mapped to the (event, tool) tuple the generic
# Store and hook actually key on. Only the MCP layer consults this; the hook matches blindly.
# The cross-cutting bucket: its own folder, merged into every real hook event at runtime
# rather than duplicated into each mode. Default target for add/import when no -m is given.
ALL_MODE = "all"
MODES = {
    "submit": {"event": "UserPromptSubmit"},
    "stop": {"event": "Stop"},
    "plan": {"event": "PreToolUse", "tool": "ExitPlanMode"},
    "ask": {"event": "PreToolUse", "tool": "AskUserQuestion"},
    # Hookless: bound to no Claude hook, so it never fires at runtime; its entries
    # exist only to be fanned out by generate-workflow.
    "verify": None,
    # Applies to every mode; merged into each event's read at runtime (see Store.joined).
    ALL_MODE: None,
}
GATE_MODES = tuple(
    mode for mode, key in MODES.items() if key and "tool" in key
)


def mode_key(mode):
    """Store addressing for a mode; a hookless (None) mode keys on its own name."""
    return MODES[mode] or {"event": mode}


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
    if explicit:
        path = pathlib.Path(explicit).absolute()
    elif env := os.environ.get("CLAUDE_PROJECT_DIR", ""):
        # use exactly as provided
        path = pathlib.Path(env)
    else:
        path = pathlib.Path.cwd().absolute()
    return base64.urlsafe_b64encode(str(path).encode()).decode()


class ClaudeCode:
    @staticmethod
    async def sessions(cwd=None):
        # cwd=None lists active sessions across ALL directories; pass a cwd to
        # restrict to that directory. Returns {sessionId: cwd}.
        args = ["--cwd", str(cwd)] if cwd is not None else []
        try:
            process = await asyncio.create_subprocess_exec(
                "claude",
                "agents",
                "--json",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await process.communicate()
        except OSError:
            return {}
        if process.returncode:
            return {}
        try:
            sessions = json.loads(stdout)
        except json.JSONDecodeError:
            return {}
        return {
            s["sessionId"]: s.get("cwd", "")
            for s in sessions
            if s.get("sessionId")
        }

    @staticmethod
    async def session_ids(cwd=None):
        return sorted(await ClaudeCode.sessions(cwd=cwd))


def tilde(path):
    if not path:
        return path
    try:
        return f"~/{pathlib.Path(path).relative_to(pathlib.Path.home())}"
    except ValueError:
        return path


def session_lines(ids, dirs):
    # Sort by (path, id); sessions in the current dir (shown as $PWD) sort first.
    cwd = str(pathlib.Path.cwd())

    def render(i):
        path = dirs.get(i, "")
        return "$PWD" if path == cwd else tilde(path)

    ordered = sorted(
        ids, key=lambda i: (dirs.get(i, "") != cwd, dirs.get(i, ""), i)
    )
    return [f"  {i}  {render(i)}" for i in ordered]


async def pick_session(explicit, required):
    if explicit:
        # A prefix matches active sessions in ANY directory.
        dirs = await ClaudeCode.sessions()
        matches = [i for i in sorted(dirs) if i.startswith(explicit)]
        match matches:
            case [only]:
                return only
            case []:
                raise UserError(
                    f"no active Claude session matches --session prefix {explicit!r}"
                )
            case _:
                listing = "\n".join(session_lines(matches, dirs))
                raise UserError(
                    "multiple active Claude sessions match --session prefix "
                    f"{explicit!r}; pass a longer prefix:\n{listing}"
                )
    # Automatic resolution stays scoped to this directory.
    ids = await ClaudeCode.session_ids(cwd=pathlib.Path.cwd())
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
            dirs = await ClaudeCode.sessions()
            listing = "\n".join(session_lines(dirs, dirs))
            raise UserError(
                "multiple active Claude sessions in this directory; "
                f"pass --session ID to choose one:\n{listing}"
            )


class UserError(Exception):
    pass


def all_files(*paths, suffix=None):
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
    if suffix is not None:
        files = {path for path in files if path.suffix.lower() == suffix}
    return sorted(files)


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
        self.session = session
        self._state_root = plugin_data / "state" / "session"
        self.state_dir = self._state_root / session
        for directory in (*self.dirs.values(), self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for scope in self.dirs:
            for mode in MODES:
                self._dir(scope, **mode_key(mode)).mkdir(
                    parents=True, exist_ok=True
                )

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

    def issue_token(self, event, tool=None):
        path = self._token_path(event, tool)
        try:
            return json.loads(path.read_text())["token"]
        except FileNotFoundError:
            # The session-hex prefix lets confirm locate this file without knowing
            # its own (possibly different) session; the hex part keeps it secret.
            token = f"{uuid.UUID(self.session).hex}:{secrets.token_hex(8)}"
            path.write_text(json.dumps({"token": token, "verified": False}))
            return token

    def confirm_token(self, token, event, tool=None):
        try:
            session = str(uuid.UUID(token.partition(":")[0]))
        except ValueError:
            return False
        path = (
            self._state_root / session / f"{self._encode(event, tool)}.token"
        )
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return False
        if data["token"] != token:
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

    def _stem(self, name):
        stem = name.strip()
        if stem.endswith(self._SUFFIX):
            stem = stem[: -len(self._SUFFIX)]
        if not stem or "/" in stem or "\\" in stem or stem in (".", ".."):
            raise UserError(f"invalid entry name: {name!r}")
        return stem

    def _unique_name(self, directory, stem):
        stem = self._stem(stem)
        candidate = f"{stem}{self._SUFFIX}"
        n = 1
        while (directory / candidate).exists():
            candidate = f"{stem}-{n}{self._SUFFIX}"
            n += 1
        return candidate

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

    def add_entry(self, scope, text, event, tool=None, name="default"):
        text = text.strip()
        if not text:
            raise UserError("entry text must not be empty")
        directory = self._dir(scope, event, tool)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{self._stem(name)}{self._SUFFIX}"
        if target.exists():
            prev = target.read_text().rstrip("\n")
            text = f"{prev}\n{text}" if prev else text
        target.write_text(text + "\n")

    def entry_path(self, scope, name, event, tool=None):
        """Filesystem path of a named entry file, creating its parent dir."""
        directory = self._dir(scope, event, tool)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{self._stem(name)}{self._SUFFIX}"

    def add_import_entry(self, scope, text, stem, event, tool=None):
        text = text.strip()
        if not text:
            raise UserError("entry text must not be empty")
        directory = self._dir(scope, event, tool)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / self._unique_name(directory, stem)
        target.write_text(text + "\n")

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
        entries = self._load(scope, event, tool)
        if event != ALL_MODE:
            entries = self._load(scope, ALL_MODE) + entries
        return "\n\n".join(entries)

    def walk(self):
        """Yield (scope, key, entries) for every non-empty verifier, broad->narrow."""
        for scope in self.SCOPES:
            for p in sorted(self.dirs[scope].iterdir(), key=lambda p: p.name):
                if not p.is_dir():
                    continue
                key = self._decode(p.name)
                entries = self._load(scope, **key)
                if entries:
                    yield scope, key, entries


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def dump_context(store):
    out = {}
    for scope, key, entries in store.walk():
        out.setdefault(mode_name(key), {}).update(
            {f"{scope}/{i}": text for i, text in enumerate(entries)}
        )
    return out


# ---------------------------------------------------------------------------
# Workflow generation: turn stored verifiers into a Claude Code Workflow script
# that fans out one agent per verifier. An MCP tool cannot run a Workflow (it is
# a plain subprocess), so it only emits the script for Claude to run.
# ---------------------------------------------------------------------------

_VERDICT = """
const VERDICT = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    violations: { type: 'array', items: { type: 'string' } },
  },
  required: ['pass'],
}
"""

_PLAN_META = """export const meta = {
  name: 'verify-loop-plan',
  description: 'Loop planner and verifiers over a plan artifact until all pass',
  phases: [{title:'Plan'}, {title:'Verify'}],
}
const VERIFIERS ="""

_PLAN_ENGINE = (
    _VERDICT
    + """
const MAX_ROUNDS = __MAX_ROUNDS__

phase('Plan')
let plan = await agent(`Draft an implementation plan for this request:\\n${args.prompt}`)

let unmet = VERIFIERS
for (let round = 0; round < MAX_ROUNDS; round++) {
  phase('Verify')
  const verdicts = await parallel(unmet.map(v => () =>
    agent(
      `Adversarially verify the PLAN below satisfies this check; ` +
      `default pass=false if unsure.\\n\\nPlan:\\n${plan}\\n\\nCheck ${v.id}:\\n${v.rule}`,
      { label: `verify:${v.id}`, schema: VERDICT }
    )
  ))
  unmet = unmet.filter((_, i) => !verdicts[i]?.pass)
  log(`round ${round + 1}: ${unmet.length} unmet`)
  if (!unmet.length) break

  phase('Plan')
  plan = await agent(
    `Revise the plan to satisfy these checks:\\n` +
    unmet.map(v => `- ${v.id}: ${v.rule}`).join('\\n') +
    `\\n\\nCurrent plan:\\n${plan}`
  )
}

return { plan, passed: VERIFIERS.filter(v => !unmet.includes(v)).map(v => v.id), failed: unmet.map(v => v.id) }
"""
)

_AUDIT_META = """export const meta = {
  name: 'verify-loop-audit',
  description: 'Run verifiers over the working tree once and report violations',
  phases: [{title:'Verify'}],
}
const VERIFIERS ="""

_AUDIT_ENGINE = (
    _VERDICT
    + """
const scope = (args.files && args.files.length)
  ? `\\n\\nScope: restrict to ONLY these files:\\n` + args.files.join('\\n')
  : ``

phase('Verify')
const verdicts = await parallel(VERIFIERS.map(v => () =>
  agent(
    `Audit the working tree against this check. Read-only: do NOT edit files. ` +
    `List every violation as file:line + snippet.\\n\\nCheck ${v.id}:\\n${v.rule}` + scope,
    { label: `verify:${v.id}`, schema: VERDICT }
  )
))

return {
  passed: VERIFIERS.filter((_, i) => verdicts[i]?.pass).map(v => v.id),
  failed: VERIFIERS.filter((_, i) => !verdicts[i]?.pass).map(v => v.id),
  report: VERIFIERS.map((v, i) => ({ id: v.id, pass: !!verdicts[i]?.pass, violations: verdicts[i]?.violations ?? [] })),
}
"""
)

_FIX_META = """export const meta = {
  name: 'verify-loop-fix',
  description: 'Loop verifiers and fixes over the working tree until all pass',
  phases: [{title:'Verify'}, {title:'Fix'}],
}
const VERIFIERS ="""

_FIX_ENGINE = (
    _VERDICT
    + """
const MAX_ROUNDS = __MAX_ROUNDS__

const scope = (args.files && args.files.length)
  ? `\\n\\nScope: restrict to ONLY these files:\\n` + args.files.join('\\n')
  : ``

async function verify(list) {
  phase('Verify')
  const verdicts = await parallel(list.map(v => () =>
    agent(
      `Adversarially verify this check against the working tree; ` +
      `default pass=false if unsure. List violations.\\n\\nCheck ${v.id}:\\n${v.rule}` + scope,
      { label: `verify:${v.id}`, schema: VERDICT }
    )
  ))
  return list.filter((_, i) => !verdicts[i]?.pass)
}

let unmet = await verify(VERIFIERS)
for (let round = 0; round < MAX_ROUNDS && unmet.length; round++) {
  phase('Fix')
  await agent(
    `Edit the code on disk to satisfy these failing checks:\\n` +
    unmet.map(v => `- ${v.id}: ${v.rule}`).join('\\n') +
    (args.prompt ? `\\n\\nAdditional guidance:\\n${args.prompt}` : ``) + scope
  )
  unmet = await verify(unmet)
  log(`round ${round + 1}: ${unmet.length} unmet`)
}

return { passed: VERIFIERS.filter(v => !unmet.includes(v)).map(v => v.id), failed: unmet.map(v => v.id) }
"""
)

LOOPS = {
    "audit": (_AUDIT_META, _AUDIT_ENGINE),
    "fix": (_FIX_META, _FIX_ENGINE),
    "plan": (_PLAN_META, _PLAN_ENGINE),
}


def store_verifiers(store, mode=None):
    """One verifier per stored entry across scopes, broad->narrow; filter by mode."""
    return [
        {"id": f"{scope}/{mode_name(key)}/{i}", "rule": text}
        for scope, key, entries in store.walk()
        if mode is None or mode_name(key) == mode
        for i, text in enumerate(entries)
    ]


def build_script(verifiers, loop, max_rounds=4):
    meta, engine = LOOPS[loop]
    engine = engine.replace("__MAX_ROUNDS__", str(max_rounds))
    return " ".join([meta, json.dumps(verifiers), engine]) + "\n"


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

    def context(self, event, tool):
        body = self.store.joined(event, tool)
        if body:
            json.dump(
                {
                    "suppressOutput": True,
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": body,
                    },
                },
                sys.stdout,
            )

    def block(self, event, tool):
        body = self.store.joined(event, tool)
        if body:
            json.dump(
                {
                    "decision": "block",
                    "reason": body,
                    "suppressOutput": True,
                },
                sys.stdout,
            )

    def deny(self, event, tool):
        body = self.store.joined(event, tool)
        if not body:
            return
        if self.store.is_token_verified(event, tool):
            self.store.clear_token(event, tool)
            return
        token = self.store.issue_token(event, tool)
        reason = body + "\n\n" + self.proceed(tool, token)
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
            "violations remain, call the "
            "`mcp__plugin_handoff-verifier_handoff-verifier__confirm` tool with token "
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

    @staticmethod
    def enabled():
        """Tools disabled by default; opt in with HANDOFF_VERIFIER_ENABLED=1."""
        return os.environ.get("HANDOFF_VERIFIER_ENABLED") == "1"

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
                    "tools": (
                        [t["descriptor"] for t in self._tools.values()]
                        if self.enabled()
                        else []
                    )
                }
            case "tools/call":
                params = message.get("params") or {}
                try:
                    if not self.enabled():
                        raise self.TOOL_ERROR(
                            "handoff-verifier tools are disabled; set "
                            "HANDOFF_VERIFIER_ENABLED=1 to enable"
                        )
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
            "interrupting the user. verify = NOT a hook; it never fires at runtime. Its "
            "entries are stored solely to be fanned out by generate-workflow. all = applies "
            "to every mode; stored once and merged into each event's read at runtime."
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
        # Generated Workflow scripts live exactly as long as this server: the
        # handle is finalized (file deleted) when the process exits.
        self._script = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".gen.js",
            prefix="handoff-verifier-",
            delete=True,
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
        self.register_tool(
            name="generate-workflow",
            description=(
                "Generate a Claude Code Workflow script that fans out ONE agent per stored "
                "verifier of the given mode, each auditing the working tree (read-only) against "
                "that verifier's text. Use when the user wants to actually run their handoff "
                "verifiers as a review ('run my stop verifiers over the code', 'audit against my "
                "plan gates'). Writes the script to a temp file and returns JSON "
                "{scriptPath, count, mode}. AFTER calling this, run the script with the Workflow "
                "tool: Workflow({ scriptPath, args: { files } }) — `files` is an optional array "
                "narrowing the audit to those paths. Errors if no verifier of that mode is set."
            ),
            input_schema={
                "type": "object",
                "properties": {"mode": self.MODE_PROP},
                "required": ["mode"],
            },
            handler=self._generate_workflow,
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
        return scope, mode, mode_key(mode)

    @staticmethod
    def _index(arguments):
        index = arguments.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise UserError("index must be an integer")
        return index

    @staticmethod
    def _render(entries):
        return "\n".join(f"{i}: {text}" for i, text in enumerate(entries))

    def _list(self, arguments):
        return json_dumps(dump_context(self.store))

    def _read(self, arguments):
        scope, mode, key = self._resolve(arguments, require_scope=True)
        entries = self.store.entries(scope, **key)
        if not entries:
            raise UserError(f"no {mode} verifier at {scope} scope")
        return self._render(entries)

    def _write(self, arguments):
        scope, mode, key = self._resolve(arguments)
        content = arguments.get("content", "")
        if not content.strip():
            raise UserError("content must not be empty")
        self.store.add_entry(scope, content, **key)
        entries = self.store.entries(scope, **key)
        return f"added {mode} entry at {scope} scope\n{self._render(entries)}"

    def _edit(self, arguments):
        scope, mode, key = self._resolve(arguments)
        index = self._index(arguments)
        old_string = arguments.get("old_string", "")
        new_string = arguments.get("new_string", "")
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
        if count > 1 and not bool(arguments.get("replace_all")):
            raise UserError(
                f"old_string is not unique in {scope} {mode} entry {index} "
                f"({count} matches); pass replace_all to replace every match"
            )
        new_text = text.replace(old_string, new_string)
        self.store.replace_entry(
            scope=scope, index=index, text=new_text, **key
        )
        return f"edited {mode} entry {index} at {scope} scope\n{index}: {new_text}"

    def _remove(self, arguments):
        scope, mode, key = self._resolve(arguments)
        index = self._index(arguments)
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

    def _confirm(self, arguments):
        scope, mode, key = self._resolve(arguments)
        if "tool" not in key:
            raise UserError(
                f"confirm applies to {' or '.join(GATE_MODES)} (got {mode!r})"
            )
        if not self.store.confirm_token(arguments.get("token", ""), **key):
            raise UserError(
                f"no matching pending {mode} verification — make the gated call first so its "
                "constraints and token are shown, then confirm with that exact token"
            )
        return f"{mode} verification confirmed — now retry your call once"

    def _generate_workflow(self, arguments):
        mode = arguments.get("mode")
        if mode not in MODES:
            raise UserError(f"unknown mode: {mode!r}")
        verifiers = store_verifiers(self.store, mode)
        if not verifiers:
            raise UserError(
                f"no {mode} verifier set in any scope — nothing to fan out"
            )
        self._script.seek(0)
        self._script.truncate()
        self._script.write(build_script(verifiers, "audit"))
        self._script.flush()
        return json_dumps(
            {
                "scriptPath": self._script.name,
                "count": len(verifiers),
                "mode": mode,
            }
        )


def link_cli():
    """Symlink this script into ~/.local/bin when that dir exists.

    Run from hook and mcp modes so it self-installs on first invocation. Does nothing
    if the dir is absent, or if HANDOFF_VERIFIER_NO_SYMLINK=1. An existing symlink is
    refreshed to point at this script; a real (non-symlink) file is never clobbered.
    """
    if os.environ.get("HANDOFF_VERIFIER_NO_SYMLINK") == "1":
        return
    target = pathlib.Path.home() / ".local" / "bin" / "handoff-verifier"
    if not target.parent.is_dir():
        return
    if target.is_symlink():
        # Refresh a stale symlink (e.g. moved plugin path); leave real files alone.
        try:
            target.unlink()
        except OSError:
            return
    elif target.exists():
        return
    try:
        target.symlink_to(pathlib.Path(__file__))
    except OSError:
        pass


async def cmd_hook(args):
    link_cli()
    HookRunner(Store(resolve_session(), resolve_project())).run(
        json.load(sys.stdin)
    )


async def cmd_mcp(args):
    link_cli()
    VerifierMcpServer(Store(resolve_session(), resolve_project())).serve()


async def cmd_edit(args):
    editor = os.environ.get("EDITOR")
    if not editor:
        raise UserError("EDITOR is not set")
    scope = resolve_target_scope(args)
    session = await pick_session(args.session, scope == Store.SESSION)
    prepare_env()
    store = Store(resolve_session(session), resolve_project(args.project))
    name = args.name or "default"
    paths = [
        store.entry_path(scope, name, **mode_key(mode))
        for mode in add_target_modes(args)
    ]
    process = await asyncio.create_subprocess_exec(
        editor, *(str(p) for p in paths)
    )
    await process.wait()
    if process.returncode:
        raise UserError(f"editor exited with status {process.returncode}")


async def edit_new_entry():
    editor = os.environ.get("EDITOR")
    if not editor:
        raise UserError("EDITOR is not set")
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".md", delete=False
    ) as handle:
        path = pathlib.Path(handle.name)
    try:
        process = await asyncio.create_subprocess_exec(editor, str(path))
        await process.wait()
        if process.returncode:
            raise UserError(f"editor exited with status {process.returncode}")
        text = path.read_text()
    finally:
        path.unlink(missing_ok=True)
    if not text.strip():
        raise UserError("aborted: no text entered")
    return text


async def cmd_add(args):
    scope = resolve_target_scope(args)
    session = await pick_session(args.session, scope == Store.SESSION)
    prepare_env()
    store = Store(resolve_session(session), resolve_project(args.project))
    if args.import_dir is not None:
        await import_entries(store, scope, args)
        return
    name = args.name or "default"
    texts = args.text
    if not texts:
        texts = [
            await edit_new_entry() if sys.stdin.isatty() else sys.stdin.read()
        ]
    for mode in add_target_modes(args):
        key = mode_key(mode)
        if args.replace:
            store.clear_context(scope, **key)
        for text in texts:
            store.add_entry(scope, text, name=name, **key)
        verb = "replaced with" if args.replace else "added"
        count = len(texts)
        print(
            f"{verb} {count} {mode} entr{'y' if count == 1 else 'ies'} "
            f"to {name!r} at {scope} scope"
        )


async def import_entries(store, scope, args):
    if args.text:
        raise UserError("--import cannot be combined with entry text")
    if args.name is not None:
        raise UserError("--import cannot be combined with --name")
    target = args.import_dir
    if not target.exists():
        raise UserError(f"no such file or directory: {target}")
    files = all_files(target, suffix=".md")
    if not files:
        raise UserError(f"no .md files under {target}")
    for mode in add_target_modes(args):
        key = mode_key(mode)
        if args.replace:
            store.clear_context(scope, **key)
        count = 0
        for path in files:
            if not path.read_text().strip():
                print(f"skipped empty {path}")
                continue
            store.add_import_entry(scope, path.read_text(), path.stem, **key)
            count += 1
        print(f"imported {count} {mode} entries at {scope} scope")


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


async def cmd_show(args):
    session = await pick_session(args.session, required=False)
    prepare_env()
    store = Store(resolve_session(session), resolve_project(args.project))
    body = store.joined(**mode_key(args.mode))
    if body:
        print(body)


async def cmd_path(args):
    scope = resolve_target_scope(args)
    session = await pick_session(args.session, scope == Store.SESSION)
    prepare_env()
    print(
        Store(resolve_session(session), resolve_project(args.project)).dirs[
            scope
        ]
    )


async def cmd_clear(args):
    scope = resolve_target_scope(args)
    session = await pick_session(args.session, scope == Store.SESSION)
    prepare_env()
    store = Store(resolve_session(session), resolve_project(args.project))
    for mode in resolve_modes(args):
        key = mode_key(mode)
        if not store.entries(scope, **key):
            continue
        if args.index is not None:
            store.remove_entry(scope, args.index, **key)
            print(f"removed {mode} entry {args.index} at {scope} scope")
        else:
            store.clear_context(scope, **key)
            print(f"cleared {mode} verifier at {scope} scope")


async def cmd_generate_workflow(args):
    session = await pick_session(args.session, required=False)
    prepare_env()
    store = Store(resolve_session(session), resolve_project(args.project))
    verifiers = store_verifiers(store, args.mode)
    if not verifiers:
        target = f"{args.mode} verifier" if args.mode else "verifiers"
        raise UserError(f"no {target} set in any scope — nothing to fan out")
    script = build_script(verifiers, args.loop, args.max_rounds)
    if args.output:
        args.output.write_text(script)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(script)


def add_mode_argument(subparser):
    subparser.add_argument(
        "-m",
        "--mode",
        action="append",
        dest="mode",
        choices=list(MODES),
        metavar="MODE",
        help="verifier mode to act on (repeatable); 'all' = the cross-cutting "
        "bucket merged into every mode at runtime. add defaults to 'all'; "
        "clear defaults to every mode",
    )


def resolve_modes(args):
    if not args.mode:
        return list(MODES)
    return list(dict.fromkeys(args.mode))


def add_target_modes(args):
    """add/import target: the listed modes, or just the all-folder when none given."""
    if not args.mode:
        return [ALL_MODE]
    return list(dict.fromkeys(args.mode))


def add_target_argument(subparser):
    """Scope selector for scope-specific commands.

    The three scopes are mutually exclusive; the flag chosen IS the scope.
    Defaults to the project scope when none is given.
    """
    section = subparser.add_argument_group(
        "scope", "which verifier scope to act on (default: project)"
    )
    group = section.add_mutually_exclusive_group()
    group.add_argument(
        "-u",
        "--user",
        action="store_true",
        help="target the global (user) scope",
    )
    group.add_argument(
        "-p",
        "--project",
        nargs="?",
        const="",
        metavar="DIR",
        help="target the project scope; optional DIR overrides the current directory",
    )
    group.add_argument(
        "-s",
        "--session",
        nargs="?",
        const="",
        metavar="ID",
        help="target the session scope; optional ID (or unique prefix) selects the "
        "session, else it is auto-resolved from this directory",
    )


def resolve_target_scope(args):
    if args.user:
        return Store.GLOBAL
    if args.session is not None:
        return Store.SESSION
    return Store.PROJECT


def add_session_argument(subparser):
    subparser.add_argument(
        "-s",
        "--session",
        metavar="ID",
        help="session id, or a unique prefix of an active session's id; "
        "empty or omitted auto-resolves from this directory",
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
        metavar="{hook,mcp,ls,show,path,edit,add,clear,generate-workflow}",
    )
    hook = subparsers.add_parser(
        "hook",
        aliases=["h"],
        help="run as a Claude Code hook (invoked by hooks.json)",
    )
    hook.set_defaults(func=cmd_hook)
    mcp = subparsers.add_parser(
        "mcp", aliases=["m"], help="run as an MCP stdio server"
    )
    mcp.set_defaults(func=cmd_mcp)
    show = subparsers.add_parser(
        "ls", aliases=["l"], help="list active verifiers across scopes"
    )
    show.set_defaults(func=cmd_ls)
    add_session_argument(show)
    add_project_argument(show)
    show_cmd = subparsers.add_parser(
        "show",
        aliases=["s"],
        help="print the rendered verifier text a mode's hook would inject",
    )
    show_cmd.set_defaults(func=cmd_show)
    show_cmd.add_argument(
        "mode",
        choices=list(MODES),
        metavar="MODE",
        help="verifier mode to render",
    )
    add_session_argument(show_cmd)
    add_project_argument(show_cmd)
    path = subparsers.add_parser(
        "path",
        aliases=["p"],
        help="print the filesystem path of a scope's verifiers",
    )
    path.set_defaults(func=cmd_path)
    add_target_argument(path)
    edit = subparsers.add_parser(
        "edit", aliases=["e"], help="open a scope's verifiers in $EDITOR"
    )
    edit.set_defaults(func=cmd_edit)
    add_target_argument(edit)
    add_mode_argument(edit)
    edit.add_argument(
        "-n",
        "--name",
        metavar="NAME",
        help="entry file to open (default: default)",
    )
    add = subparsers.add_parser(
        "add", aliases=["a"], help="append an entry to one scope's verifier"
    )
    add.set_defaults(func=cmd_add)
    add_target_argument(add)
    add_mode_argument(add)
    entry = add.add_argument_group("entry", "the content to store and how")
    entry.add_argument(
        "-n",
        "--name",
        metavar="NAME",
        help="entry file to append to (default: default)",
    )
    entry.add_argument(
        "-r",
        "--replace",
        action="store_true",
        help="remove existing entries for the target mode(s) first, leaving only this input",
    )
    entry.add_argument(
        "-i",
        "--import",
        dest="import_dir",
        type=pathlib.Path,
        metavar="PATH",
        help="add a .md file as an entry, or recursively add every .md file under a directory",
    )
    entry.add_argument(
        "text",
        nargs="*",
        help="entry text, one entry per argument; read from stdin if omitted",
    )
    clear = subparsers.add_parser(
        "clear", aliases=["c"], help="remove one scope's verifier for a mode"
    )
    clear.set_defaults(func=cmd_clear)
    add_target_argument(clear)
    add_mode_argument(clear)
    clear.add_argument(
        "--index",
        type=int,
        help="entry index to remove; omit to clear the whole mode",
    )
    gen = subparsers.add_parser(
        "generate-workflow",
        aliases=["g"],
        help="emit a Workflow script fanning one agent out per verifier",
    )
    gen.set_defaults(func=cmd_generate_workflow)
    gen.add_argument(
        "-l",
        "--loop",
        choices=list(LOOPS),
        default="audit",
        help="engine: audit (once, read-only), fix (verify->edit loop), plan (draft->revise)",
    )
    gen.add_argument(
        "-m",
        "--mode",
        choices=list(MODES),
        help="limit to one verifier mode; omit for every mode across scopes",
    )
    gen.add_argument(
        "-n",
        "--max-rounds",
        type=int,
        default=4,
        help="loop round cap for fix/plan (default: 4)",
    )
    gen.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        metavar="PATH",
        help="write the script to PATH; defaults to stdout",
    )
    add_session_argument(gen)
    add_project_argument(gen)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    try:
        main()
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
