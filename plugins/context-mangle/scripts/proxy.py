#!/usr/bin/env python3
"""Forward Claude Code's API requests upstream, the marked ones cut to one prompt.

Listens on a free port of 127.0.0.1 and prints `port <N>` once it is ready.
A Messages API request whose first message holds --marker followed by the JSON
object {"system_prompt": "...", "prompt": "..."} is rewritten before it is
forwarded, to keep only what is listed here:

- system: the billing header, which the API requires, and system_prompt.
- tools: each tool's name and input schema, less the schema's annotations
  (`description`, `title`, `$schema`); none for the --stop-prompt request.
- messages: one user message, the latest prompt: the last tool result, or
  before any tool call the object's prompt. No earlier turn is carried.
- context_management: dropped, as it edits turns the request no longer carries.

A marked request's reply is buffered whole. Unless its prompt is --stop-prompt,
a reply that calls no tool is drawn again, up to MAX_REPLIES times, so the
engine sees a reply without a tool call only when the replies run out.

A Messages API request whose system prompt holds --ask-tag's opening and
closing tags is rewritten to keep only the current turn:

- system: the billing header, and the text between the tags.
- messages: from the user's latest prompt (the last user message holding no
  tool result) on, with every <system-reminder> text block left out.
- context_management: dropped, as it edits turns the request no longer carries.

Every other request is forwarded unchanged. A response to a request that is
not marked is streamed back as it arrives.

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

# How many replies the proxy draws for one marked request before it passes on
# one that calls no tool.
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


def is_marked(request, marker):
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return False
    first = messages[0]
    return (
        isinstance(first, dict)
        and first.get("role") == "user"
        and any(
            marker in block.get("text", "") for block in text_blocks(first)
        )
    )


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


# The object after the marker in the first message.
def spawn_object(messages, marker):
    block = next(
        block
        for block in text_blocks(messages[0])
        if marker in block.get("text", "")
    )
    return json.loads(block["text"].split(marker, 1)[1])


# The prompt the next request carries alone: the last tool result, which the
# hook answers with the agent's next prompt, or before any tool call the spawn
# object's prompt.
def latest_prompt(messages, spawn):
    last = messages[-1]
    if isinstance(last, dict) and last.get("role") == "user":
        results = [
            block
            for block in last.get("content", [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        if results:
            return result_text(results[-1])
    return spawn["prompt"]


# The rewritten body, and whether its response must call a tool: true for
# every marked request but the one carrying the stop prompt.
def rewrite(body, marker, stop_prompt, ask_tag):
    request = json.loads(body)
    asked = rewrite_ask(request, ask_tag)
    if asked is not None:
        return json.dumps(asked).encode(), False
    if not is_marked(request, marker):
        return body, False
    spawn = spawn_object(request["messages"], marker)
    system = request.get("system")
    billing = (
        [block for block in system if is_billing(block)]
        if isinstance(system, list)
        else []
    )
    request["system"] = billing + (
        [{"type": "text", "text": spawn["system_prompt"]}]
        if spawn["system_prompt"]
        else []
    )
    for tool in request.get("tools", []):
        tool.pop("description", None)
        if "input_schema" in tool:
            tool["input_schema"] = without_annotations(tool["input_schema"])
    prompt = latest_prompt(request["messages"], spawn)
    request["messages"] = [
        {"role": "user", "content": [{"type": "text", "text": prompt}]}
    ]
    # The engine's context management edits turns this request no longer carries.
    request.pop("context_management", None)
    # The stop prompt is answered in text: the request offers no tool.
    if prompt == stop_prompt:
        request.pop("tools", None)
        request.pop("tool_choice", None)
    return json.dumps(request).encode(), prompt != stop_prompt


# The opening and closing tags of an --ask-tag.
def ask_tags(tag):
    return f"<{tag}>", f"</{tag}>"


def system_texts(request):
    system = request.get("system")
    if isinstance(system, str):
        return [system]
    if isinstance(system, list):
        return [
            block.get("text", "")
            for block in system
            if isinstance(block, dict)
        ]
    return []


# The text between the tags in the system prompt, or None when it holds none.
def ask_prompt(request, tag):
    opening, closing = ask_tags(tag)
    for text in system_texts(request):
        start = text.find(opening)
        end = text.find(closing, start + len(opening))
        if start != -1 and end != -1:
            return text[start + len(opening) : end].strip()
    return None


def is_reminder(block):
    return block.get("text", "").lstrip().startswith("<system-reminder>")


def has_tool_result(message):
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


# Whether a user message holds the user's prompt: text that is no reminder,
# and no tool result.
def is_prompt(message):
    return (
        isinstance(message, dict)
        and message.get("role") == "user"
        and not has_tool_result(message)
        and any(not is_reminder(block) for block in text_blocks(message))
    )


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


# The request cut to its current turn, when its system prompt holds the ask
# tags; None otherwise.
def rewrite_ask(request, tag):
    prompt = ask_prompt(request, tag)
    if prompt is None:
        return None
    messages = request.get("messages")
    if not isinstance(messages, list):
        return None
    start = max(
        (index for index, message in enumerate(messages) if is_prompt(message)),
        default=0,
    )
    kept = [without_reminders(message) for message in messages[start:]]
    request["messages"] = [message for message in kept if message.get("content")]
    system = request.get("system")
    billing = (
        [block for block in system if is_billing(block)]
        if isinstance(system, list)
        else []
    )
    request["system"] = billing + (
        [{"type": "text", "text": prompt}] if prompt else []
    )
    request.pop("context_management", None)
    return request


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


def make_handler(upstream, marker, stop_prompt, ask_tag, exchange_log):
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
                    body, expects_tool = rewrite(
                        body, marker, stop_prompt, ask_tag
                    )
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
        "--marker",
        required=True,
        help="the text whose presence in a request's first message marks it for rewriting",
    )
    parser.add_argument(
        "--stop-prompt",
        required=True,
        help="the prompt that ends the run: on every other one, a reply that calls no tool is drawn again",
    )
    parser.add_argument(
        "--ask-tag",
        required=True,
        help="the tag name whose opening and closing tags in a request's system prompt mark it to be cut to its current turn",
    )
    parser.add_argument(
        "--log",
        type=pathlib.Path,
        help="append each exchange with the upstream to this JSON lines file",
    )
    args = parser.parse_args()
    if not args.marker:
        parser.error("--marker must not be empty")
    if not args.ask_tag:
        parser.error("--ask-tag must not be empty")
    upstream = urllib.parse.urlsplit(args.upstream)
    if upstream.scheme not in ("http", "https") or not upstream.netloc:
        parser.error(
            f"--upstream must be an http or https URL: {args.upstream}"
        )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(
            upstream,
            args.marker,
            args.stop_prompt,
            args.ask_tag,
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
