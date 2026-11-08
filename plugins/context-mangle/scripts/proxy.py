#!/usr/bin/env python3
"""Forward Claude Code's API requests upstream, each rewritten by its settings.

Listens on a free port of 127.0.0.1 and prints `port <N>` once it is ready.

A request's settings are the --config JSON file's, read for each request, with
any settings field over them: a JSON object between --tag's opening and
closing tags in its system prompt (an agent's definition) or its first message
(a spawn's prompt). Each field is cut from the text it is in, and a later one
overrides an earlier one key by key. A missing or invalid value is its default.

- system_prompt (a field's only; the hooks apply the config's): a string
  replaces the system prompt, and "" sends none; the billing header, which the
  API requires, is kept.
- turns: "all" keeps every message; "latest" keeps one user message, the
  latest prompt: the last user message's last tool result's text, or its text
  that is no reminder, when it has any. With "latest", context_management is
  dropped, as it edits turns the request no longer carries.
- no_reminders: when true, every <system-reminder> text block is left out.
- tools.only: null offers every tool; a list of names offers only those tools,
  and [] offers none.
- tools.remove: the named tools are left out.
  A tool left out by either is dropped from `tools`, as is a tool_choice naming
  it, and ToolSearch results that reference it. A request left with no tool
  carries neither `tools` nor `tool_choice`.
- tools.minimal_descriptions: when true, every tool's description is dropped
  and its input schema's annotations (`description`, `title`, `$schema`) with it.
- stop_prompt: a request whose latest prompt is this text offers no tool.
- require_tool_call: when true, the reply to a request that offers tools is
  buffered whole and drawn again while it calls no tool, up to MAX_REPLIES
  times, so the engine sees a reply without a tool call only when the replies
  run out. Every other response is streamed back as it arrives.

With --log, each exchange with the upstream is appended to that file as a JSON
line: the request as the engine sent it and as it was forwarded, and the
response's status and body. Headers are left out, the credential among them.
"""

import argparse
import datetime
import http.client
import http.server
import json
import os
import pathlib
import sys
import threading
import time
import urllib.parse

# The system block the API refuses a request without.
BILLING_PREFIX = "x-anthropic-billing-header:"

# Schema keys that only annotate it for the model.
SCHEMA_ANNOTATIONS = frozenset(["$schema", "description", "title"])

# Schema keys whose value maps names to subschemas: the names are kept as they are.
SCHEMA_MAPS = frozenset(
    [
        "$defs",
        "definitions",
        "dependentSchemas",
        "patternProperties",
        "properties",
    ]
)

# Schema keys whose value is a subschema or a list of them.
SCHEMA_CHILDREN = frozenset(
    [
        "additionalItems",
        "additionalProperties",
        "allOf",
        "anyOf",
        "contains",
        "else",
        "if",
        "items",
        "not",
        "oneOf",
        "prefixItems",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    ]
)

# How many replies the proxy draws for one request that requires a tool call
# before it passes on one that calls no tool.
MAX_REPLIES = 3

# Request paths whose JSON body carries tools and a system prompt.
REWRITTEN_PATHS = ("/v1/messages", "/v1/messages/count_tokens")

# Headers set per hop: the proxy sets its own.
HOP_HEADERS = frozenset(
    [
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "transfer-encoding",
        "accept-encoding",
    ]
)


def without_annotations(schema):
    if isinstance(schema, list):
        return [without_annotations(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    stripped = {}
    for key, value in schema.items():
        if key in SCHEMA_ANNOTATIONS:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            stripped[key] = {
                name: without_annotations(child)
                for name, child in value.items()
            }
        elif key in SCHEMA_CHILDREN:
            stripped[key] = without_annotations(value)
        else:
            stripped[key] = value
    return stripped


def is_billing(block):
    return isinstance(block, dict) and block.get("text", "").startswith(
        BILLING_PREFIX
    )


def text_blocks(message):
    content = message.get("content")
    if isinstance(content, str):
        message["content"] = content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]


def result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def is_reminder(block):
    return block.get("text", "").lstrip().startswith("<system-reminder>")


# The message with its reminder text blocks left out.
def without_reminders(message):
    if message.get("role") != "user":
        return message
    text_blocks(message)
    content = message.get("content")
    if not isinstance(content, list):
        return message
    return {
        **message,
        "content": [
            block
            for block in content
            if not (
                isinstance(block, dict)
                and block.get("type") == "text"
                and is_reminder(block)
            )
        ],
    }


# Drops each ToolSearch reference to a tool not allowed from the tool results;
# a result left with none says so. Whether any was dropped.
def drop_tool_references(messages, allowed):
    changed = False
    for message in messages if isinstance(messages, list) else []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("content"), list)
            ):
                continue
            kept = [
                part
                for part in block["content"]
                if not (
                    isinstance(part, dict)
                    and part.get("type") == "tool_reference"
                    and not allowed(part.get("tool_name"))
                )
            ]
            if len(kept) == len(block["content"]):
                continue
            block["content"] = kept or [
                {"type": "text", "text": "No matching tools found."}
            ]
            changed = True
    return changed


# Applies the config's tools part to the request in place; whether it changed.
def apply_tool_config(request, minimal, removed, only):
    tools = request.get("tools")
    if not isinstance(tools, list):
        return False
    changed = False

    def allowed(name):
        return name not in removed and (only is None or name in only)

    if removed or only is not None:
        kept = [
            tool
            for tool in tools
            if not (isinstance(tool, dict) and not allowed(tool.get("name")))
        ]
        if len(kept) != len(tools):
            request["tools"] = tools = kept
            changed = True
        choice = request.get("tool_choice")
        # A request left with no tool offers none, as the API takes no
        # tool_choice without tools.
        if not tools:
            request.pop("tools", None)
            request.pop("tool_choice", None)
            choice = None
        if (
            isinstance(choice, dict)
            and "name" in choice
            and not allowed(choice["name"])
        ):
            request.pop("tool_choice")
            changed = True
        changed = (
            drop_tool_references(request.get("messages"), allowed) or changed
        )
    if minimal:
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if tool.pop("description", None) is not None:
                changed = True
            schema = tool.get("input_schema")
            if schema is not None:
                stripped = without_annotations(schema)
                if stripped != schema:
                    tool["input_schema"] = stripped
                    changed = True
    return changed


# The opening and closing tags of --tag.
def field_tags(tag):
    return f"<{tag}>", f"</{tag}>"


# The settings fields in text, in order, and the text with them cut. A field
# that is not a JSON object is cut and reported.
def take_fields(text, tag):
    opening, closing = field_tags(tag)
    fields = []
    search = 0
    while (start := text.find(opening, search)) != -1:
        end = text.find(closing, start + len(opening))
        if end == -1:
            break
        try:
            field = json.loads(text[start + len(opening) : end])
        except ValueError as error:
            field = error
        if isinstance(field, dict):
            fields.append(field)
        else:
            print(
                f"ignoring a {tag} field that is not a JSON object: {field}",
                file=sys.stderr,
                flush=True,
            )
        text = text[:start] + text[end + len(closing) :]
        search = start
    return fields, text


# base with over's values in its place, objects merged key by key.
def merged(base, over):
    result = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = value
    return result


# Cuts every settings field from the request's system prompt and first
# message; the fields merged in order, or None when it holds none.
def take_settings(request, tag):
    found = False
    settings = {}

    def take(text):
        nonlocal found, settings
        fields, rest = take_fields(text, tag)
        if rest != text:
            found = True
        for field in fields:
            settings = merged(settings, field)
        return rest

    system = request.get("system")
    if isinstance(system, str):
        request["system"] = take(system)
        if not request["system"]:
            request.pop("system")
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                block["text"] = take(block["text"])
        request["system"] = [
            block
            for block in system
            if not (isinstance(block, dict) and block.get("text") == "")
        ]
    messages = request.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict) and first.get("role") == "user":
            for block in text_blocks(first):
                block["text"] = take(block.get("text", ""))
            first["content"] = [
                block
                for block in first["content"]
                if not (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and not block.get("text", "").strip()
                )
            ]
    return settings if found else None


# The config file's settings: {} when it is missing or not a JSON object.
def read_config(path):
    if path is None:
        return {}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        print(
            f"reading {path} failed, so its defaults apply: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {}
    return config if isinstance(config, dict) else {}


class Settings:
    """A request's settings, each invalid value its default."""

    TURNS = ("all", "latest")

    def __init__(self, config, field):
        values = merged(
            {
                key: config[key]
                for key in ("tools", "no_reminders")
                if key in config
            },
            field or {},
        )
        tools = values.get("tools")
        tools = tools if isinstance(tools, dict) else {}
        remove = tools.get("remove")
        only = tools.get("only")
        prompt = values.get("system_prompt")
        stop = values.get("stop_prompt")
        turns = values.get("turns")
        self.system_prompt = prompt if isinstance(prompt, str) else None
        self.turns = turns if turns in self.TURNS else "all"
        self.no_reminders = values.get("no_reminders") is True
        self.minimal_descriptions = tools.get("minimal_descriptions") is True
        self.removed = frozenset(
            name
            for name in (remove if isinstance(remove, list) else [])
            if isinstance(name, str)
        )
        self.only = (
            frozenset(name for name in only if isinstance(name, str))
            if isinstance(only, list)
            else None
        )
        self.stop_prompt = stop if isinstance(stop, str) else None
        self.require_tool_call = values.get("require_tool_call") is True


# The request's latest prompt, from its last user message (the engine may send
# a system message after it): its last tool result's text, or its text that is
# no reminder; None when it has no user message.
def latest_prompt(messages):
    last = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )
    if last is None:
        return None
    content = last.get("content")
    results = [
        block
        for block in (content if isinstance(content, list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    if results:
        return result_text(results[-1])
    return "\n".join(
        block.get("text", "")
        for block in text_blocks(last)
        if not is_reminder(block)
    )


# Applies the settings' turns and no_reminders to the messages in place;
# whether they changed.
def apply_turns(request, settings):
    messages = request.get("messages")
    if not isinstance(messages, list) or (
        settings.turns == "all" and not settings.no_reminders
    ):
        return False
    if settings.turns == "latest":
        prompt = latest_prompt(messages)
        if not prompt:
            return False
        request["messages"] = [
            {"role": "user", "content": [{"type": "text", "text": prompt}]}
        ]
        request.pop("context_management", None)
    else:
        kept = [without_reminders(message) for message in messages]
        request["messages"] = [
            message for message in kept if message.get("content")
        ]
    return True


# The rewritten body, and whether its response must call a tool.
def rewrite(body, tag, config):
    request = json.loads(body)
    if not isinstance(request, dict):
        return body, False
    field = take_settings(request, tag)
    settings = Settings(read_config(config), field)
    changed = field is not None
    if settings.system_prompt is not None:
        system = request.get("system")
        billing = (
            [block for block in system if is_billing(block)]
            if isinstance(system, list)
            else []
        )
        request["system"] = billing + (
            [{"type": "text", "text": settings.system_prompt}]
            if settings.system_prompt
            else []
        )
        changed = True
    changed = apply_turns(request, settings) or changed
    messages = request.get("messages")
    stopped = settings.stop_prompt is not None and (
        latest_prompt(messages if isinstance(messages, list) else [])
        == settings.stop_prompt
    )
    if stopped:
        request.pop("tools", None)
        request.pop("tool_choice", None)
        changed = True
    changed = (
        apply_tool_config(
            request,
            settings.minimal_descriptions,
            settings.removed,
            settings.only,
        )
        or changed
    )
    expects_tool = settings.require_tool_call and bool(request.get("tools"))
    return (json.dumps(request).encode() if changed else body), expects_tool


# Whether a Messages API response, a JSON body or an event stream, calls a tool.
def calls_tool(data):
    try:
        response = json.loads(data)
    except ValueError:
        response = None
    if isinstance(response, dict):
        return any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in response.get("content", [])
        )
    for line in data.decode(errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line.removeprefix("data:"))
        except ValueError:
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "content_block_start"
            and event.get("content_block", {}).get("type") == "tool_use"
        ):
            return True
    return False


def logged_body(data):
    if not data:
        return None
    try:
        return json.loads(data)
    except ValueError:
        return data.decode(errors="replace")


class ExchangeLog:
    """Appends one JSON line per exchange; the handler threads take turns."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def append(self, **fields):
        line = json.dumps(
            {
                "at": datetime.datetime.now(datetime.UTC).isoformat(),
                **fields,
            },
            ensure_ascii=False,
        )
        try:
            with self.lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as error:
            print(
                f"logging to {self.path} failed: {error}",
                file=sys.stderr,
                flush=True,
            )


def make_handler(upstream, tag, config, exchange_log):
    connection_class = (
        http.client.HTTPSConnection
        if upstream.scheme == "https"
        else http.client.HTTPConnection
    )
    base_path = upstream.path.rstrip("/")

    class Handler(http.server.BaseHTTPRequestHandler):
        def forward(self):
            received = self.rfile.read(
                int(self.headers.get("content-length", 0))
            )
            body = received
            expects_tool = False
            if (
                self.command == "POST"
                and urllib.parse.urlsplit(self.path).path in REWRITTEN_PATHS
            ):
                try:
                    body, expects_tool = rewrite(body, tag, config)
                except ValueError as error:
                    print(
                        f"forwarding {self.path} unrewritten: {error}",
                        file=sys.stderr,
                        flush=True,
                    )
            # A count_tokens response holds no reply to judge.
            if urllib.parse.urlsplit(self.path).path != "/v1/messages":
                expects_tool = False
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in HOP_HEADERS
            }
            attempt = 1
            while True:
                connection = connection_class(upstream.netloc, timeout=600)
                try:
                    connection.request(
                        self.command,
                        base_path + self.path,
                        body=body or None,
                        headers=headers,
                    )
                    response = connection.getresponse()
                    relayed = True
                    if not expects_tool or response.status != 200:
                        data = self.relay(response, data=None)
                    else:
                        # Buffered whole, so a reply without a tool call is
                        # sent again and the engine never sees it.
                        data = response.read()
                        relayed = calls_tool(data) or attempt >= MAX_REPLIES
                        if relayed:
                            self.relay(response, data=data)
                    if exchange_log is not None:
                        exchange_log.append(
                            method=self.command,
                            path=self.path,
                            attempt=attempt,
                            received=logged_body(received),
                            sent=logged_body(body),
                            status=response.status,
                            response=logged_body(data),
                        )
                    if relayed:
                        return
                finally:
                    connection.close()
                print(
                    f"reply {attempt} called no tool; sending {self.path} again",
                    file=sys.stderr,
                    flush=True,
                )
                attempt += 1

        # Sends the response on, and answers its body when a log will read it.
        def relay(self, response, data):
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("connection", "close")
            self.end_headers()
            if data is not None:
                self.wfile.write(data)
                self.wfile.flush()
                return data
            chunks = []
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
                if exchange_log is not None:
                    chunks.append(chunk)
            return b"".join(chunks)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = (
            do_OPTIONS
        ) = forward

        def log_message(self, format, *args):
            pass

    return Handler


def exit_with_parent(parent):
    while os.getppid() == parent:
        time.sleep(1)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream", required=True, help="the API base URL to forward to"
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="the tag name around a settings field",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        help="the JSON config file whose settings rewrite every request",
    )
    parser.add_argument(
        "--log",
        type=pathlib.Path,
        help="append each exchange with the upstream to this JSON lines file",
    )
    args = parser.parse_args()
    if not args.tag:
        parser.error("--tag must not be empty")
    upstream = urllib.parse.urlsplit(args.upstream)
    if upstream.scheme not in ("http", "https") or not upstream.netloc:
        parser.error(
            f"--upstream must be an http or https URL: {args.upstream}"
        )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(
            upstream,
            args.tag,
            args.config,
            None if args.log is None else ExchangeLog(args.log),
        ),
    )
    threading.Thread(
        target=exit_with_parent, args=(os.getppid(),), daemon=True
    ).start()
    print(f"port {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
