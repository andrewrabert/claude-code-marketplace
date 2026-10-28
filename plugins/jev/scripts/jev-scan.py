#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "pydantic>=2,<3",
#   "tree-sitter>=0.23,<0.26",
#   "tree-sitter-python>=0.23,<0.26",
#   "tree-sitter-rust>=0.23,<0.25",
#   "unidiff>=0.7,<0.8",
# ]
# ///
"""Review code and text with jev question sets and print the findings as JSON lines: every top-level item of the Rust, Python and Markdown files in a git repository, the hunks of any text file changed since a revision, or each declaration a Rust surface spec adds, judged against a description of the change. The text rules apply to every file; Rust also gets the Rust standards."""

import argparse
import asyncio
import dataclasses
import json
import pathlib
import sys

import pydantic
import tree_sitter
import tree_sitter_python
import tree_sitter_rust
import unidiff

# The question sets, gates files and jev-ask.py sit beside this script.
HERE = pathlib.Path(__file__).resolve().parent
JEV_ASK = HERE / "jev-ask.py"
DEFAULT_SET = HERE / "standards.yaml"
DEFAULT_SPEC_SET = HERE / "surface.yaml"
TEXT_SET = HERE / "text.yaml"

# Exit status when every item was reviewed, and when some items failed to.
PARTIAL = 2

# Siblings that belong to the item after them.
LEADING = {"line_comment", "block_comment", "attribute_item"}
PYTHON_LEADING = {"comment"}

# Items with nothing for the question set to judge.
SKIPPED = {
    "use_declaration",
    "extern_crate_declaration",
    "inner_attribute_item",
    "line_comment",
    "block_comment",
    "attribute_item",
    "empty_statement",
}

PYTHON_SKIPPED = {
    "import_statement",
    "import_from_statement",
    "future_import_statement",
    "comment",
    "pass_statement",
}

RUST = tree_sitter.Language(tree_sitter_rust.language())
PYTHON = tree_sitter.Language(tree_sitter_python.language())


@dataclasses.dataclass(frozen=True)
class Language:
    # The question sets every item of the file is reviewed against.
    sets: tuple[pathlib.Path, ...]
    # Splits a whole file into items; with none, the whole file is one item.
    parser: tree_sitter.Language | None = None
    # A line marking where test code starts; it and everything after it is left out.
    test_marker: str | None = None


LANGUAGES = {
    ".rs": Language(
        sets=(DEFAULT_SET, TEXT_SET), parser=RUST, test_marker="#[cfg(test)]"
    ),
    ".py": Language(sets=(TEXT_SET,), parser=PYTHON),
}

OTHER = Language(sets=(TEXT_SET,))

# The files a whole-directory scan reviews; with --base, every changed text file is reviewed.
WHOLE_SCAN = ("*.rs", "*.py", "*.md")


def language_of(name):
    return LANGUAGES.get(pathlib.PurePath(name).suffix, OTHER)


class UserError(Exception):
    pass


class Gates(pydantic.BaseModel):
    threshold: float
    gate: float
    gates: dict[str, list[str]]


# For a question set with no gates file.
DEFAULT_GATES = Gates(threshold=0.75, gate=0.5, gates={})


Answers = pydantic.RootModel[dict[str, float]]


class DiffHunk(pydantic.BaseModel):
    header: str
    # The hunk's added and context lines, each with its `+` or ` ` prefix; removed lines are left
    # out.
    lines: list[str]


class Item(pydantic.BaseModel):
    file: str
    start: int
    end: int
    name: str
    context: str
    text: str
    # Changed hunks as git printed them; reviewed in place of `text` when there are any.
    hunks: list[DiffHunk] = []
    # Whether the diff leaves out its `@@` lines.
    headless: bool = False
    # The whole state jev is asked about, in place of the diff.
    state: str | None = None
    # The question sets the item is reviewed against.
    sets: tuple[pathlib.Path, ...] = ()
    # How much of the diff the item evaluates: a hunk, a file's hunks, or the full diff.
    evaluated: str | None = None

    @property
    def diff(self):
        hunks = self.hunks or [
            DiffHunk(
                header=f"@@ -0,0 +{self.start},{len(self.text.splitlines())} @@ "
                f"{self.context}".rstrip(),
                lines=[f"+{line}" for line in self.text.splitlines()],
            )
        ]
        return "\n".join(
            [
                f"diff --git a/{self.file} b/{self.file}",
                f"--- a/{self.file}",
                f"+++ b/{self.file}",
                *(
                    line
                    for hunk in hunks
                    for line in (
                        hunk.lines
                        if self.headless
                        else [hunk.header, *hunk.lines]
                    )
                ),
            ]
        )


class Finding(pydantic.BaseModel):
    file: str
    start: int
    end: int
    item: str
    question: str
    probability: float
    asks: str
    violation: str
    accepted: str
    evaluated: str | None = None


class Failure(pydantic.BaseModel):
    file: str
    start: int
    item: str
    error: str


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


async def run(*argv, stdin=None, cwd=None):
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(stdin)
    return proc.returncode, stdout.decode(), stderr.decode()


def is_test(node, source):
    return node.type == "attribute_item" and b"cfg(test)" in source[
        node.start_byte : node.end_byte
    ].replace(b" ", b"")


def leading(node, kinds=LEADING):
    """The comments and attributes directly above `node`, top first."""
    found = []
    sibling = node.prev_sibling
    while sibling is not None and sibling.type in kinds:
        below = found[0] if found else node
        if below.start_point[0] - sibling.end_point[0] > 1:
            break
        found.insert(0, sibling)
        sibling = sibling.prev_sibling
    return found


def name_of(node, source):
    name = node.child_by_field_name("name")
    if name is None:
        name = node.child_by_field_name("type")
    label = source[name.start_byte : name.end_byte].decode() if name else ""
    return f"{node.type.removesuffix('_item')} {label}".strip()


def header_of(node, source):
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    return " ".join(source[node.start_byte : end].decode().split())


def items(nodes, source, path, context=""):
    lines = source.decode().splitlines()
    for node in nodes:
        if node.type in SKIPPED:
            continue
        above = leading(node)
        if any(is_test(a, source) for a in above):
            continue
        body = node.child_by_field_name("body")
        if node.type == "mod_item" and body is not None:
            yield from items(
                body.named_children, source, path, header_of(node, source)
            )
            continue
        if node.type in ("impl_item", "trait_item") and body is not None:
            methods = [
                c
                for c in body.named_children
                if c.type in ("function_item", "function_signature_item")
            ]
            if methods:
                yield from items(
                    methods, source, path, header_of(node, source)
                )
                continue
        start = (above[0] if above else node).start_point[0]
        end = node.end_point[0]
        yield Item(
            file=path,
            start=start + 1,
            end=end + 1,
            name=name_of(node, source),
            context=context,
            text="\n".join(lines[start : end + 1]),
        )


def python_name_of(node, source):
    if node.type == "expression_statement" and node.named_children:
        statement = node.named_children[0]
        target = statement.child_by_field_name("left")
        if statement.type == "assignment" and target is not None:
            return f"assignment {source[target.start_byte : target.end_byte].decode()}"
        return statement.type
    name = node.child_by_field_name("name")
    label = source[name.start_byte : name.end_byte].decode() if name else ""
    return f"{node.type.removesuffix('_definition')} {label}".strip()


def python_items(nodes, source, path, context=""):
    """Each top-level statement of a Python file, and each method of a class apart from its head."""
    lines = source.decode().splitlines()

    def item(first, last, name):
        return Item(
            file=path,
            start=first + 1,
            end=last + 1,
            name=name,
            context=context,
            text="\n".join(lines[first : last + 1]),
        )

    for node in nodes:
        if node.type in PYTHON_SKIPPED:
            continue
        above = leading(node, PYTHON_LEADING)
        start = (above[0] if above else node).start_point[0]
        definition = node.child_by_field_name("definition") or node
        name = python_name_of(definition, source)
        body = definition.child_by_field_name("body")
        if definition.type == "class_definition" and body is not None:
            methods = [
                c
                for c in body.named_children
                if (c.child_by_field_name("definition") or c).type
                == "function_definition"
            ]
            if methods:
                first = leading(methods[0], PYTHON_LEADING) or [methods[0]]
                yield item(start, first[0].start_point[0] - 1, name)
                yield from python_items(
                    methods, source, path, header_of(definition, source)
                )
                continue
        yield item(start, node.end_point[0], name)


def file_items(name, source, language):
    match language.parser:
        case None:
            lines = source.decode().splitlines()
            return [
                Item(
                    file=name,
                    start=1,
                    end=max(len(lines), 1),
                    name="file",
                    context="",
                    text="\n".join(lines),
                )
            ]
        case parser if parser is PYTHON:
            tree = tree_sitter.Parser(parser).parse(source)
            return list(
                python_items(tree.root_node.named_children, source, name)
            )
        case parser:
            tree = tree_sitter.Parser(parser).parse(source)
            return list(items(tree.root_node.named_children, source, name))


def merge_constants(scanned):
    """Consecutive const, static and assignment items as one item, so each costs one review together."""
    merged = []
    for item in scanned:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.file == item.file
            and previous.context == item.context
            and previous.name.split()[0] in MERGED
            and item.name.split()[0] in MERGED
            and item.start - previous.end <= 2
        ):
            gap = "\n" * (item.start - previous.end)
            merged[-1] = previous.model_copy(
                update={
                    "end": item.end,
                    "name": f"{previous.name}, {item.name}",
                    "text": previous.text + gap + item.text,
                }
            )
        else:
            merged.append(item)
    return merged


MERGED = ("const", "static", "assignment")


def test_cutoff(source, marker):
    """The line number of the first line that is `marker`, after the last line when there is none."""
    lines = source.decode(errors="replace").splitlines()
    return next(
        (
            n
            for n, line in enumerate(lines, 1)
            if marker is not None and line == marker
        ),
        len(lines) + 1,
    )


async def changed_items(root, pathspecs, base, context):
    """The hunks changed since `base`'s merge-base with HEAD, each with `context` as git diff
    options for its context lines, and the untracked files."""
    if base.startswith("-"):
        raise UserError(f"base {base!r} is not a revision")
    code, stdout, stderr = await run(
        "git", "merge-base", base, "HEAD", cwd=root
    )
    if code != 0:
        raise UserError(f"git merge-base {base} HEAD: {stderr.strip()}")
    merge_base = stdout.strip()
    code, stdout, stderr = await run(
        "git",
        "diff",
        *context,
        "--no-color",
        "--no-ext-diff",
        "--relative",
        merge_base,
        "--",
        *pathspecs,
        cwd=root,
    )
    if code != 0:
        raise UserError(f"git diff {merge_base}: {stderr.strip()}")
    changed = []
    for patched in unidiff.PatchSet(stdout):
        if patched.is_removed_file or patched.is_binary_file:
            continue
        name = patched.path
        # A submodule's diff names its directory.
        if not (root / name).is_file():
            continue
        cutoff = test_cutoff(
            (root / name).read_bytes(),
            language_of(name).test_marker,
        )
        for hunk in patched:
            lines = [
                line
                for line in hunk
                if (line.is_added or line.is_context)
                and line.target_line_no < cutoff
            ]
            if not any(line.is_added for line in lines):
                continue
            header = (
                f"@@ -{hunk.source_start},{hunk.source_length} "
                f"+{hunk.target_start},{hunk.target_length} @@ {hunk.section_header}"
            )
            changed.append(
                Item(
                    file=name,
                    start=hunk.target_start,
                    end=lines[-1].target_line_no,
                    name=hunk.section_header or "hunk",
                    context="",
                    text="",
                    hunks=[
                        DiffHunk(
                            header=header.rstrip(),
                            lines=[
                                f"{line.line_type}{line.value.removesuffix('\n')}"
                                for line in lines
                            ],
                        )
                    ],
                )
            )
    code, stdout, stderr = await run(
        "git",
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        *pathspecs,
        cwd=root,
    )
    if code != 0:
        raise UserError(f"git ls-files --others in {root}: {stderr.strip()}")
    untracked = [name for name in stdout.split("\0") if name]
    return changed, untracked


# What one item of a change evaluates: the full diff, each file's diff, or each hunk of it.
EVALUATIONS = ("diff", "file", "hunk")

DEFAULT_CONTEXT = 20

FULL_CONTEXT = "full"

# A git diff context length longer than any file, so each file's diff is one hunk.
WHOLE_FILE_LINES = 100_000_000


def context_lines(value):
    """The lines of context a --context value asks for: a count, or every line for `full`."""
    if value == FULL_CONTEXT:
        return WHOLE_FILE_LINES
    try:
        lines = int(value)
    except ValueError:
        lines = -1
    if lines < 0:
        raise argparse.ArgumentTypeError(
            f"expected a count of lines, 0 or more, or {FULL_CONTEXT}; got {value!r}"
        )
    return lines


def added_everywhere(item):
    """`item` with every context line of its hunks marked as added, so it is judged too."""
    return item.model_copy(
        update={
            "hunks": [
                hunk.model_copy(
                    update={"lines": [f"+{line[1:]}" for line in hunk.lines]}
                )
                for hunk in item.hunks
            ]
        }
    )


def file_diffs(hunks):
    """One item per file holding all of the file's hunks."""
    by_file = {}
    for hunk in hunks:
        by_file.setdefault(hunk.file, []).append(hunk)
    return [
        Item(
            file=name,
            start=file_hunks[0].start,
            end=file_hunks[-1].end,
            name="file",
            context="",
            text="",
            hunks=[hunk for item in file_hunks for hunk in item.hunks],
        )
        for name, file_hunks in by_file.items()
    ]


def change_items(hunks, untracked, evaluations, all_added):
    """The items that evaluate the change's `hunks` as each of `evaluations` says. An untracked
    file is all added, so its diff is the whole file, and its hunks are its top-level items."""
    if all_added:
        hunks = [added_everywhere(hunk) for hunk in hunks]
    new_files = []
    for name, source in untracked.items():
        lines = source.decode(errors="replace").splitlines()
        lines = lines[: test_cutoff(source, language_of(name).test_marker) - 1]
        new_files.append(
            Item(
                file=name,
                start=1,
                end=max(len(lines), 1),
                name="file",
                context="",
                text="\n".join(lines),
            )
        )

    def evaluated(items, evaluation):
        return [
            item.model_copy(update={"evaluated": evaluation}) for item in items
        ]

    scanned = []
    if "diff" in evaluations:
        files = file_diffs(hunks) + new_files
        if files:
            scanned.append(
                Item(
                    file=".",
                    start=0,
                    end=0,
                    name="diff",
                    context="",
                    text="",
                    state="\n".join(item.diff for item in files),
                    sets=tuple(
                        dict.fromkeys(
                            s
                            for item in files
                            for s in language_of(item.file).sets
                        )
                    ),
                    evaluated="diff",
                )
            )
    if "file" in evaluations:
        scanned += evaluated(file_diffs(hunks) + new_files, "file")
    if "hunk" in evaluations:
        new = [
            item
            for name, source in untracked.items()
            for item in file_items(name, source, language_of(name))
        ]
        scanned += evaluated(
            [
                item.model_copy(update={"headless": True})
                for item in hunks + merge_constants(new)
            ],
            "hunk",
        )
    return scanned


SPEC_SECTIONS = ("## Additions", "## Declarations")

SPEC_STATE = """Description of the change:
{description}

Every declaration the change adds, from its surface spec:
{additions}

Declaration under review, in {file}:
```rust
{declaration}
```
"""


def spec_items(spec, description, parser):
    """Each declaration under the spec's `## Additions`, or `## Declarations` in a spec of
    whole files, its lines counted in the spec."""
    lines = spec.splitlines()
    sections = [n for n, line in enumerate(lines) if line in SPEC_SECTIONS]
    if not sections:
        raise UserError(
            "the spec has no ## Additions or ## Declarations section"
        )
    begin = sections[0]
    end = next(
        (
            i
            for i in range(begin + 1, len(lines))
            if lines[i].startswith("## ")
        ),
        len(lines),
    )
    additions = "\n".join(lines[begin:end]).strip()
    found = []
    file = None
    i = begin + 1
    while i < end:
        line = lines[i].strip()
        if line.startswith("### "):
            file = line.removeprefix("### ").strip()
        elif line == "```rust":
            close = next(
                (j for j in range(i + 1, end) if lines[j].strip() == "```"),
                None,
            )
            if close is None:
                raise UserError(
                    f"the rust block at spec line {i + 1} is not closed"
                )
            if file is None:
                raise UserError(
                    f"the rust block at spec line {i + 1} has no ### file heading"
                )
            source = "\n".join(lines[i + 1 : close]).encode()
            tree = parser.parse(source)
            for item in items(tree.root_node.named_children, source, file):
                declaration = (
                    f"{item.context} {{\n{item.text}\n}}"
                    if item.context
                    else item.text
                )
                found.append(
                    item.model_copy(
                        update={
                            "start": item.start + i + 1,
                            "end": item.end + i + 1,
                            "state": SPEC_STATE.format(
                                description=description,
                                additions=additions,
                                file=file,
                                declaration=declaration,
                            ),
                        }
                    )
                )
            i = close
        i += 1
    return found


async def tracked_files(root, pathspecs):
    """The tracked and untracked files matching `pathspecs`, leaving out those git ignores."""
    code, stdout, stderr = await run(
        "git",
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *pathspecs,
        cwd=root,
    )
    if code != 0:
        raise UserError(f"git ls-files in {root}: {stderr.strip()}")
    return [name for name in stdout.split("\0") if name]


def describe(question):
    instructions = question.get("instructions")
    if isinstance(instructions, dict):
        asks = (
            instructions.get("statement") or instructions.get("question") or ""
        )
    else:
        asks = instructions or ""
    criteria = question.get("criteria")
    if not isinstance(criteria, dict):
        criteria = {}
    return asks, criteria.get("true", ""), criteria.get("false", "")


async def descriptions(question_set):
    code, stdout, stderr = await run(
        str(JEV_ASK),
        "--dry-run",
        "-q",
        str(question_set),
        stdin=b"x",
    )
    if code != 0:
        raise UserError(
            f"jev-ask.py --dry-run {question_set}: {stderr.strip()}"
        )
    return {
        name: describe(question)
        for name, question in json.loads(stdout)["questions"].items()
    }


def findings(item, root, answers, gates, described):
    gate_questions = {g for names in gates.gates.values() for g in names}
    for question, probability in answers.items():
        if question in gate_questions or probability < gates.threshold:
            continue
        if question in gates.gates and all(
            answers.get(g, 0) >= gates.gate for g in gates.gates[question]
        ):
            continue
        asks, violation, accepted = described.get(question, ("", "", ""))
        yield Finding(
            file=str(root / item.file),
            start=item.start,
            end=item.end,
            item=item.name,
            question=question,
            probability=round(probability, 2),
            asks=asks,
            violation=violation,
            accepted=accepted,
            evaluated=item.evaluated,
        )


async def ask(item, question_set, gate, verbose):
    state = (item.state if item.state is not None else item.diff).encode()
    async with gate:
        if verbose:
            code, stdout, stderr = await run(
                str(JEV_ASK), "-q", str(question_set), "--dry-run", stdin=state
            )
            if code == 0:
                print(
                    json_dumps(
                        {
                            "file": item.file,
                            "start": item.start,
                            "item": item.name,
                            "evaluated": item.evaluated,
                            "request": json.loads(stdout),
                        }
                    ),
                    file=sys.stderr,
                )
        code, stdout, stderr = await run(
            str(JEV_ASK), "-q", str(question_set), stdin=state
        )
    if code != 0:
        return Failure(
            file=item.file,
            start=item.start,
            item=item.name,
            error=stderr.strip(),
        )
    return Answers.model_validate_json(stdout).root


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        help="a file, or a directory, inside a git repository; a directory without --base scans its "
        ".rs, .py and .md files, and with --base every changed text file",
    )
    parser.add_argument(
        "--spec",
        type=pathlib.Path,
        help="a Rust surface spec, or - for stdin; reviews each declaration under ## Additions "
        "instead of PATH, and findings give its lines in the spec",
    )
    parser.add_argument(
        "--description",
        help="what the change is for, in a few sentences; required with --spec",
    )
    parser.add_argument(
        "--set",
        dest="question_set",
        type=pathlib.Path,
        help=f"question set for every item; default: {TEXT_SET.name} for every file, with "
        f"{DEFAULT_SET.name} too for .rs, or {DEFAULT_SPEC_SET.name} with --spec",
    )
    parser.add_argument(
        "--gates",
        type=pathlib.Path,
        help="gates file; default: each question set's path with .gates.json, or the default "
        "gates when there is none",
    )
    parser.add_argument(
        "--base",
        help="review only what changed from this revision's merge-base with HEAD to the "
        "working tree, plus untracked files; HEAD reviews uncommitted changes",
    )
    parser.add_argument(
        "-e",
        "--evaluate",
        action="append",
        choices=EVALUATIONS,
        help="with --base, what each request evaluates: the full diff, each file's diff, or "
        "each hunk of it; repeatable; default: hunk",
    )
    parser.add_argument(
        "-C",
        "--context",
        type=context_lines,
        metavar="LINES",
        help="with --base, the lines of context on each side of a hunk, or "
        f"{FULL_CONTEXT} for every line of the file; default: {DEFAULT_CONTEXT}",
    )
    parser.add_argument(
        "-a",
        "--all-added",
        action="store_true",
        help="with --base, mark every line of each evaluated hunk as added, so jev judges the "
        "unchanged lines too",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print each item's diff instead of asking jev",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print each request sent to jev to stderr as a JSON line",
    )
    args = parser.parse_args()
    evaluations = args.evaluate or ["hunk"]

    if args.spec is not None:
        if (
            args.path is not None
            or args.base is not None
            or args.evaluate is not None
            or args.context is not None
            or args.all_added
        ):
            raise UserError(
                "--spec takes no PATH, no --base, no --evaluate, no --context and no "
                "--all-added"
            )
        if not args.description:
            raise UserError("--spec needs --description")
        spec = (
            sys.stdin.read()
            if str(args.spec) == "-"
            else args.spec.expanduser().read_text()
        )
        sets = (args.question_set or DEFAULT_SPEC_SET,)
        scanned = [
            item.model_copy(update={"sets": sets})
            for item in spec_items(
                spec, args.description, tree_sitter.Parser(RUST)
            )
        ]
        return await review(
            scanned,
            pathlib.Path(),
            args.gates,
            args.concurrency,
            args.dry_run,
            args.verbose,
        )
    if args.path is None:
        raise UserError("give a PATH, or --spec")
    target = args.path.expanduser().resolve()
    if target.is_dir():
        root = target
        pathspecs = ["."] if args.base is not None else list(WHOLE_SCAN)
    elif target.is_file():
        root, pathspecs = target.parent, [target.name]
    else:
        raise UserError(f"{target} is neither a directory nor a file")

    if args.base is None:
        if (
            args.evaluate is not None
            or args.context is not None
            or args.all_added
        ):
            raise UserError(
                "--evaluate, --context and --all-added need --base"
            )
        whole = await tracked_files(root, pathspecs)
        if target.is_file() and not whole:
            raise UserError(f"{target} is ignored by git")
    else:
        lines = DEFAULT_CONTEXT if args.context is None else args.context
        hunks, whole = await changed_items(
            root, pathspecs, args.base, (f"-U{lines}",)
        )
    sources = {}
    for name in whole:
        # git lists an untracked nested repository as its directory.
        if not (root / name).is_file():
            continue
        source = (root / name).read_bytes()
        try:
            source.decode()
        except UnicodeDecodeError:
            # Not text, so nothing for the question sets to judge.
            continue
        sources[name] = source
    if args.base is None:
        scanned = merge_constants(
            [
                item
                for name, source in sources.items()
                for item in file_items(name, source, language_of(name))
            ]
        )
    else:
        scanned = change_items(hunks, sources, evaluations, args.all_added)
    scanned = [
        item.model_copy(
            update={
                "sets": (args.question_set,)
                if args.question_set
                else item.sets or language_of(item.file).sets
            }
        )
        for item in scanned
    ]
    return await review(
        scanned, root, args.gates, args.concurrency, args.dry_run, args.verbose
    )


def load_gates(question_set, override):
    """The gates for `question_set`: `override`, the .gates.json beside it, or the defaults."""
    path = override or question_set.with_suffix(".gates.json")
    if override is None and not path.exists():
        return DEFAULT_GATES
    return Gates.model_validate_json(path.read_text())


async def review(scanned, root, gates_override, concurrency, dry_run, verbose):
    if dry_run:
        for item in scanned:
            print(
                item.state if item.state is not None else item.diff, end="\n\n"
            )
        print(f"{len(scanned)} items", file=sys.stderr)
        return 0

    sets = sorted({s for item in scanned for s in item.sets})
    described = {s: await descriptions(s) for s in sets}
    gates = {s: load_gates(s, gates_override) for s in sets}
    asked = [(item, s) for item in scanned for s in item.sets]
    gate = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(ask(item, s, gate, verbose) for item, s in asked)
    )
    found = 0
    failures = []
    # A question two of an item's sets both ask is reported once, from the first set.
    reported = set()
    for (item, question_set), result in zip(asked, results):
        if isinstance(result, Failure):
            failures.append(
                result.model_copy(update={"file": str(root / result.file)})
            )
            continue
        for finding in findings(
            item, root, result, gates[question_set], described[question_set]
        ):
            if (id(item), finding.question) in reported:
                continue
            reported.add((id(item), finding.question))
            found += 1
            print(json_dumps(finding.model_dump(exclude_none=True)))
    for failure in failures:
        print(json_dumps({"failure": failure.model_dump()}))
    print(
        f"{len(scanned)} items reviewed in {root}, {found} findings, {len(failures)} failed",
        file=sys.stderr,
    )
    return PARTIAL if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
