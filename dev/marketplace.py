#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["python-frontmatter", "tabulate"]
# ///
"""Marketplace maintenance: bump plugin versions and regenerate README.md."""

import argparse
import asyncio
import datetime
import json
import pathlib
import re

import frontmatter
import tabulate

REPO = pathlib.Path(__file__).resolve().parent.parent

PREFIX = "andrewrabert-"
AUTHOR = {"name": "Andrew Rabert"}
VERSION_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}\.\d+")

TEMPLATE = """\
# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

{plugins_table}

{sections}
## Usage

```
/plugin marketplace add andrewrabert/claude-code-marketplace
/plugin install <plugin>@{marketplace_name}
```
"""

SECTION = """\
### {name}

{skills_table}
"""


class git:
    @staticmethod
    async def _run(*args):
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(REPO),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode().strip())
        return stdout.decode()

    @staticmethod
    async def staged_paths():
        out = await git._run("diff", "--cached", "--name-only", "-z")
        return [pathlib.Path(name) for name in out.split("\0") if name]

    @staticmethod
    async def head_text(path):
        try:
            return await git._run("show", f"HEAD:{path}")
        except RuntimeError:
            return None

    @staticmethod
    async def add(path):
        await git._run("add", "--", str(path))

    @staticmethod
    async def is_tracked(path):
        out = await git._run("ls-files", "--", str(path))
        return bool(out.strip())


def next_version(head_text):
    today = datetime.date.today().strftime("%Y.%m.%d")
    serial = 0
    if head_text is not None:
        version = json.loads(head_text)["version"]
        prefix = f"{today}."
        if version.startswith(prefix):
            serial = int(version[len(prefix) :]) + 1
    return f"{today}.{serial}"


def staged_plugins(paths):
    plugins = set()
    for path in paths:
        parts = path.parts
        if len(parts) >= 2 and parts[0] == "plugins":
            plugins.add(parts[1])
    return sorted(plugins)


async def bump_plugin(name):
    rel = pathlib.Path("plugins") / name / ".claude-plugin" / "plugin.json"
    manifest = json.loads((REPO / rel).read_text())
    version = next_version(await git.head_text(rel))
    if manifest["version"] == version:
        return
    manifest["version"] = version
    (REPO / rel).write_text(json.dumps(manifest, indent=2) + "\n")
    await git.add(rel)
    print(f"{name} -> {version}")


async def cmd_bump(args):
    plugins = staged_plugins(await git.staged_paths())
    # A wholly-deleted plugin has no manifest left to bump; skip it. A skill
    # deleted from a surviving plugin still bumps that plugin's version.
    plugins = [
        name
        for name in plugins
        if (
            REPO / "plugins" / name / ".claude-plugin" / "plugin.json"
        ).exists()
    ]
    await asyncio.gather(*(bump_plugin(name) for name in plugins))


def today_version():
    return datetime.date.today().strftime("%Y.%m.%d") + ".0"


def dump_manifest(manifest):
    return json.dumps(manifest, indent=2) + "\n"


def canonical_manifest(name, existing=None):
    existing = existing or {}
    version = existing.get("version")
    if not (isinstance(version, str) and VERSION_RE.fullmatch(version)):
        version = today_version()
    return {
        "name": name,
        "description": existing.get("description", ""),
        "version": version,
        "author": dict(AUTHOR),
    }


def plugin_dirs():
    root = REPO / "plugins"
    return sorted(
        path
        for path in root.iterdir()
        if (path / ".claude-plugin" / "plugin.json").exists()
    )


async def cmd_check_plugin(args):
    names = args.names
    changed = False
    for plugin_dir in plugin_dirs():
        if names and plugin_dir.name not in names:
            continue
        path = plugin_dir / ".claude-plugin" / "plugin.json"
        current = path.read_text()
        canonical = dump_manifest(
            canonical_manifest(plugin_dir.name, json.loads(current))
        )
        if current != canonical:
            path.write_text(canonical)
            if await git.is_tracked(path):
                await git.add(path)
            print(f"normalized {plugin_dir.name}")
            changed = True
    if await sync_marketplace_descriptions():
        changed = True
    if not changed:
        print("all plugin manifests OK")


async def sync_marketplace_descriptions():
    mp_path = REPO / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(mp_path.read_text())
    changed = False
    for entry in marketplace["plugins"]:
        manifest = json.loads(
            (
                (REPO / entry["source"]).resolve()
                / ".claude-plugin"
                / "plugin.json"
            ).read_text()
        )
        description = manifest.get("description", "")
        if entry.get("description") != description:
            entry["description"] = description
            changed = True
    if changed:
        mp_path.write_text(json.dumps(marketplace, indent=2) + "\n")
        if await git.is_tracked(mp_path):
            await git.add(mp_path)
        print("synced marketplace.json descriptions")
    return changed


def cmd_new_plugin(args):
    name = args.name
    description = args.description
    if not name.startswith(PREFIX):
        name = PREFIX + name
    plugin_dir = REPO / "plugins" / name
    if plugin_dir.exists():
        raise SystemExit(f"plugin already exists: {name}")

    mp_path = REPO / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(mp_path.read_text())
    if any(plugin["name"] == name for plugin in marketplace["plugins"]):
        raise SystemExit(f"already in marketplace.json: {name}")

    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        dump_manifest(canonical_manifest(name, {"description": description}))
    )

    marketplace["plugins"].append(
        {
            "name": name,
            "source": f"./plugins/{name}",
            "description": description,
        }
    )
    mp_path.write_text(json.dumps(marketplace, indent=2) + "\n")
    print(f"created {name}")


def github_table(rows, headers):
    return tabulate.tabulate(rows, headers=headers, tablefmt="github")


def load_skills(plugin_dir):
    return [
        frontmatter.load(skill_file).metadata
        for skill_file in plugin_dir.glob("skills/*/SKILL.md")
    ]


def load_marketplace():
    marketplace = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text()
    )
    plugins = []
    for entry in marketplace["plugins"]:
        plugin_dir = (REPO / entry["source"]).resolve()
        manifest = json.loads(
            (plugin_dir / ".claude-plugin" / "plugin.json").read_text()
        )
        plugins.append({**manifest, "skills": load_skills(plugin_dir)})
    return {**marketplace, "plugins": plugins}


def render(marketplace):
    plugins = sorted(marketplace["plugins"], key=lambda plugin: plugin["name"])
    plugins_table = github_table(
        [[f"`{plugin['name']}`", plugin["description"]] for plugin in plugins],
        ["Plugin", "Description"],
    )
    sections = []
    for plugin in plugins:
        skills = sorted(plugin["skills"], key=lambda skill: skill["name"])
        skills_table = (
            github_table(
                [
                    [f"`{skill['name']}`", skill["description"]]
                    for skill in skills
                ],
                ["Skill", "Description"],
            )
            if skills
            else "_No skills._"
        )
        sections.append(
            SECTION.format(name=plugin["name"], skills_table=skills_table)
        )
    return TEMPLATE.format(
        plugins_table=plugins_table,
        sections="\n".join(sections),
        marketplace_name=marketplace["name"],
    )


def cmd_readme(args):
    (REPO / "README.md").write_text(render(load_marketplace()))
    print(f"Wrote {REPO / 'README.md'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "bump", help="bump versions of plugins with staged changes"
    )
    subparsers.add_parser("readme", help="regenerate README.md")

    check_parser = subparsers.add_parser(
        "check-plugin",
        help="normalize plugin manifests to the canonical shape",
    )
    check_parser.add_argument(
        "names", nargs="*", help="limit to these plugins"
    )

    new_parser = subparsers.add_parser(
        "new-plugin", help="scaffold a new plugin"
    )
    new_parser.add_argument(
        "name", help="plugin name (andrewrabert- prefix added if absent)"
    )
    new_parser.add_argument("description")

    args = parser.parse_args()
    match args.command:
        case "bump":
            asyncio.run(cmd_bump(args))
        case "readme":
            cmd_readme(args)
        case "check-plugin":
            asyncio.run(cmd_check_plugin(args))
        case "new-plugin":
            cmd_new_plugin(args)


if __name__ == "__main__":
    main()
