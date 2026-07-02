export const meta = {
  name: 'session-findings-sweep',
  description: 'Mine a work-list of Claude Code sessions into per-session findings notes',
  phases: [{ title: 'Classify' }],
}

// Fan-out sweep for the session-findings skill. Do NOT hand-author this per run
// — generate the work-list with `session_findings.py worklist ... --digest-dir`
// and pass it as this workflow's `args`. Each agent gets ONE session's identity
// baked in (never "read the shared array and take index i"), so it can never
// collide with or skip another.
//
// args = {
//   skill:    "<abs path to session_findings.py>",   // for the `render` step
//   tmp:      "<writable dir for the interim findings.json>",
//   sessions: [ <work-list rows from `worklist`> ]     // each row self-contained
// }

if (!args || !Array.isArray(args.sessions) || !args.skill || !args.tmp) {
  throw new Error(
    'args must be {skill, tmp, sessions:[...]} — build sessions with `session_findings.py worklist --digest-dir`'
  )
}
const SKILL = args.skill
const TMP = args.tmp
const SESSIONS = args.sessions

// Return-summary shape — the classification itself is written to notes, not
// returned; agents return only a compact rollup line (schema-enforced).
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['session_id', 'skipped', 'n_bugs', 'n_process', 'n_learnings'],
  properties: {
    session_id: { type: 'string' },
    skipped: { type: 'boolean' },
    n_bugs: { type: 'integer' },
    n_process: { type: 'integer' },
    n_learnings: { type: 'integer' },
    top_learning: { type: 'string' },
  },
}

function prompt(w) {
  return `You classify ONE Claude Code session digest into a findings record and store it as notes. This session's identity is baked in below — do NOT read any manifest, work-list, or other session's data.

SESSION
  session_id:      ${w.session_id}
  project:         ${w.project}
  cwd:             ${w.cwd}
  title:           ${w.title}
  date:            ${w.date}
  branch:          ${w.branch}
  duration_min:    ${w.duration_min}
  turn_count:      ${w.turn_count}
  last_message_at: ${w.last_message_at}
  processed_at:    ${w.processed_at}
  index:           ${JSON.stringify(w.index)}
  digest_path:     ${w.digest_path}

STEPS
1. RESUME-CHECK: ReadNote "Claude/Session Findings/${w.session_id}/findings.json".
   If it already exists, do nothing else and return {session_id:"${w.session_id}", skipped:true, n_bugs:0, n_process:0, n_learnings:0}.
2. Read the digest JSON at digest_path (the Read tool). It is metadata + an ordered events[] stream: prompt (with is_correction), tool, note, and the split failure kinds error / tool_error / rejection.
3. Run via Bash: python3 ${SKILL} schema — it prints the canonical classification contract (the three arrays' field shapes and the exact allowed enum values; single source of truth, do not restate from memory). Classify into those three arrays (bugs[], process_problems[], learnings[]) using ONLY evidence present in the digest — never invent filenames, commits, or facts. Reflect rejection events in process_problems/learnings. Do NOT treat tool_error as a code bug. Capture everything real; use [] when genuinely none. Every enum field MUST be one of the values the schema lists.
4. Assemble the findings.json object: {schema_version:1, session_id, project, cwd, title, date, branch, duration_min, turn_count, last_message_at, processed_at, index, bugs, process_problems, learnings} — copy every metadata field verbatim from SESSION above (processed_at is already provided; do NOT call date).
5. WriteNote "Claude/Session Findings/${w.session_id}/findings.json" with that JSON pretty-printed (2-space indent).
6. Write the same JSON to ${TMP}/${w.session_id}.json (Write tool), then run via Bash: python3 ${SKILL} render ${TMP}/${w.session_id}.json — capture stdout as the markdown, and WriteNote "Claude/Session Findings/${w.session_id}/findings.md" with it.
7. Return {session_id:"${w.session_id}", skipped:false, n_bugs, n_process, n_learnings, top_learning:(single most useful learning text, or "")}.`
}

phase('Classify')
const results = await parallel(
  SESSIONS.map((w) => () =>
    agent(prompt(w), {
      label: `classify:${w.session_id.slice(0, 8)}`,
      phase: 'Classify',
      schema: SCHEMA,
    })
  )
)

const ok = results.filter(Boolean)
const written = ok.filter((r) => !r.skipped)
const skipped = ok.filter((r) => r.skipped)
const failed = results.length - ok.length
return {
  total: SESSIONS.length,
  written: written.length,
  skipped: skipped.length,
  failed,
  sessions_with_bugs: written
    .filter((r) => r.n_bugs > 0)
    .map((r) => ({ id: r.session_id.slice(0, 8), bugs: r.n_bugs })),
  learnings: written
    .filter((r) => r.n_learnings > 0)
    .map((r) => ({ id: r.session_id.slice(0, 8), n: r.n_learnings, top: r.top_learning || '' })),
}
