---
name: plan
description: Use when explicitly asked to plan a task into notes (e.g. /plan) — work a task through read-only explore → design → review, then persist the plan as a noted note under dev/plans/ and open a noted task referencing it.
---

# plan

Work a task through a read-only planning pass, then keep the plan and its
tracking in the user's `noted` notes. Invoke this only when explicitly asked
(e.g. `/plan <task>`); never start it on your own.

The skill is a set of instructions, not an enforced mode — nothing stops you
from writing. Follow the read-only rule below by discipline. Refer to your
capabilities generically (question tool, sub-agents) so this works under any
agent with access to the `noted` MCP server.

## The noted MCP tools this skill uses

Tool names use the `mcp__noted__` prefix; map by the bare tool name if your
harness exposes the `noted` server under a different naming.

- `mcp__noted__SearchNotes` — find an existing related plan under `dev/plans/`.
- `mcp__noted__WriteNote` — write/overwrite the plan note.
- `mcp__noted__CreateTask` — open the tracking task in group `dev/plans`.
- `mcp__noted__UpdateTask` — advance the task's state.
- `mcp__noted__ReadNote`, `mcp__noted__GetTasks` — read a plan/task back.

## Workflow

### 0. Read-only until approved

Until the user explicitly approves the plan, take only read-only actions. The
*only* writes you may make are the plan note and its task in noted. Do not edit
code, run mutating shell commands, or make commits.

### 1. Understand

Start by searching for a prior plan so you build on it rather than duplicate:
`mcp__noted__SearchNotes(pattern="<keywords>", glob=["dev/plans"])`. If a
related plan exists, read it — it is context for everything below — and update
that note in place in step 4 instead of creating a new one.

Explore to understand the request and to find existing functions, utilities, and
patterns to reuse — avoid proposing new code where a suitable implementation
already exists. If your harness supports parallel read-only sub-agents, fan them
out; otherwise explore directly. When intent is ambiguous, ask clarifying
questions (your harness's question tool, or plain prose if it has none) before
designing.

### 2. Design

Decide one concrete implementation approach. Weigh alternatives internally, but
carry forward only the recommendation.

Select by this criterion: deliver the correct, ideal-world solution — the one
this codebase would have if written today with full knowledge. Scope is never a
constraint: a one-line fix and a total rewrite are equally acceptable answers;
choose by correctness alone. Do not patch symptoms when the root cause is
reachable. Do not leave TODOs, shims, fallbacks, or "for now" anywhere. If you
find yourself qualifying the result, the work is not done — resolve the
qualification or report the task incomplete. Verify every claim against the
actual code before asserting it. Anything less is failure, not partial success.

### 3. Review

Re-read the critical files you identified, confirm the approach matches what was
asked, and resolve any remaining open questions with the user.

### 4. Persist to noted

1. Write the plan note (or overwrite the prior plan found in step 1):
   `mcp__noted__WriteNote(path="dev/plans/<date>-<slug>.md", content=<plan>)`
   - `<date>` — today, `YYYYMMDD`, from your harness's current-date context.
   - `<slug>` — kebab-cased short task title.
   - Use `WriteNote`, not `LogNote` (which is immutable/timestamped) — a plan
     must stay editable. A plan is a note, not a `Tasks/` entry.
   - Plan content, concise but executable:
     - **Context** — why this change is being made; the problem or need.
     - **Approach** — the recommended approach only, not every alternative.
     - **Critical files** — the files to modify; name reusable functions and
       utilities to lean on, with their paths. For a pattern repeated across
       many files, describe it once with a few representative paths.
     - **Verification** — how to test the change end-to-end.

2. Open the tracking task:
   `mcp__noted__CreateTask(task="<one-line summary>", group="dev/plans",
   notes="<body that references dev/plans/<date>-<slug>.md>")`. noted assigns the
   `task_NNNN` filename; the task starts in state `created`.

### 5. Approve, then execute

Present the plan, its note path, and the task path, then wait for explicit
approval. Do not begin any non-read-only work until the user approves. On
approval, advance the task with `mcp__noted__UpdateTask(state="started")` and
implement. When the implementation is finished, set `state="completed"`; if the
user declines the plan, set `state="rejected"`. Terminal states (`blocked`,
`completed`, `rejected`, `invalid`) require a non-empty `notes` body explaining
why.

