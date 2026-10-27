#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "pydantic>=2,<3",
# ]
# ///
"""Score the standards question sets (scripts/standards.yaml and calibration/history) against the labelled cases in this directory."""

import argparse
import asyncio
import json
import pathlib
import sys

import pydantic

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent.parent / "scripts"
HISTORY = HERE.parent / "history"
STANDARDS = HISTORY / "standards-v1.yaml"
STANDARDS_V2 = HISTORY / "standards-v2.yaml"
STANDARDS_V3 = HISTORY / "standards-v3.yaml"
STANDARDS_V4 = HISTORY / "standards-v4.yaml"
STANDARDS_V5 = SCRIPTS / "standards.yaml"
STANDARDS_V6 = HISTORY / "standards-v6.yaml"

STANDARDS_CATEGORY = {
    "needless-layer": "needless_layer",
    "speculative-generality": "speculative",
    "global-state": "global",
    "duplicate-literal": "duplicate_literal",
    "hand-built-format": "handrolled_format",
    "erased-error-type": "error_erased",
    "error-type-wraps": "error_wrapper",
    "option-means-absence": "option_state",
    "layer-reaches-outward": "layer_reach",
    "layer-knows-foreign-encoding": "foreign_layout",
    "fabricated-placeholder": "placeholder",
    "timed-wait": "timed_wait",
    "bare-literal": "literal",
    "check-after-construction": "post_construction",
    "forgettable-check": "forgettable",
    "silent-failure": "silent",
    "non-idiomatic-error": "nonidiomatic",
    "propagation-stops-early": "propagation",
    "intermediate-abstraction": "abstraction",
    "edits-raw-text": "transform",
    "parallel-variant-table": "table",
    "invented-error-context": "context",
    "predicate-classifies": "classification",
    "default-outside-owner": "leaked_default",
    "comment-restates-code": "comment",
}

# standards-v2.yaml onward: a rule is suppressed when all of its gate questions are at or above GATE.
GATES_FILE = json.loads((SCRIPTS / "standards.gates.json").read_text())
GATES = {rule: tuple(names) for rule, names in GATES_FILE["gates"].items()}
GATE = GATES_FILE["gate"]


class UserError(Exception):
    pass


class Label(pydantic.BaseModel):
    expect: frozenset[str]
    allow: frozenset[str]


Labels = pydantic.RootModel[dict[str, Label]]

Answers = pydantic.RootModel[dict[str, float]]


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


async def run(*argv, stdin=None):
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(stdin)
    return proc.returncode, stdout.decode(), stderr.decode()


def strip_tests(diff):
    """The diff without the lines from a test module's `#[cfg(test)]` onward, as the hook sends it."""
    kept = []
    for line in diff.splitlines():
        if line[1:].startswith("#[cfg(test)]"):
            break
        kept.append(line)
    return "\n".join(kept) + "\n"


async def ask(question_set, state, name):
    if not any(
        line.startswith("+") and not line.startswith("+++")
        for line in state.splitlines()
    ):
        return {}
    code, stdout, stderr = await run(
        str(SCRIPTS / "jev-ask.py"),
        "-q",
        str(question_set),
        stdin=state.encode(),
    )
    if code != 0:
        raise UserError(f"jev-ask.py {name}: {stderr.strip()}")
    return Answers.model_validate_json(stdout).root


def flagged_v1(probs, threshold):
    return {
        STANDARDS_CATEGORY[q]
        for q, p in probs.items()
        if q in STANDARDS_CATEGORY and p >= threshold
    }


def flagged_v2(probs, threshold):
    return {
        STANDARDS_CATEGORY[q]
        for q, p in probs.items()
        if q in STANDARDS_CATEGORY
        and p >= threshold
        and not (q in GATES and all(probs[gate] >= GATE for gate in GATES[q]))
    }


# A category no question asks about is reported apart, not counted as a miss.
COVERED = frozenset(STANDARDS_CATEGORY.values())


def score(flagged, label):
    hits = flagged & label.expect
    misses = (label.expect & COVERED) - flagged
    false_alarms = flagged - label.expect - label.allow
    return hits, misses, false_alarms


def report(name, results, labels, verbose):
    totals = [0, 0, 0]
    rows = []
    for case, flagged in results.items():
        hits, misses, false_alarms = score(flagged, labels[case])
        for i, part in enumerate((hits, misses, false_alarms)):
            totals[i] += len(part)
        marks = []
        if misses:
            marks.append(f"missed {sorted(misses)}")
        if false_alarms:
            marks.append(f"false alarm {sorted(false_alarms)}")
        if marks:
            rows.append(f"    {case:32} {'; '.join(marks)}")
    print(
        f"{name:52} hits={totals[0]} misses={totals[1]} false_alarms={totals[2]}"
    )
    if verbose:
        print("\n".join(rows))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--thresholds", type=float, nargs="+", default=[0.5, 0.6, 0.7, 0.8]
    )
    parser.add_argument(
        "--out", type=pathlib.Path, help="write raw answers to this JSON file"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="list each miss and false alarm"
    )
    parser.add_argument(
        "--from",
        dest="saved",
        type=pathlib.Path,
        help="score answers saved by --out instead of calling the API",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=["v1", "v2", "v3", "v4", "v5", "v6"],
        default=["v5", "v6"],
    )
    args = parser.parse_args()

    labels = Labels.model_validate_json(
        (HERE / "labels.json").read_text()
    ).root
    cases = sorted((HERE / "cases").glob("*.diff"))
    unlabelled = {c.stem for c in cases} - labels.keys()
    if unlabelled:
        raise UserError(f"cases without labels: {sorted(unlabelled)}")
    names = [c.stem for c in cases]

    async def answers_for(variant):
        match variant:
            case "v1":
                calls = (ask(STANDARDS, c.read_text(), c.stem) for c in cases)
            case "v2" | "v3" | "v4" | "v5" | "v6":
                path = {
                    "v2": STANDARDS_V2,
                    "v3": STANDARDS_V3,
                    "v4": STANDARDS_V4,
                    "v5": STANDARDS_V5,
                    "v6": STANDARDS_V6,
                }[variant]
                calls = (
                    ask(path, strip_tests(c.read_text()), c.stem)
                    for c in cases
                )
        # One call at a time: each is a separate process.
        return dict(zip(names, [await call for call in calls]))

    if args.saved:
        saved = json.loads(args.saved.read_text())
        results = {v: saved[v] for v in args.variants if v in saved}
    else:
        results = {v: await answers_for(v) for v in args.variants}
    if args.out:
        args.out.write_text(json_dumps(results))

    for variant, answers in results.items():
        match variant:
            case "v1":
                for threshold in args.thresholds:
                    report(
                        f"standards.yaml >= {threshold}",
                        {
                            c: flagged_v1(p, threshold)
                            for c, p in answers.items()
                        },
                        labels,
                        args.verbose,
                    )
            case "v2" | "v3" | "v4" | "v5" | "v6":
                for threshold in args.thresholds:
                    report(
                        f"standards-{variant}.yaml >= {threshold}, gated, tests stripped",
                        {
                            c: flagged_v2(p, threshold)
                            for c, p in answers.items()
                        },
                        labels,
                        args.verbose,
                    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
