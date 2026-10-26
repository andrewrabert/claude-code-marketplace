import type { ProcessRunInit, ProcessRunResult, Register } from 'claude-code'

const AGENT_TYPE = 'jev:edit'

const SCAN_TOOL = 'scan'

const AUDIT_AGENT_TYPE = 'jev:audit'

// A jev:audit agent's prompt, which is exactly the arguments its one scan runs with.
type ScanRequest = { path: string; base?: string }

const SCAN_REQUEST_FORMAT = '{"path": "<absolute path of a .rs file or directory>", "base": "<git revision>"}, base optional'

// A question set's decision logic, read from the `.gates.json` beside it and
// shared with scripts/jev-scan and the calibration in calibration/standards.
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
  // Matched against the path's basename.
  globs: readonly string[]
  // Relative to the plugin's scripts/.
  set: string
  // A line marking where test code starts; it and everything after it is left out of the review.
  testModule?: string
}

const QUESTION_SETS: readonly QuestionSet[] = [
  { globs: ['*.rs'], set: 'standards.yaml', testModule: '#[cfg(test)]' },
  { globs: ['*.md'], set: 'prose.yaml' },
]

const WRITE_TOOLS: ReadonlySet<string> = new Set(
  ['Edit', 'Write'].concat(
    ['mcp__bxwrp__', 'mcp__ro-bxwrp__'].flatMap(prefix =>
      ['edit', 'write'].map(tool => prefix + tool),
    ),
  ),
)

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

// A scan request, or why `prompt` is not one.
const parseScanRequest = (prompt: string): ScanRequest | string => {
  const parsed = parseJson(prompt.trim())
  if (!isRecord(parsed)) {
    return 'the prompt is not a JSON object'
  }
  const { path, base, ...rest } = parsed
  const extra = Object.keys(rest)
  if (extra.length > 0) {
    return `unknown keys ${extra.join(', ')}`
  }
  if (typeof path !== 'string' || !path.startsWith('/')) {
    return 'path is not an absolute path'
  }
  if (base === undefined) {
    return { path }
  }
  if (typeof base !== 'string' || base === '' || base.startsWith('-')) {
    return 'base is not a git revision'
  }
  return { path, base }
}

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
// `jev ask --dry-run`'s canonical payload. `instructions` is a string, or an
// object holding `statement` (jev-lint form) or `question` (jevkit form).
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
  const dry = await run(['jev', 'ask', '-p', 'typesafe', '--dry-run', '-q', setPath], {
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

    const setPath = `${$.plugin.root}/scripts/${set.set}`
    const ask = await $.process.run(['jev', 'ask', '-p', 'typesafe', '-q', setPath], {
      stdin: state,
    })
    if (ask.exitCode !== 0) {
      return fail(`jev ask: ${ask.stderr.trim()}`)
    }
    const answers = parseJson(ask.stdout)
    if (!isNumberRecord(answers)) {
      return fail(`jev ask returned no noul answers: ${ask.stdout.trim()}`)
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
    const flagged = Object.entries(answers).filter(([question]) =>
      isFinding(question, answers, gates),
    )
    if (flagged.length === 0) {
      return result
    }
    const described = descriptions.get(setPath) ?? (await describeSet((argv, init) => $.process.run(argv, init), setPath))
    if (described === undefined) {
      return fail(`jev ask --dry-run could not read the questions in ${setPath}`)
    }
    const review = [
      `jev review of ${path}, flagged at >= ${gates.threshold}:`,
      ...flagged.map(([question, p]) => `- ${question} (${p.toFixed(2)}): ${described[question] ?? ''}`),
    ].join('\n')
    return { ...result, context: [...(result.context ?? []), review] }
  }).catch((_, e, next) => next(e))

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: SCAN_TOOL,
      description:
        "Review Rust code in a git repository with jev against the user's standards: a .rs file or a " +
        'directory, every top-level item (fn, method, struct, enum, const), or with `base` only the hunks ' +
        'changed since that revision. Each item costs one paid call, and an agent gets one scan: pass ' +
        'the narrowest path and the base the request names. Returns one JSON line per finding: file, ' +
        'start, end, item, question, probability, asks (what the rule says), violation (what a ' +
        'violation looks like) and accepted (similar code the rule allows); then {"failure": ...} ' +
        'lines for items jev could not review, and a summary line. Findings are unverified: about 1 in 7 items of accepted code gets a false one. ' +
        'Takes about 1 call per item; a large repository can take minutes.',
      inputSchema: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Absolute path of a .rs file, or of a directory, inside a git repository.',
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
    return started
  })

  on('agent.spawn', async (_, e, next) => {
    if (e.subagentType !== AUDIT_AGENT_TYPE) {
      return next(e)
    }
    const request = parseScanRequest(e.prompt)
    if (typeof request === 'string') {
      return { deny: `${AUDIT_AGENT_TYPE} takes a prompt of exactly ${SCAN_REQUEST_FORMAT}: ${request}.` }
    }
    const spawned = await next(e)
    if (spawned.agentId !== undefined) {
      scanRequests.set(spawned.agentId, request)
    }
    return spawned
  }).catch((_, e, next) =>
    next.called || e.subagentType !== AUDIT_AGENT_TYPE
      ? next(e)
      : { deny: `${AUDIT_AGENT_TYPE} spawn check failed.` },
  )

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
      return { deny: 'path must be an absolute path of a .rs file or a directory.' }
    }
    if (base !== undefined && typeof base !== 'string') {
      return { deny: 'base must be a git revision.' }
    }
    // Claimed before the scan runs, so a second call made in parallel is refused too.
    scanned.add(scanner)
    // jev-scan exits 2 when it reviewed some items and failed others.
    const scan = await $.process.run(
      [
        `${$.plugin.root}/scripts/jev-scan`,
        ...(base === undefined ? [] : ['--base', base]),
        path,
      ],
      { timeoutMs: 600_000 },
    )
    if (scan.exitCode !== 0 && scan.exitCode !== 2) {
      return { deny: `jev-scan failed: ${scan.stderr.trim()}` }
    }
    return { result: `${scan.stdout}${scan.stderr.trim().split('\n').at(-1) ?? ''}\n` }
  })
}
