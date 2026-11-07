import type { Register } from 'claude-code'

const AGENT_TYPE = 'surface-tools:surface-justify'

const TOOL_NAME = 'justify'

const MAX_WORDS = 15

const PROMPT_FORMAT = 'exactly {"capture": "<absolute path of a surface-spec --json capture>", "node": <node id>}'

// The node a spawned agent justifies, from its spawn prompt.
type Target = { capture: string; node: number }

// The agentIds that may still call the tool, each with the node it justifies.
const targets = new Map<string, Target>()

// The tail of the justify calls made on each capture: surface-spec justify
// rewrites the whole file, so calls on one capture run one at a time.
const captureLocks = new Map<string, Promise<unknown>>()

const parsePrompt = (prompt: string): Target | string => {
  let value: unknown
  try {
    value = JSON.parse(prompt)
  } catch {
    return 'the prompt is not JSON'
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return 'the prompt is not a JSON object'
  }
  const extra = Object.keys(value).filter(key => key !== 'capture' && key !== 'node')
  if (extra.length > 0) {
    return `unknown keys ${extra.join(', ')}`
  }
  const { capture, node } = value as Record<string, unknown>
  if (typeof capture !== 'string' || !capture.startsWith('/')) {
    return 'capture must be an absolute path'
  }
  if (typeof node !== 'number' || !Number.isSafeInteger(node) || node < 0) {
    return 'node must be a non-negative integer'
  }
  return { capture, node }
}

const wordCount = (text: string): number => text.trim().split(/\s+/).filter(Boolean).length

const withCaptureLock = async <T>(capture: string, run: () => Promise<T>): Promise<T> => {
  const previous = captureLocks.get(capture) ?? Promise.resolve()
  const current = previous.then(run, run)
  const tail = current.catch(() => undefined)
  captureLocks.set(capture, tail)
  try {
    return await current
  } finally {
    if (captureLocks.get(capture) === tail) {
      captureLocks.delete(capture)
    }
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: TOOL_NAME,
      description: 'Record justification',
      inputSchema: {
        type: 'object',
        properties: {
          justification: {
            type: 'string',
            pattern: `^\\s*\\S+(\\s+\\S+){0,${MAX_WORDS - 1}}\\s*$`,
          },
        },
        required: ['justification'],
        additionalProperties: false,
      },
      isDeferred: false,
    })
    return started
  })

  on('agent.spawn', async ($, e, next) => {
    if (e.subagentType !== AGENT_TYPE) {
      return next(e)
    }
    const target = parsePrompt(e.prompt)
    if (typeof target === 'string') {
      return { deny: `${AGENT_TYPE} takes a prompt of ${PROMPT_FORMAT}: ${target}.` }
    }
    const parts = await $.process.run(['surface-spec', 'parts', target.capture])
    if (parts.exitCode !== 0) {
      return { deny: `surface-spec parts failed: ${parts.stderr.trim()}` }
    }
    const part = parts.stdout
      .split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line) as { id: number; justified: boolean })
      .find(p => p.id === target.node)
    if (part === undefined) {
      return { deny: `node ${target.node} is not among the nodes of ${target.capture}.` }
    }
    if (part.justified) {
      return { deny: `node ${target.node} of ${target.capture} is already justified.` }
    }
    const context = await $.process.run(['surface-spec', 'context', target.capture, String(target.node)])
    if (context.exitCode !== 0) {
      return { deny: `surface-spec context failed: ${context.stderr.trim()}` }
    }
    const spawned = await next({ ...e, prompt: context.stdout })
    if (spawned.agentId !== undefined) {
      targets.set(spawned.agentId, target)
    }
    return spawned
  }).catch((_, e, next) =>
    next.called || e.subagentType !== AGENT_TYPE ? next(e) : { deny: `${AGENT_TYPE} spawn check failed.` },
  )

  on('tool.call', { tool: `mcp__surface-tools__${TOOL_NAME}` }, async ($, e) => {
    const agentId = e.agentId
    const target = agentId === undefined ? undefined : targets.get(agentId)
    if (agentId === undefined || target === undefined) {
      return { deny: `only a ${AGENT_TYPE} agent that has not yet justified its node can use this tool.` }
    }
    const justification = 'justification' in e ? e.justification : undefined
    if (typeof justification !== 'string' || wordCount(justification) === 0) {
      return { deny: 'justification must be a non-empty string.' }
    }
    const words = wordCount(justification)
    if (words > MAX_WORDS) {
      return { deny: `justification has ${words} words; the limit is ${MAX_WORDS}.` }
    }
    const sentence = justification.trim()
    // Claimed before the write runs, so a second call made in parallel is refused too.
    targets.delete(agentId)
    const written = await withCaptureLock(target.capture, () =>
      $.process.run(['surface-spec', 'justify', target.capture, String(target.node), sentence]),
    )
    if (written.exitCode !== 0) {
      targets.set(agentId, target)
      return { deny: `surface-spec justify failed: ${written.stderr.trim()}` }
    }
    return { result: sentence }
  }).catch(($, e, next) =>
    next.called ? next(e) : { deny: `${$.plugin.name}: its justify hook failed.` },
  )

  on('tool.check', { tool: `mcp__surface-tools__${TOOL_NAME}` }, () => ({ decision: 'allow' }))
}
