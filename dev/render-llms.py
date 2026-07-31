#!/usr/bin/env python3
"""Render the llms skill from its URL registry."""

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins" / "andrewrabert-dev" / "skills" / "llms" / "SKILL.md"

# Every trigger is rendered into both the registry link title and the
# description's "publishes one (...)" list, so the skill fires on any of them.
REGISTRY = [
    {
        "url": "https://pydantic.dev/docs/validation/latest/llms.txt",
        "triggers": ["pydantic", "pydantic-settings"],
    },
    {
        "url": "https://modelcontextprotocol.io/llms.txt",
        "triggers": [
            "Model Context Protocol specification",
            "mcp specification",
        ],
    },
    {
        "url": "https://gofastmcp.com/llms.txt",
        "triggers": ["fastmcp"],
    },
]

DESCRIPTION = (
    'Use any time llms.txt or "llms" is referenced, or when working with a '
    "project that publishes one ({triggers}) — fetch that project's canonical "
    "remote llms.txt as the source of truth for current docs. Covers what "
    "llms.txt is (an index of pages to fetch) and how to follow it."
)

TEMPLATE = """\
---
name: llms
description: {description}
---

# llms.txt

`llms.txt` is a plain-text or Markdown, LLM-oriented file published by a
project at a canonical URL. Treat it as the authoritative, current source for
that project's docs.

## Registry

{registry}

For anything else, projects typically serve it from `/llms.txt`. This may be
the full documentation or an index to other URLs or paths. When it's an index,
some projects also serve a `llms-full.txt` containing the full documentation.
"""


def triggers():
    """Every registry trigger in order, deduplicated case-insensitively."""
    seen = set()
    ordered = []
    for entry in REGISTRY:
        for trigger in entry["triggers"]:
            if trigger.casefold() not in seen:
                seen.add(trigger.casefold())
                ordered.append(trigger)
    return ordered


def listing(triggers):
    """Comma-separated triggers, quoting any that contain whitespace."""
    return ", ".join(
        f'"{trigger}"' if any(char.isspace() for char in trigger) else trigger
        for trigger in triggers
    )


def render():
    return TEMPLATE.format(
        description=DESCRIPTION.format(triggers=listing(triggers())),
        registry="\n".join(
            f"- [{listing(entry['triggers'])}]({entry['url']})"
            for entry in REGISTRY
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skill",
        nargs="?",
        default=SKILL,
        type=pathlib.Path,
        help=f"path to the llms SKILL.md (default: {SKILL})",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        dest="pre_commit",
        help="write nothing; exit non-zero if the rendering would change",
    )
    args = parser.parse_args()

    content = render()
    current = args.skill.read_text() if args.skill.exists() else None
    if current == content:
        print(f"{args.skill}: up to date")
        return 0
    if args.pre_commit:
        print(f"{args.skill}: stale, run just render", file=sys.stderr)
        return 1
    args.skill.parent.mkdir(parents=True, exist_ok=True)
    args.skill.write_text(content)
    print(f"{args.skill}: rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
