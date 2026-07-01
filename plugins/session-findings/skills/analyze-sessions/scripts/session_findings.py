#!/usr/bin/env python3
"""Session-findings pipeline primitives.

Deterministic (no-model) transforms over Claude Code session transcripts:

  digest   <session.jsonl>            condense one transcript to a bug/friction digest
  render   <findings.json>            render a findings record to findings.md
  manifest <project-dir> [<dir>...]   enumerate sessions -> classification manifest
  worklist <project-dir> [<dir>...]   one-shot: digest each session to --digest-dir
                                      and emit the fan-out sweep's work-list

The model step (classifying a digest into bugs/process_problems/learnings) and
all note writes (via the notes MCP) live outside this script — see SKILL.md.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Correction = user pushing back on prior work. Bare "no"/"still"/"broken"
# anywhere is too noisy ("pay no attention"), so negations must lead the
# message; the rest are strong-enough phrases to match anywhere.
CORRECTION_LEAD_RE = re.compile(
    r"^\s*(no|nope|wrong|stop|revert|undo)\b", re.IGNORECASE
)
CORRECTION_RE = re.compile(
    r"\b(undo|undid|revert|that('?s| is)\s+(not|wrong)|doesn'?t work|"
    r"didn'?t work|not what|still (broken|not|failing)|incorrect|"
    r"that'?s wrong)\b",
    re.IGNORECASE,
)
# Strong command-failure markers only. is_error==True is the primary signal;
# this regex just catches failures whose is_error flag isn't set true. Generic
# "Error"/"error" is deliberately excluded — it matches successful file reads.
ERROR_RE = re.compile(
    r"Exit code [1-9]|Traceback \(most recent call last\)|"
    r"\berror\[E\d|panic:|Segmentation fault|FAILED\b",
)
SNIPPET = 220


def is_correction(text):
    return bool(CORRECTION_LEAD_RE.search(text) or CORRECTION_RE.search(text))


def _blocks(content):
    """Yield content blocks; a bare string becomes a single synthetic text block."""
    if isinstance(content, str):
        yield {"type": "text", "text": content}
    elif isinstance(content, list):
        yield from content


def _result_text(tr):
    c = tr.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict))
    return ""


def _tool_target(name, inp):
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        return inp.get("command", "")
    return inp.get("file_path", inp.get("path", ""))


def digest(path):
    """Condense one session .jsonl into a compact bug/friction digest dict."""
    records = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    title = branch = cwd = None
    times = []
    events = []
    n_prompts = n_assistant = n_errors = n_corrections = n_rejections = 0
    n_tool_errors = 0
    has_traceback = False

    for r in records:
        typ = r.get("type")
        if typ == "ai-title" and not title:
            title = r.get("aiTitle")
            continue
        if ts := r.get("timestamp"):
            times.append(ts)
        if b := r.get("gitBranch"):
            branch = b
        if cwd is None and (c := r.get("cwd")):
            cwd = c

        if typ == "user":
            content = r.get("message", {}).get("content")
            if isinstance(content, str):
                n_prompts += 1
                corr = is_correction(content)
                n_corrections += corr
                events.append(
                    {
                        "kind": "prompt",
                        "is_correction": corr,
                        "text": content[:600],
                    }
                )
            else:
                for blk in _blocks(content):
                    if blk.get("type") != "tool_result":
                        continue
                    text = _result_text(blk)
                    low = text.lower()
                    # is_error:true covers BOTH user rejections and real command
                    # failures; split them, and split out agent tool-misuse.
                    cmd_fail = bool(ERROR_RE.search(text))
                    is_tool_error = "<tool_use_error>" in low
                    is_reject = (
                        "want to proceed" in low
                        or "tool use was rejected" in low
                        or "[request interrupted" in low
                    )
                    if is_tool_error:
                        n_tool_errors += 1
                        events.append(
                            {"kind": "tool_error", "snippet": text[:SNIPPET]}
                        )
                    elif is_reject or (
                        blk.get("is_error") is True and not cmd_fail
                    ):
                        n_rejections += 1
                        events.append(
                            {"kind": "rejection", "snippet": text[:SNIPPET]}
                        )
                    elif blk.get("is_error") is True or cmd_fail:
                        n_errors += 1
                        if "Traceback (most recent call last)" in text:
                            has_traceback = True
                        events.append(
                            {"kind": "error", "snippet": text[:SNIPPET]}
                        )
        elif typ == "assistant":
            n_assistant += 1
            for blk in _blocks(r.get("message", {}).get("content")):
                bt = blk.get("type")
                if bt == "tool_use":
                    name = blk.get("name", "")
                    events.append(
                        {
                            "kind": "tool",
                            "name": name,
                            "target": _tool_target(name, blk.get("input"))[
                                :200
                            ],
                        }
                    )
                elif bt == "text":
                    txt = (blk.get("text") or "").strip()
                    if txt:
                        events.append({"kind": "note", "text": txt[:400]})

    started = min(times) if times else None
    ended = max(times) if times else None
    duration_min = None
    if started and ended:
        fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
        duration_min = round(
            (fmt(ended) - fmt(started)).total_seconds() / 60, 1
        )

    return {
        "session_id": Path(path).stem,
        "project": Path(path).parent.name,
        "cwd": cwd,
        "title": title,
        "branch": branch,
        "date": (started or "")[:10] or None,
        "started": started,
        "ended": ended,
        "duration_min": duration_min,
        "n_user_prompts": n_prompts,
        "n_assistant_turns": n_assistant,
        "turn_count": n_prompts + n_assistant,
        "index": {
            "n_errors": n_errors,
            "n_tool_errors": n_tool_errors,
            "n_corrections": n_corrections,
            "n_rejections": n_rejections,
            "has_traceback": has_traceback,
        },
        "events": events,
    }


def render(findings):
    """Render a findings record dict into the findings.md summary string."""
    d = findings
    ix = d.get("index", {})
    proj = (d.get("cwd") or "").rstrip("/").rsplit("/", 1)[-1] or None
    out = [f"# {d.get('title') or d['session_id']}"]
    meta = " · ".join(
        str(x)
        for x in [
            proj,
            d.get("date"),
            f"{d['duration_min']} min"
            if d.get("duration_min") is not None
            else None,
            f"{d['turn_count']} turns"
            if d.get("turn_count") is not None
            else None,
            f"branch {d['branch']}" if d.get("branch") else None,
        ]
        if x
    )
    out.append(f"*{meta}*")
    counts = ", ".join(
        f"{k}={ix[k]}"
        for k in ("n_errors", "n_tool_errors", "n_corrections", "n_rejections")
        if k in ix
    )
    if counts:
        out.append(f"`{counts}`")
    out.append("")

    bugs = d.get("bugs", [])
    out.append(f"## Bugs ({len(bugs)})")
    for b in bugs:
        out.append(
            f"- **[{b.get('category')}, {b.get('severity')}]** {b.get('one_line')}"
        )
        for label, key in (
            ("root cause", "root_cause"),
            ("found", "how_found"),
            ("fixed", "how_fixed"),
        ):
            if b.get(key):
                out.append(f"  - *{label}:* {b[key]}")
    if not bugs:
        out.append("- _none_")
    out.append("")

    pp = d.get("process_problems", [])
    out.append(f"## Friction ({len(pp)})")
    for p in pp:
        cost = f" (~{p['cost_turns']} turns)" if p.get("cost_turns") else ""
        out.append(f"- **{p.get('type')}**{cost}: {p.get('one_line')}")
    if not pp:
        out.append("- _none_")
    out.append("")

    lr = d.get("learnings", [])
    out.append(f"## Learnings ({len(lr)})")
    for learning in lr:
        tag = f"{learning.get('kind')}, {learning.get('suggested_scope')}/{learning.get('suggested_mode')}"
        out.append(f"- **[{tag}]** {learning.get('text')}")
        if learning.get("verifier_text"):
            out.append(f"  - *verifier:* {learning['verifier_text']}")
    if not lr:
        out.append("- _none_")
    out.append("")

    footer = f"session `{d['session_id']}`"
    if d.get("processed_at"):
        footer += f" · processed {d['processed_at']}"
    if d.get("last_message_at"):
        footer += f" · last message {d['last_message_at']}"
    footer += f" · schema v{d.get('schema_version', 1)}"
    out.append(f"<sub>{footer}</sub>")
    return "\n".join(out)


def _load_ids(ids_path):
    """Read an ids file (whitespace/comma-separated) into a set, or None."""
    if not ids_path:
        return None
    text = Path(ids_path).read_text()
    return {tok for tok in re.split(r"[\s,]+", text) if tok}


def _id_match(session_id, ids):
    """True if ids is None (no filter) or session_id equals/prefixes an entry.

    Callers routinely track sessions by the 8-char uuid prefix, so a short id
    matches the full session_id it prefixes.
    """
    if ids is None:
        return True
    return any(session_id == i or session_id.startswith(i) for i in ids)


def _manifest_entry(f, dg):
    """One manifest row from a session path and its digest."""
    return {
        "session_id": dg["session_id"],
        "path": str(f),
        "project": dg["project"],
        "cwd": dg["cwd"],
        "title": dg["title"],
        "branch": dg["branch"],
        "date": dg["date"],
        "duration_min": dg["duration_min"],
        "turn_count": dg["turn_count"],
        "index": dg["index"],
        "last_message_at": dg["ended"],
    }


def manifest(dirs, ids=None):
    """Enumerate sessions across project dirs into a classification manifest.

    ids (optional set): keep only sessions whose id equals or is prefixed by an
    entry — lets a sweep target a curated subset instead of whole project dirs.
    """
    out = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.jsonl")):
            if ids is not None and not _id_match(f.stem, ids):
                continue
            out.append(_manifest_entry(f, digest(str(f))))
    return out


def worklist(dirs, digest_dir, ids=None):
    """One-shot: digest each in-scope session and emit the fan-out work-list.

    Folds the enumerate -> filter -> digest -> assemble glue into one step:
    writes each session's digest JSON to digest_dir and returns work-list rows
    (manifest metadata + digest_path + a single processed_at stamp for the whole
    batch, so fan-out agents never need to call `date`).
    """
    digest_dir = Path(digest_dir)
    digest_dir.mkdir(parents=True, exist_ok=True)
    processed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.jsonl")):
            if ids is not None and not _id_match(f.stem, ids):
                continue
            dg = digest(str(f))
            dpath = digest_dir / f"{dg['session_id']}.json"
            dpath.write_text(json.dumps(dg, indent=2))
            row = _manifest_entry(f, dg)
            row["digest_path"] = str(dpath)
            row["processed_at"] = processed_at
            out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest").add_argument("path")
    sub.add_parser("render").add_argument("path")
    m = sub.add_parser("manifest")
    m.add_argument("dirs", nargs="+")
    m.add_argument("--ids", help="file of session ids/prefixes to keep")
    w = sub.add_parser("worklist")
    w.add_argument("dirs", nargs="+")
    w.add_argument(
        "--digest-dir", required=True, help="dir to write per-session digests"
    )
    w.add_argument("--ids", help="file of session ids/prefixes to keep")
    args = ap.parse_args()

    if args.cmd == "digest":
        print(json.dumps(digest(args.path), indent=2))
    elif args.cmd == "render":
        print(render(json.loads(Path(args.path).read_text())))
    elif args.cmd == "manifest":
        print(json.dumps(manifest(args.dirs, _load_ids(args.ids)), indent=1))
    elif args.cmd == "worklist":
        print(
            json.dumps(
                worklist(args.dirs, args.digest_dir, _load_ids(args.ids)),
                indent=1,
            )
        )


if __name__ == "__main__":
    sys.exit(main())
