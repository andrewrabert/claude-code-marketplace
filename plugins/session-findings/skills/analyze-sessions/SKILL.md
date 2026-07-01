---
name: analyze-sessions
description: Use when analyzing Claude Code session history to learn what bugs were fixed, where development got stuck, or what lessons recur — mines transcripts into self-contained per-session findings notes (bugs, friction, learnings) and supports a resumable multi-session sweep whose learnings can feed verifiers
---

# Analyze Sessions

Mine Claude Code session transcripts into per-session **findings**: the bugs
fixed, the development friction hit, and the reusable learnings. Output is one
self-contained folder per session, stored as notes.

**Core principle: heuristics route, the model classifies.** A deterministic
digest pass finds *where* the signal is (errors, rejections, corrections); the
model decides *what kind*. Never rank sessions by raw counts alone.

## Where sessions live

`<config-dir>/projects/<url-encoded-cwd>/<session-uuid>.jsonl`, where
`<config-dir>` is Claude Code's config directory (`~/.claude` by default, or
`$CLAUDE_CONFIG_DIR` if set). Each line is a typed record (`user`,
`assistant`, `ai-title`, …). One encoded dir per distinct `cwd`; the same repo
can appear under several dirs (path variants, subdir cwds).

## Tooling

`scripts/session_findings.py` — deterministic, no-model primitives:

```sh
session_findings.py digest   <session.jsonl>          # transcript -> digest JSON
session_findings.py render   <findings.json>          # findings record -> findings.md
session_findings.py manifest <project-dir> [<dir>...] # enumerate sessions -> manifest JSON
```

The digest is what the model classifies — it keeps raw transcripts (tens of MB)
away from the model. `manifest` is the sweep's work-list.

### Digest event taxonomy

The digest is metadata + an ordered `events[]` stream. `is_error:true` in a
transcript conflates three unrelated things; the digest splits them — this split
is essential:

- `error` — real command/build/code failure (`Exit code [1-9]`, `Traceback`,
  `panic:`, `error[E`, `FAILED`).
- `tool_error` — the agent misused a tool (`<tool_use_error>`, e.g. Edit before
  Read). Self-corrects; **not** a code bug.
- `rejection` — the USER vetoed/redirected a tool call (rejected tool use,
  interrupt, or is_error prose with no failure marker). **The strongest friction
  signal** — invisible if lumped into `error`.

Plus `prompt` (with `is_correction`), `tool`, `note` (assistant text). Index
counters: `n_errors`, `n_tool_errors`, `n_corrections`, `n_rejections`,
`has_traceback`.

## Findings schema

The model classifies a digest into three arrays. Capture **everything** (incl.
session-specific or trivial items); use `[]` if genuinely none.

```json
{
  "schema_version": 1,
  "session_id": "...", "project": "<encoded dir>", "cwd": "...",
  "title": "...", "date": "YYYY-MM-DD", "branch": "...",
  "duration_min": 0, "turn_count": 0,
  "last_message_at": "<digest.ended>", "processed_at": "<date -u, at write time>",
  "index": { "n_errors": 0, "n_tool_errors": 0, "n_corrections": 0, "n_rejections": 0, "has_traceback": false },
  "bugs": [{
    "category": "crash|logic|type|test-failure|build-dep|config-tooling|docs-accuracy|render|concurrency|perf|integration",
    "one_line": "...", "root_cause": "...", "how_found": "...", "how_fixed": "...",
    "severity": "low|med|high"
  }],
  "process_problems": [{
    "type": "correction-loop|dead-end-revert|re-explaining|stall",
    "one_line": "...", "cost_turns": 0
  }],
  "learnings": [{
    "text": "generalizable guidance",
    "kind": "project-fact|gotcha|prevention-rule|process-rule",
    "evidence": "what in this session produced it",
    "suggested_scope": "global|project|session",
    "suggested_mode": "submit|stop|plan|ask|verify",
    "verifier_text": "ready-to-store text a verifier would inject/check"
  }]
}
```

Rules: use only evidence in the digest — never invent filenames or commits.
Reflect `rejection` events in `process_problems` and `learnings`. Do not treat
`tool_error` as a code bug. `category`/`kind`/`type`/`scope`/`mode` MUST be from
the enums above — enforce with structured output when running a sweep.

Each `learnings` entry is a candidate handoff-verifier entry (`scope` + `mode`
map to `handoff-verifier.py add -s <scope> -m <mode>`).

## Storage

Notes only — **the notes MCP tools (`WriteNote`/`ReadNote`/`SearchNotes`) are
the ONLY interface**, addressed by relative path. Never reference an on-disk
notes location.

One dedicated, **self-contained** folder per session, keyed by session id:

```
Claude/Session Findings/<session-id>/findings.json   # source of truth
Claude/Session Findings/<session-id>/findings.md     # readable (render output)
```

No central ledger — the folder's existence is the processed-marker; `when`,
`last message`, and `result` all live inside `findings.json`. Project grouping
is a later concern, derived from the `project`/`cwd` fields, not the path.

## Single session

1. `session_findings.py digest <path>` → digest.
2. Classify the digest into the schema (model).
3. Add `processed_at` (`date -u +%Y-%m-%dT%H:%M:%SZ`) and `last_message_at`
   (digest `ended`); copy metadata.
4. `WriteNote` the findings JSON; `session_findings.py render` it; `WriteNote`
   the `.md`.

## Multi-session sweep

For a project (or the whole corpus), a fan-out Workflow — one classifier agent
per session — writing self-contained folders.

1. Build the work-list: `session_findings.py manifest <dir>...` → array of
   `{session_id, path, project, cwd, title, branch, date, duration_min,
   turn_count, index, last_message_at}`. Write per-session digests to a temp dir.
2. Workflow: one `agent()` per session. Each agent, given its own session baked
   in: resume-check (`ReadNote` the `findings.json` → skip if present) → read its
   digest → classify → stamp `processed_at` → `WriteNote` both files → return a
   small summary (schema-enforced).
3. **Verify against the notes** (`SearchNotes` the prefix), not the workflow's
   returned rollup, then remediate any gaps with targeted per-session agents.

### Hard-won rules (do not repeat these)

- **Bake each session's identity directly into its agent** — session_id,
  digest path, metadata. NEVER tell an agent to "read the shared manifest and
  take element index i": an LLM miscounts indexing a large array, causing
  collisions (some sessions processed twice, others skipped).
- **On-disk notes are the source of truth**, not agent return values. A
  workflow's rollup can double-count collisions; always diff `SearchNotes`
  output against the expected session ids.
- **Rank hotspots by `duration_min` + `n_user_prompts` + `n_rejections`**, never
  by error count — a long adversarial debugging session can score
  `n_errors:1`, identical to a trivial one.
- Self-contained folders + the resume-check make re-runs idempotent: safe to
  re-launch a sweep; done sessions are skipped.
- **Fill in small targeted batches, don't re-burst the whole corpus.** At a few
  hundred concurrent agents the API rate-limits hard (transient server-side),
  and re-launching all N again — even mostly resume-check skips, since each skip
  still costs one call — compounds it. After a throttled run: recompute the
  MISSING set (one cheap agent diffing `SearchNotes` vs the manifest), build a
  missing-only manifest, and sweep just those. Repeat on the residual; it
  converges in a few small passes.

## Verification

- `session_findings.py digest <path> | jq .index` — spot-check counts; confirm a
  known rejection lands as `rejection`, a real failure as `error`, an
  Edit-before-Read as `tool_error`.
- After a sweep, `SearchNotes` the `Claude/Session Findings` prefix and diff the
  written session ids against the manifest; open a couple of `findings.md` to
  confirm root causes are grounded and nothing is invented.
