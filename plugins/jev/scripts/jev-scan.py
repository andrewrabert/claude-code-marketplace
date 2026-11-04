#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "pathspec>=0.12,<2",
#   "pydantic>=2,<3",
#   "pyyaml>=6,<7",
#   "tree-sitter>=0.23,<0.26",
#   "tree-sitter-bash>=0.23,<0.26",
#   "tree-sitter-python>=0.23,<0.26",
#   "tree-sitter-rust>=0.23,<0.25",
#   "unidiff>=0.7,<0.8",
# ]
# ///
"""Review code and text with jev question sets and print the findings as JSON lines: every top-level item of the files in a known language under a root, or the hunks of any text file changed since a revision. Each file is reviewed against the question sets under --config whose `when` matches it."""

import argparse
import asyncio
import dataclasses
import functools
import json
import pathlib
import re
import sys

import pathspec
import pydantic
import yaml
import tree_sitter
import tree_sitter_bash
import tree_sitter_python
import tree_sitter_rust
import unidiff

HERE = pathlib.Path(__file__).resolve().parent
JEV_ASK = HERE / "jev-ask.py"
# The default --config: every *.yaml under it, at any depth, is a question set; its `when` picks
# the files it reviews.
QUESTIONS = HERE.parent / "questions"

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

# Top-level sh commands that change how every other part of the script runs; each item of a
# script carries the ones outside it as context.
SHELL_SETUP = {"set", "trap"}

RUST = tree_sitter.Language(tree_sitter_rust.language())
PYTHON = tree_sitter.Language(tree_sitter_python.language())
BASH = tree_sitter.Language(tree_sitter_bash.language())


@dataclasses.dataclass(frozen=True)
class Syntax:
    # Splits a whole file into items; with none, the whole file is one item.
    parser: tree_sitter.Language | None = None
    # A line marking where test code starts; it and everything after it is left out.
    test_marker: str | None = None


# The languages a question set's `when.language` can name.
SYNTAXES = {
    "rust": Syntax(parser=RUST, test_marker="#[cfg(test)]"),
    "python": Syntax(parser=PYTHON),
    "sh": Syntax(parser=BASH),
    "just": Syntax(),
    "markdown": Syntax(),
}

PLAIN = Syntax()

SUFFIXES = {".rs": "rust", ".py": "python", ".just": "just", ".md": "markdown"}

JUSTFILE_NAMES = ("justfile", "Justfile", ".justfile")

# A first line that matches one of these marks a Python script, or failing that a POSIX sh
# script.
PYTHON_SHEBANGS = (
    re.compile(r"^#!\S*/python[\d.]*(\s|$)"),
    re.compile(r"^#!\S*/env\s+(-\S+\s+)*python[\d.]*(\s|$)"),
    re.compile(r"^#!/usr/bin/env.*uv.*run"),
)
SHELL_SHEBANGS = (
    re.compile(r"^#!\S*/sh(\s|$)"),
    re.compile(r"^#!\S*/env\s+(-\S+\s+)*sh(\s|$)"),
)


def has_shebang(source, patterns):
    first = source.split(b"\n", 1)[0].decode(errors="replace")
    return any(pattern.search(first) for pattern in patterns)


def detect_language(name, source):
    """The language of a file, a key of SYNTAXES, or None."""
    path = pathlib.PurePath(name)
    if path.name in JUSTFILE_NAMES:
        return "just"
    if path.suffix in SUFFIXES:
        return SUFFIXES[path.suffix]
    if has_shebang(source, PYTHON_SHEBANGS):
        return "python"
    if has_shebang(source, SHELL_SHEBANGS):
        return "sh"
    return None


class When(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    # The file's detected language is one of these.
    language: tuple[str, ...] = ()
    # gitignore(5) patterns matched against the file's path from the scanned directory.
    pattern: tuple[str, ...] = ()


class Gates(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    # A noul answer at or above this flags the question.
    threshold: float = 0.75
    # A gated question is suppressed when every one of its gate questions is at or above this.
    gate: float = 0.5
    # Question to the gate questions that together suppress it; gate questions are never findings.
    gates: dict[str, list[str]] = {}


class QuestionSetFile(pydantic.BaseModel):
    """A question set file as jev-scan.py reads it; jev-ask.py reads the questions."""

    model_config = pydantic.ConfigDict(extra="forbid")

    # What the set covers, what it leaves out, and where it came from.
    description: str
    # Without one, the set reviews only what --set gives it.
    when: When | None = None
    # Which answers are findings.
    decision: Gates = Gates()
    questions: dict[str, object]


@functools.cache
def read_set(path):
    try:
        return QuestionSetFile.model_validate(
            yaml.safe_load(path.read_text())
        )
    except (OSError, yaml.YAMLError, pydantic.ValidationError) as e:
        raise UserError(f"question set {path}: {e}") from e


@dataclasses.dataclass(frozen=True)
class QuestionSet:
    path: pathlib.Path
    languages: frozenset[str]
    patterns: pathspec.GitIgnoreSpec


@functools.cache
def question_sets(config):
    """Every question set under `config` with a `when`, sorted by path."""
    if not config.is_dir():
        raise UserError(f"--config {config} is not a directory")
    found = []
    for path in sorted(config.rglob("*.yaml")):
        parsed = read_set(path)
        if parsed.when is None:
            continue
        if unknown := sorted(set(parsed.when.language) - SYNTAXES.keys()):
            raise UserError(
                f"question set {path}: unknown language {', '.join(unknown)}; "
                f"expected one of {', '.join(SYNTAXES)}"
            )
        found.append(
            QuestionSet(
                path=path,
                languages=frozenset(parsed.when.language),
                patterns=pathspec.GitIgnoreSpec.from_lines(parsed.when.pattern),
            )
        )
    return tuple(found)


@dataclasses.dataclass(frozen=True)
class Language:
    # The question sets every item of the file is reviewed against.
    sets: tuple[pathlib.Path, ...]
    # Splits a whole file into items; with none, the whole file is one item.
    parser: tree_sitter.Language | None = None
    # A line marking where test code starts; it and everything after it is left out.
    test_marker: str | None = None


def language_of(name, source, sets):
    """How a file is reviewed against `sets`; `name` is its path from the root."""
    detected = detect_language(name, source)
    syntax = SYNTAXES.get(detected, PLAIN)
    return Language(
        sets=tuple(
            question_set.path
            for question_set in sets
            if detected in question_set.languages
            or question_set.patterns.match_file(name)
        ),
        parser=syntax.parser,
        test_marker=syntax.test_marker,
    )


def in_whole_scan(name, source):
    """Whether a whole-directory scan reviews the file: it has a language. With --base, every
    changed text file is reviewed."""
    return detect_language(name, source) is not None


class UserError(Exception):
    pass


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


def shell_items(nodes, source, path):
    """Each function of a sh script, and each run of top-level code between them. Every item
    carries the script's top-level set and trap commands that lie outside it as context."""
    lines = source.decode().splitlines()
    # The shebang is not a comment for the question sets to judge.
    first_line = 1 if lines and lines[0].startswith("#!") else 0
    setup = []
    for node in nodes:
        name = node.child_by_field_name("name") if node.type == "command" else None
        if name is not None and source[name.start_byte : name.end_byte].decode() in SHELL_SETUP:
            setup.append(node)

    def item(first, last, name):
        start = max(
            (leading(first, PYTHON_LEADING) or [first])[0].start_point[0],
            first_line,
        )
        end = last.end_point[0]
        return Item(
            file=path,
            start=start + 1,
            end=end + 1,
            name=name,
            context="; ".join(
                " ".join(source[n.start_byte : n.end_byte].decode().split())
                for n in setup
                if not start <= n.start_point[0] <= end
            ),
            text="\n".join(lines[start : end + 1]),
        )

    run = []
    for node in nodes:
        if node.type == "comment":
            continue
        if node.type != "function_definition":
            run.append(node)
            continue
        if run:
            yield item(run[0], run[-1], "top-level")
            run = []
        name = node.child_by_field_name("name")
        label = source[name.start_byte : name.end_byte].decode() if name else ""
        yield item(node, node, f"function {label}".strip())
    if run:
        yield item(run[0], run[-1], "top-level")


def file_items(name, source, language):
    return [
        item.model_copy(update={"sets": language.sets})
        for item in parsed_items(name, source, language)
    ]


def parsed_items(name, source, language):
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
        case parser if parser is BASH:
            tree = tree_sitter.Parser(parser).parse(source)
            return list(
                shell_items(tree.root_node.named_children, source, name)
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


async def changed_items(root, pathspecs, base, context, sets):
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
        source = (root / name).read_bytes()
        language = language_of(name, source, sets)
        cutoff = test_cutoff(source, language.test_marker)
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
                    sets=language.sets,
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
            sets=file_hunks[0].sets,
            hunks=[hunk for item in file_hunks for hunk in item.hunks],
        )
        for name, file_hunks in by_file.items()
    ]


def change_items(hunks, untracked, evaluations, all_added, sets):
    """The items that evaluate the change's `hunks` as each of `evaluations` says. An untracked
    file is all added, so its diff is the whole file, and its hunks are its top-level items."""
    if all_added:
        hunks = [added_everywhere(hunk) for hunk in hunks]
    new_files = []
    for name, source in untracked.items():
        language = language_of(name, source, sets)
        lines = source.decode(errors="replace").splitlines()
        lines = lines[: test_cutoff(source, language.test_marker) - 1]
        new_files.append(
            Item(
                file=name,
                start=1,
                end=max(len(lines), 1),
                name="file",
                context="",
                text="\n".join(lines),
                sets=language.sets,
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
                            for s in item.sets
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
            for item in file_items(name, source, language_of(name, source, sets))
        ]
        scanned += evaluated(
            [
                item.model_copy(update={"headless": True})
                for item in hunks + merge_constants(new)
            ],
            "hunk",
        )
    return scanned


async def current_repository():
    code, stdout, _ = await run("git", "rev-parse", "--show-toplevel", cwd=pathlib.Path.cwd())
    if code != 0:
        raise UserError("the current directory is outside a git repository; give --root")
    return pathlib.Path(stdout.strip())


async def in_repository(root):
    code, stdout, _ = await run("git", "rev-parse", "--is-inside-work-tree", cwd=root)
    return code == 0 and stdout.strip() == "true"


def all_files(root, targets):
    """The files under each of `targets`, or each target itself, by path from `root`."""
    stack = []
    files = set()
    for target in targets:
        if target.is_file():
            files.add(str(target.relative_to(root)))
        else:
            stack.append(target)
    while stack:
        for path in stack.pop().iterdir():
            if path.is_dir():
                stack.append(path)
            elif path.is_file():
                files.add(str(path.relative_to(root)))
    return sorted(files)


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
        "paths",
        nargs="*",
        type=pathlib.Path,
        metavar="PATH",
        help="files or directories to review, relative to --root; default: the whole root. A "
        "directory without --base scans its files in a known language, and with --base every "
        "changed text file",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        help="the directory PATHs are relative to, each question set's `when.pattern` is matched "
        "from, and git runs in; default: the git repository holding the current directory. "
        "Outside a git repository every file counts as new",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=pathlib.Path,
        default=QUESTIONS,
        help=f"the directory of question sets; every *.yaml under it, at any depth, whose `when` "
        f"matches a file reviews it; default: {QUESTIONS}",
    )
    parser.add_argument(
        "--set",
        dest="question_set",
        type=pathlib.Path,
        help="question set for every item; default: each set under --config whose `when` "
        "matches the file",
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

    root = (
        await current_repository()
        if args.root is None
        else args.root.resolve()
    )
    if not root.is_dir():
        raise UserError(f"--root {root} is not a directory")
    sets = question_sets(args.config.resolve())
    targets = []
    for path in args.paths:
        if path.is_absolute():
            raise UserError(f"{path} is absolute; give PATHs relative to --root")
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise UserError(f"{path} is outside --root {root}")
        if not target.is_file() and not target.is_dir():
            raise UserError(f"{path} is neither a directory nor a file in {root}")
        targets.append(target)
    targets = targets or [root]
    pathspecs = [str(target.relative_to(root)) for target in targets]
    # Files named on the command line are reviewed whatever their language.
    named = {str(target.relative_to(root)) for target in targets if target.is_file()}

    if args.base is None and (
        args.evaluate is not None or args.context is not None or args.all_added
    ):
        raise UserError("--evaluate, --context and --all-added need --base")
    if not await in_repository(root):
        # Outside a repository every file is new: reviewed whole, or as added with --base.
        hunks, whole = [], all_files(root, targets)
    elif args.base is None:
        whole = await tracked_files(root, pathspecs)
        if ignored := sorted(named - set(whole)):
            raise UserError(f"{', '.join(ignored)} ignored by git")
    else:
        lines = DEFAULT_CONTEXT if args.context is None else args.context
        hunks, whole = await changed_items(
            root, pathspecs, args.base, (f"-U{lines}",), sets
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
        if args.base is None and name not in named and not in_whole_scan(name, source):
            continue
        sources[name] = source
    if args.base is None:
        scanned = merge_constants(
            [
                item
                for name, source in sources.items()
                for item in file_items(name, source, language_of(name, source, sets))
            ]
        )
    else:
        scanned = change_items(hunks, sources, evaluations, args.all_added, sets)
    scanned = [
        item.model_copy(
            update={
                "sets": (args.question_set,) if args.question_set else item.sets
            }
        )
        for item in scanned
        if args.question_set or item.sets
    ]
    return await review(
        scanned, root, args.concurrency, args.dry_run, args.verbose
    )


async def review(scanned, root, concurrency, dry_run, verbose):
    if dry_run:
        for item in scanned:
            print(
                item.state if item.state is not None else item.diff, end="\n\n"
            )
        print(f"{len(scanned)} items", file=sys.stderr)
        return 0

    sets = sorted({s for item in scanned for s in item.sets})
    described = {s: await descriptions(s) for s in sets}
    gates = {s: read_set(s).decision for s in sets}
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
