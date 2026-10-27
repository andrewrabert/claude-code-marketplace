import type { ProcessRunInit, ProcessRunResult, Register, ToolSpec } from 'claude-code'

const AGENT_TYPE = 'jev:edit'

const SCAN_TOOL = 'scan'

const AUDIT_AGENT_TYPE = 'jev:audit'

// The sandbox tools: each call runs scripts/jev-bash.py once, in the calling
// jev agent's scope.
const SANDBOX_TOOLS: readonly ToolSpec[] = [
  {
    name: 'bash',
    description:
      'Run a shell command. Standard output and standard error are returned together, followed by ' +
      'the exit code when it is nonzero. Each call starts a new shell: the working directory and ' +
      'variables do not carry over. /tmp is your own and keeps its files.',
    inputSchema: {
      type: 'object',
      properties: { command: { type: 'string' }, description: { type: 'string' } },
      required: ['command', 'description'],
    },
  },
  {
    name: 'read',
    description:
      'Read a text file with numbered lines. The path must be absolute. Use offset and limit to ' +
      'select a range of lines.',
    inputSchema: {
      type: 'object',
      properties: {
        file_path: { type: 'string' },
        limit: { type: ['integer', 'null'], minimum: 0 },
        offset: { type: ['integer', 'null'], minimum: 0 },
      },
      required: ['file_path'],
    },
  },
  {
    name: 'write',
    description:
      'Write a text file. The path must be absolute, and missing parent directories are created ' +
      'automatically.',
    inputSchema: {
      type: 'object',
      properties: { content: { type: 'string' }, file_path: { type: 'string' } },
      required: ['file_path', 'content'],
    },
  },
  {
    name: 'edit',
    description:
      'Replace exact text in a file. By default the old text must occur exactly once; set ' +
      'replace_all to replace every occurrence.',
    inputSchema: {
      type: 'object',
      properties: {
        file_path: { type: 'string' },
        new_string: { type: 'string' },
        old_string: { type: 'string' },
        replace_all: { default: false, type: 'boolean' },
      },
      required: ['file_path', 'old_string', 'new_string'],
    },
  },
]

// The keys of a tool.call input that are not the tool's arguments.
const ENVELOPE_KEYS: ReadonlySet<string> = new Set(['tool', 'tool_use_id', 'agentId', 'requestMeta'])

// The arguments a jev:audit agent's one scan runs with, from its prompt.
type ScanRequest = { path: string; base?: string }

// The directories a jev agent's bash and file tools mount read-write, named by its spawner.
type Scope = readonly string[]

const SCOPE_FORMAT = '"scope": [<absolute path of a directory>, ...]'

// Each jev agent type's prompt format, for the refusal of any other prompt.
const PROMPT_FORMATS: Readonly<Record<string, string>> = {
  [AUDIT_AGENT_TYPE]:
    `exactly {"path": "<absolute path of a file or directory>", "base": "<git revision>", ${SCOPE_FORMAT}}, base optional`,
  [AGENT_TYPE]: `a first line of exactly {${SCOPE_FORMAT}}, then the edit instructions`,
}

// A jev agent's sandbox: the scope its spawner named, and its own temp
// directory, mounted at /tmp.
type Sandbox = { scope: Scope; tmp: string }

// A spawn's parsed prompt: the scope, and the prompt the agent runs with.
type SpawnPrompt = { scope: Scope; prompt: string; request?: ScanRequest }

// A question set's decision logic, read from the `.gates.json` beside it and
// shared with scripts/jev-scan.py and the calibration in calibration/standards.
type Gates = {
  // A noul answer at or above this flags the question.
  threshold: number
  // A gated rule is suppressed when every one of its gate questions is at or above this.
  gate: number
  // Rule question to the gate questions that together suppress it. Gate
  // questions are never reported as findings.
  gates: Readonly<Record<string, readonly string[]>>
}

// For a question set with no gates file.
const DEFAULT_GATES: Gates = { threshold: 0.75, gate: 0.5, gates: {} }

type QuestionSet = {
  // Matched against the path's basename; the first entry that matches applies.
  globs: readonly string[]
  // Relative to the plugin's scripts/; the change is reviewed against each, one at a time.
  sets: readonly string[]
  // A line marking where test code starts; it and everything after it is left out of the review.
  testModule?: string
}

// text.yaml, the rules for comments, error text and prose, applies to every file.
const QUESTION_SETS: readonly QuestionSet[] = [
  { globs: ['*.rs'], sets: ['standards.yaml', 'text.yaml'], testModule: '#[cfg(test)]' },
  { globs: ['*'], sets: ['text.yaml'] },
]

const WRITE_TOOLS: ReadonlySet<string> = new Set(['Edit', 'Write', 'mcp__jev__edit', 'mcp__jev__write'])

const globToRegExp = (glob: string): RegExp =>
  new RegExp(`^${glob.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`)

const SET_MATCHERS = QUESTION_SETS.map(questionSet => ({
  patterns: questionSet.globs.map(globToRegExp),
  questionSet,
}))

const setFor = (path: string): QuestionSet | undefined => {
  const basename = path.slice(path.lastIndexOf('/') + 1)
  return SET_MATCHERS.find(({ patterns }) => patterns.some(pattern => pattern.test(basename)))
    ?.questionSet
}

const HUNK_HEADER = /^@@ -\d+(?:,\d+)? \+(\d+)/

// The diff's lines whose line number in the new file is below `cutoff`, with
// the file headers before the first hunk.
const truncateDiff = (diff: string, cutoff: number): string => {
  let line = 0
  return diff
    .split('\n')
    .filter(text => {
      const hunk = HUNK_HEADER.exec(text)
      if (hunk) {
        line = Number(hunk[1])
        return line < cutoff
      }
      if (line === 0 || text.startsWith('\\')) {
        return line < cutoff
      }
      const isKept = line < cutoff
      line += 1
      return isKept
    })
    .join('\n')
}

const hasAddedLines = (diff: string): boolean =>
  diff.split('\n').some(line => line.startsWith('+') && !line.startsWith('+++'))

const isFinding = (
  question: string,
  answers: Readonly<Record<string, number>>,
  { threshold, gate, gates }: Gates,
): boolean => {
  const gating = gates[question]
  return (
    (answers[question] ?? 0) >= threshold &&
    !Object.values(gates).some(names => names.includes(question)) &&
    !(gating !== undefined && gating.every(name => (answers[name] ?? 0) >= gate))
  )
}

const isGates = (value: unknown): value is Gates =>
  isRecord(value) &&
  typeof value.threshold === 'number' &&
  typeof value.gate === 'number' &&
  isRecord(value.gates) &&
  Object.values(value.gates).every(
    names => Array.isArray(names) && names.every(name => typeof name === 'string'),
  )

const dirname = (path: string): string => path.slice(0, path.lastIndexOf('/')) || '/'

// Each jev:audit agent's scan arguments, from its prompt at spawn.
const scanRequests = new Map<string, ScanRequest>()

// A scope, or why `value` is not one.
const parseScope = (value: unknown): Scope | string =>
  Array.isArray(value) &&
  value.length > 0 &&
  value.every(root => typeof root === 'string' && root.startsWith('/'))
    ? value
    : 'scope is not a non-empty array of absolute paths'

// A jev:audit prompt, or why `prompt` is not one. The agent runs with the scan
// request alone.
const parseAuditPrompt = (prompt: string): SpawnPrompt | string => {
  const parsed = parseJson(prompt.trim())
  if (!isRecord(parsed)) {
    return 'the prompt is not a JSON object'
  }
  const { path, base, scope, ...rest } = parsed
  const extra = Object.keys(rest)
  if (extra.length > 0) {
    return `unknown keys ${extra.join(', ')}`
  }
  if (typeof path !== 'string' || !path.startsWith('/')) {
    return 'path is not an absolute path'
  }
  if (base !== undefined && (typeof base !== 'string' || base === '' || base.startsWith('-'))) {
    return 'base is not a git revision'
  }
  const roots = parseScope(scope)
  if (typeof roots === 'string') {
    return roots
  }
  const request: ScanRequest = base === undefined ? { path } : { path, base }
  return { scope: roots, prompt: JSON.stringify(request), request }
}

// A jev:edit prompt, or why `prompt` is not one. The agent runs with the
// instructions after the scope line.
const parseEditPrompt = (prompt: string): SpawnPrompt | string => {
  const newline = prompt.indexOf('\n')
  const parsed = parseJson(newline === -1 ? prompt : prompt.slice(0, newline))
  if (!isRecord(parsed)) {
    return 'the first line is not a JSON object'
  }
  const { scope, ...rest } = parsed
  const extra = Object.keys(rest)
  if (extra.length > 0) {
    return `unknown keys ${extra.join(', ')}`
  }
  const roots = parseScope(scope)
  if (typeof roots === 'string') {
    return roots
  }
  const instructions = newline === -1 ? '' : prompt.slice(newline + 1).trim()
  if (instructions === '') {
    return 'the edit instructions are missing'
  }
  return { scope: roots, prompt: instructions }
}

const SPAWN_PARSERS: Readonly<Record<string, (prompt: string) => SpawnPrompt | string>> = {
  [AUDIT_AGENT_TYPE]: parseAuditPrompt,
  [AGENT_TYPE]: parseEditPrompt,
}

// Each jev agent's sandbox, made at its spawn; its temp directory is removed
// when the session ends.
const sandboxes = new Map<string, Sandbox>()

// The agentIds that have run their one scan; '' is the main loop, whose scan
// is per turn.
const scanned = new Set<string>()

// Whether each agentId belongs to a jev:edit agent; an agent's type is fixed at spawn.
const isJevEdit = new Map<string, boolean>()

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

const isNumberRecord = (value: unknown): value is Record<string, number> =>
  typeof value === 'object' &&
  value !== null &&
  Object.values(value).every(v => typeof v === 'number')

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const asText = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined

// What a question asks, what a violation looks like and what it accepts, from one question of
// `jev-ask.py --dry-run`'s canonical payload. `instructions` is a string, or an
// object holding `statement` or `question`.
const describe = (question: unknown): string => {
  if (!isRecord(question)) {
    return ''
  }
  const { instructions, criteria } = question
  const asks = isRecord(instructions)
    ? asText(instructions.statement) ?? asText(instructions.question)
    : asText(instructions)
  const violation = isRecord(criteria) ? asText(criteria.true) : undefined
  const accepted = isRecord(criteria) ? asText(criteria.false) : undefined
  return [asks, violation && `Violation: ${violation}`, accepted && `Accepted: ${accepted}`]
    .filter(Boolean)
    .join('\n  ')
}

// Question descriptions per question set path, read once from a dry run.
const descriptions = new Map<string, Readonly<Record<string, string>>>()

type Run = (argv: readonly string[], init?: ProcessRunInit) => Promise<ProcessRunResult>

const describeSet = async (
  run: Run,
  setPath: string,
): Promise<Readonly<Record<string, string>> | undefined> => {
  const dry = await run([`${dirname(setPath)}/jev-ask.py`, '--dry-run', '-q', setPath], {
    stdin: 'x',
  })
  const payload = parseJson(dry.stdout)
  if (dry.exitCode !== 0 || !isRecord(payload) || !isRecord(payload.questions)) {
    return undefined
  }
  const described = Object.fromEntries(
    Object.entries(payload.questions).map(([name, question]) => [name, describe(question)]),
  )
  descriptions.set(setPath, described)
  return described
}

export const register: Register = on => {
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (result.deny !== undefined || !WRITE_TOOLS.has(e.tool) || e.agentId === undefined) {
      return result
    }
    const agentId = e.agentId
    const known = isJevEdit.get(agentId)
    const applies =
      known ?? (await $.agent.list()).find(agent => agent.id === agentId)?.type === AGENT_TYPE
    isJevEdit.set(agentId, applies)
    const path = 'file_path' in e ? e.file_path : undefined
    if (!applies || typeof path !== 'string' || !path.startsWith('/')) {
      return result
    }
    const set = setFor(path)
    if (set === undefined) {
      return result
    }

    const fail = (reason: string) => {
      $.ui.toast(`${$.plugin.name}: ${reason}`)
      return { ...result, context: [...(result.context ?? []), `jev review of ${path} failed: ${reason}`] }
    }

    // A tracked file diffs against the index; an untracked one, or one outside
    // a repository, diffs against /dev/null.
    const cwd = dirname(path)
    const tracked = await $.process.run(['git', 'diff', '-W', '--', path], { cwd })
    const diff =
      tracked.exitCode === 0 && tracked.stdout.trim()
        ? tracked
        : await $.process.run(['git', 'diff', '--no-index', '--', '/dev/null', path], { cwd })
    // --no-index exits 1 when the files differ.
    if (diff.exitCode > 1 || !diff.stdout.trim()) {
      return fail(`git diff: ${diff.stderr.trim() || 'no changes found'}`)
    }
    const added = diff.stdout
      .split('\n')
      .filter(line => !line.startsWith('-') || line.startsWith('---'))
      .join('\n')
    // grep exits 1 when the file has no test module.
    const marker =
      set.testModule === undefined
        ? undefined
        : await $.process.run(['grep', '-n', '-m1', '-x', '-F', set.testModule, path])
    if (marker !== undefined && marker.exitCode > 1) {
      return fail(`grep ${set.testModule}: ${marker.stderr.trim()}`)
    }
    const cutoff = marker === undefined ? Number.NaN : Number.parseInt(marker.stdout, 10)
    const state = Number.isNaN(cutoff) ? added : truncateDiff(added, cutoff)
    if (!hasAddedLines(state)) {
      return result
    }

    const reviews: string[] = []
    // A question two of the sets both ask is reported once, from the first set.
    const reported = new Set<string>()
    for (const name of set.sets) {
      const setPath = `${$.plugin.root}/scripts/${name}`
      const ask = await $.process.run([`${dirname(setPath)}/jev-ask.py`, '-q', setPath], {
        stdin: state,
      })
      if (ask.exitCode !== 0) {
        return fail(`jev-ask.py: ${ask.stderr.trim()}`)
      }
      const answers = parseJson(ask.stdout)
      if (!isNumberRecord(answers)) {
        return fail(`jev-ask.py returned no noul answers: ${ask.stdout.trim()}`)
      }
      // Exits 3 when the question set has no gates file.
      const gatesFile = await $.process.run([
        'sh',
        '-c',
        'test -e "$1" || exit 3; cat "$1"',
        'sh',
        setPath.replace(/\.yaml$/, '.gates.json'),
      ])
      const gates = gatesFile.exitCode === 3 ? DEFAULT_GATES : parseJson(gatesFile.stdout)
      if (gatesFile.exitCode !== 0 && gatesFile.exitCode !== 3) {
        return fail(`reading gates for ${setPath}: ${gatesFile.stderr.trim()}`)
      }
      if (!isGates(gates)) {
        return fail(`gates for ${setPath} are not { threshold, gate, gates }`)
      }
      const flagged = Object.entries(answers).filter(
        ([question]) => isFinding(question, answers, gates) && !reported.has(question),
      )
      for (const [question] of flagged) {
        reported.add(question)
      }
      if (flagged.length === 0) {
        continue
      }
      const described = descriptions.get(setPath) ?? (await describeSet((argv, init) => $.process.run(argv, init), setPath))
      if (described === undefined) {
        return fail(`jev-ask.py --dry-run could not read the questions in ${setPath}`)
      }
      reviews.push(
        [
          `jev review of ${path} against ${name}, flagged at >= ${gates.threshold}:`,
          ...flagged.map(([question, p]) => `- ${question} (${p.toFixed(2)}): ${described[question] ?? ''}`),
        ].join('\n'),
      )
    }
    if (reviews.length === 0) {
      return result
    }
    return { ...result, context: [...(result.context ?? []), ...reviews] }
  }).catch((_, e, next) => next(e))

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: SCAN_TOOL,
      description:
        "Review code and text in a git repository with jev against the user's standards: a file or a " +
        'directory, every top-level item (Rust fn, method, struct, enum, const; Python function, method, ' +
        'class, assignment; any other file whole; a directory scans its .rs, .py and .md files), or with ' +
        '`base` only the hunks of any text file changed since that revision. Every file is reviewed ' +
        'against the comment, error-text and prose rules; Rust also against the Rust standards. Each item ' +
        'costs one paid call per rule set, and an agent gets one scan: pass ' +
        'the narrowest path and the base the request names. Returns one JSON line per finding: file, ' +
        'start, end, item, question, probability, asks (what the rule says), violation (what a ' +
        'violation looks like) and accepted (similar code the rule allows); then {"failure": ...} ' +
        'lines for items jev could not review, and a summary line. Findings are unverified: about 1 in 7 items of accepted code gets a false one. ' +
        'A large repository can take minutes.',
      inputSchema: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Absolute path of a file or a directory inside a git repository.',
          },
          base: {
            type: 'string',
            description:
              'A git revision. Reviews only what changed from its merge-base with HEAD to the working ' +
              'tree, plus untracked files: "HEAD" for uncommitted changes, "main" for the branch.',
          },
        },
        required: ['path'],
      },
    })
    for (const tool of SANDBOX_TOOLS) {
      await $.tool.register(tool)
    }
    return started
  })

  on('agent.spawn', async ($, e, next) => {
    const parse = SPAWN_PARSERS[e.subagentType]
    if (parse === undefined) {
      return next(e)
    }
    const parsed = parse(e.prompt)
    if (typeof parsed === 'string') {
      return { deny: `${e.subagentType} takes a prompt of ${PROMPT_FORMATS[e.subagentType]}: ${parsed}.` }
    }
    const made = await $.process.run(['sh', '-c', 'mktemp -d "${TMPDIR:-/tmp}/claude-code-jev.XXXXXX"'])
    if (made.exitCode !== 0) {
      return { deny: `mktemp for ${e.subagentType} failed: ${made.stderr.trim()}` }
    }
    const tmp = made.stdout.trim()
    const spawned = await next({ ...e, prompt: parsed.prompt })
    const agentId = spawned.agentId
    if (agentId === undefined) {
      await $.process.run(['rm', '-rf', '--', tmp])
      return spawned
    }
    if (parsed.request !== undefined) {
      scanRequests.set(agentId, parsed.request)
    }
    sandboxes.set(agentId, { scope: parsed.scope, tmp })
    return spawned
  }).catch((_, e, next) =>
    next.called || SPAWN_PARSERS[e.subagentType] === undefined
      ? next(e)
      : { deny: `${e.subagentType} spawn check failed.` },
  )

  for (const { name } of SANDBOX_TOOLS) {
    on('tool.call', { tool: `mcp__jev__${name}` }, async ($, e) => {
      const sandbox = e.agentId === undefined ? undefined : sandboxes.get(e.agentId)
      if (sandbox === undefined) {
        return { deny: 'only a jev agent spawned with a scope can use this tool.' }
      }
      const args = Object.fromEntries(Object.entries(e).filter(([key]) => !ENVELOPE_KEYS.has(key)))
      // jev-bash.py exits 1 with the reason on stderr when the call fails.
      const call = await $.process.run(
        [
          `${$.plugin.root}/scripts/jev-bash.py`,
          ...sandbox.scope.flatMap(root => ['--root', root]),
          '--tmp',
          sandbox.tmp,
          name,
        ],
        { stdin: JSON.stringify(args), timeoutMs: 120_000 },
      )
      if (call.exitCode !== 0) {
        return { deny: call.stderr.trim() || `jev-bash.py exited with ${call.exitCode}.` }
      }
      return { result: call.stdout }
    })
  }

  // A resumed agent keeps its sandbox, so temp directories last until the session ends.
  on('session.end', async ($, e, next) => {
    const dirs = [...sandboxes.values()].map(sandbox => sandbox.tmp)
    sandboxes.clear()
    if (dirs.length > 0) {
      await $.process.run(['rm', '-rf', '--', ...dirs])
    }
    return next(e)
  })

  on('turn.complete', (_, e, next) => {
    if (e.agentId === undefined) {
      scanned.delete('')
    }
    return next(e)
  })

  on('tool.call', { tool: `mcp__jev__${SCAN_TOOL}` }, async ($, e) => {
    const scanner = e.agentId ?? ''
    if (scanned.has(scanner)) {
      return { deny: 'scan already ran for this agent this turn; use its result.' }
    }
    // A jev:audit agent scans what its prompt named, whatever arguments it passes.
    const request = scanRequests.get(scanner)
    if (
      request === undefined &&
      e.agentId !== undefined &&
      (await $.agent.list()).find(agent => agent.id === e.agentId)?.type === AUDIT_AGENT_TYPE
    ) {
      return { deny: `this ${AUDIT_AGENT_TYPE} agent has no scan request from its spawn.` }
    }
    const path = request !== undefined ? request.path : 'path' in e ? e.path : undefined
    const base = request !== undefined ? request.base : 'base' in e ? e.base : undefined
    if (typeof path !== 'string' || !path.startsWith('/')) {
      return { deny: 'path must be an absolute path of a file or a directory.' }
    }
    if (base !== undefined && typeof base !== 'string') {
      return { deny: 'base must be a git revision.' }
    }
    // Claimed before the scan runs, so a second call made in parallel is refused too.
    scanned.add(scanner)
    // jev-scan.py exits 2 when it reviewed some items and failed others.
    const scan = await $.process.run(
      [
        `${$.plugin.root}/scripts/jev-scan.py`,
        ...(base === undefined ? [] : ['--base', base]),
        path,
      ],
      { timeoutMs: 600_000 },
    )
    if (scan.exitCode !== 0 && scan.exitCode !== 2) {
      return { deny: `jev-scan.py failed: ${scan.stderr.trim()}` }
    }
    return { result: `${scan.stdout}${scan.stderr.trim().split('\n').at(-1) ?? ''}\n` }
  })
}
