import type { EngineInterface, Register } from 'claude-code'

const AGENT_TYPE = 'surface-tools:surface-justify'

const TOOL_NAME = 'justify'

const MAX_WORDS = 15

// The justify calls one node may fail before the agent is stopped.
const MAX_ATTEMPTS = 3

// Opens the agent's spawn prompt: scripts/proxy.py rewrites each request whose
// first message holds it.
const MARKER = '<surface-tools-justify-agent/>'

// What the agent is told ahead of each node. The proxy drops its system prompt
// and every earlier turn, so each node's prompt carries them whole.
const INSTRUCTIONS = `You say why one surface exists. The surface follows, with its parent's justification when it has a parent.

1. Decide why it justifies existing as a surface to the best you can decide based on the context provided to you.
2. Call the justify tool with one sentence of at most ${MAX_WORDS} words.`

// The prompt that ends the run: on every other one, the proxy draws the reply
// again while it calls no tool.
const STOP_PROMPT = 'Reply with the single word "Done" then stop.'

// The attachment types the agent's requests carry, by type; every other
// attachment, whoever authored it, is left out.
const KEPT_ATTACHMENTS: ReadonlySet<string> = new Set()

// How long the proxy may take to print its port before a spawn is refused.
const PROXY_START_MS = 10_000

const PROMPT_FORMAT = 'exactly {"capture": "<absolute path of a surface-spec --json capture>"}'

// The proxy's start, made at the first spawn: true once API requests go through
// it. Reset when it exits, so the next spawn starts another.
let proxyStarted: Promise<boolean> | undefined

// Whether each agentId seen at prompt.attachment is a surface-justify agent's.
const justifyAgents = new Map<string, boolean>()

// One running agent's place in its capture: the node it is on, the justify
// calls that node has failed, and why the run stopped short when it did.
type Run = { capture: string; node: number; attempts: number; failure?: string }

// The running surface-justify agents, by agentId.
const runs = new Map<string, Run>()

// The captures a running agent justifies: one agent per capture, since
// surface-spec justify rewrites the whole file.
const busyCaptures = new Set<string>()

const parseCapturePrompt = (prompt: string): string | { error: string } => {
  let value: unknown
  try {
    value = JSON.parse(prompt)
  } catch {
    return { error: 'the prompt is not JSON' }
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { error: 'the prompt is not a JSON object' }
  }
  const extra = Object.keys(value).filter(key => key !== 'capture')
  if (extra.length > 0) {
    return { error: `unknown keys ${extra.join(', ')}` }
  }
  const { capture } = value as Record<string, unknown>
  if (typeof capture !== 'string' || !capture.startsWith('/')) {
    return { error: 'capture must be an absolute path' }
  }
  return capture
}

type Part = { id: number; justified: boolean; parent: number | null }

// The capture's nodes, or the reason surface-spec parts failed.
const readParts = async ($: EngineInterface, capture: string): Promise<Part[] | { error: string }> => {
  const parts = await $.process.run(['surface-spec', 'parts', capture])
  if (parts.exitCode !== 0) {
    return { error: `surface-spec parts failed: ${parts.stderr.trim()}` }
  }
  return parts.stdout
    .split('\n')
    .filter(Boolean)
    .map(line => JSON.parse(line) as Part)
}

// The first unjustified node whose parent is justified, or undefined when there is none.
const nextNode = (parts: Part[]): Part | undefined => {
  const justified = new Set(parts.filter(p => p.justified).map(p => p.id))
  return parts.find(p => !p.justified && (p.parent === null || justified.has(p.parent)))
}

// The prompt for one node, or the reason surface-spec context failed.
const nodePrompt = async ($: EngineInterface, capture: string, node: number): Promise<string | { error: string }> => {
  const context = await $.process.run(['surface-spec', 'context', capture, String(node)])
  if (context.exitCode !== 0) {
    return { error: `surface-spec context failed: ${context.stderr.trim()}` }
  }
  return `${INSTRUCTIONS}\n\n${context.stdout}`
}

const wordCount = (text: string): number => text.trim().split(/\s+/).filter(Boolean).length

// Ends the run with a failure: the agent is told to stop, and its answer names why.
const stop = (run: Run, failure: string): { result: string } => {
  run.failure = failure
  return { result: STOP_PROMPT }
}

// Starts scripts/proxy.py and points the engine's API requests at it. The URL it
// forwards to is kept in SURFACE_TOOLS_UPSTREAM, so a reload of this module
// forwards to the same one and not to the proxy it replaces.
async function startProxy($: EngineInterface): Promise<boolean> {
  const upstream =
    (await $.env.get('SURFACE_TOOLS_UPSTREAM')) ||
    (await $.env.get('ANTHROPIC_BASE_URL')) ||
    'https://api.anthropic.com'
  const argv = [
    `${$.plugin.root}/scripts/proxy.py`,
    '--upstream',
    upstream,
    '--marker',
    MARKER,
    '--stop-prompt',
    STOP_PROMPT,
  ]
  // SURFACE_TOOLS_PROXY_LOG names the file the proxy appends each exchange to.
  const log = await $.env.get('SURFACE_TOOLS_PROXY_LOG')
  if (log) {
    argv.push('--log', log)
  }
  let ready: (port: string | undefined) => void = () => undefined
  const port = new Promise<string | undefined>(resolve => (ready = resolve))
  let proxyUrl: string | undefined
  // The loop is the proxy's life: it runs on after the spawn that started it.
  void (async () => {
    let stdout = ''
    try {
      const proxy = $.process.spawn({ argv })
      for await (const { stream, text } of proxy) {
        if (stream === 'stderr') {
          $.ui.log(`${$.plugin.name} proxy: ${text.trim()}`, { to: 'debug' })
          continue
        }
        stdout += text
        const match = /^port (\d+)$/m.exec(stdout)
        if (match) {
          ready(match[1])
        }
      }
    } catch (error) {
      $.ui.log(`${$.plugin.name}: the proxy failed: ${String(error)}`)
    }
    ready(undefined)
    proxyStarted = undefined
    if (proxyUrl !== undefined && (await $.env.get('ANTHROPIC_BASE_URL')) === proxyUrl) {
      $.ui.log(`${$.plugin.name}: the proxy exited; API requests go to ${upstream} again.`)
      await $.env.set('ANTHROPIC_BASE_URL', upstream)
    }
  })()
  const started = await Promise.race([port, $.clock.sleep(PROXY_START_MS).then(() => undefined)])
  if (started === undefined) {
    $.ui.log(`${$.plugin.name}: the proxy did not start.`)
    return false
  }
  proxyUrl = `http://127.0.0.1:${started}`
  await $.env.set('SURFACE_TOOLS_UPSTREAM', upstream)
  await $.env.set('ANTHROPIC_BASE_URL', proxyUrl)
  return true
}

const ensureProxy = async ($: EngineInterface): Promise<boolean> => {
  proxyStarted ??= startProxy($)
  const started = await proxyStarted
  if (!started) {
    proxyStarted = undefined
  }
  return started
}

const isJustifyAgent = async ($: EngineInterface, agentId: string): Promise<boolean> => {
  const known = justifyAgents.get(agentId)
  if (known !== undefined) {
    return known
  }
  const info = (await $.agent.list()).find(a => a.id === agentId)
  if (info === undefined) {
    return false
  }
  const isJustify = info.type === AGENT_TYPE
  justifyAgents.set(agentId, isJustify)
  return isJustify
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: TOOL_NAME,
      description: 'Record justification',
      inputSchema: {
        type: 'object',
        properties: { justification: { type: 'string' } },
        required: ['justification'],
        additionalProperties: false,
      },
      isDeferred: false,
    })
    return started
  })

  on('agent.spawn', { subagentType: AGENT_TYPE }, async ($, e, next) => {
    const capture = parseCapturePrompt(e.prompt)
    if (typeof capture !== 'string') {
      return { deny: `${AGENT_TYPE} takes a prompt of ${PROMPT_FORMAT}: ${capture.error}.` }
    }
    if (busyCaptures.has(capture)) {
      return { deny: `a ${AGENT_TYPE} agent is already justifying ${capture}.` }
    }
    const parts = await readParts($, capture)
    if ('error' in parts) {
      return { deny: parts.error }
    }
    const node = nextNode(parts)
    if (node === undefined) {
      return {
        deny: parts.every(p => p.justified)
          ? `every node of ${capture} is justified.`
          : `no unjustified node of ${capture} has a justified parent.`,
      }
    }
    const prompt = await nodePrompt($, capture, node.id)
    if (typeof prompt !== 'string') {
      return { deny: prompt.error }
    }
    // The agent runs only with its default context cut.
    if (!(await ensureProxy($))) {
      return { deny: `${$.plugin.name}: its context-cutting proxy did not start.` }
    }
    busyCaptures.add(capture)
    const spawned = await next({ ...e, prompt: `${MARKER}\n${prompt}` })
    if (spawned.agentId === undefined) {
      busyCaptures.delete(capture)
    } else {
      runs.set(spawned.agentId, { capture, node: node.id, attempts: 0 })
      justifyAgents.set(spawned.agentId, true)
    }
    return spawned
  }).catch((_, e, next) => (next.called ? next(e) : { deny: `${AGENT_TYPE} spawn check failed.` }))

  // Every outcome answers the prompt for the agent's next request: the same
  // node's after a failed call, the next node's after a written one, or the
  // stop prompt once no node is left or the run fails.
  on('tool.call', { tool: `mcp__surface-tools__${TOOL_NAME}` }, async ($, e) => {
    const run = e.agentId === undefined ? undefined : runs.get(e.agentId)
    if (run === undefined) {
      return { deny: `only a ${AGENT_TYPE} agent can use this tool.` }
    }
    if (run.failure !== undefined) {
      return { result: STOP_PROMPT }
    }
    const justification = 'justification' in e ? e.justification : undefined
    const words = typeof justification === 'string' ? wordCount(justification) : 0
    let written = false
    if (typeof justification === 'string' && words > 0 && words <= MAX_WORDS) {
      const result = await $.process.run(['surface-spec', 'justify', run.capture, String(run.node), justification.trim()])
      if (result.exitCode !== 0) {
        return stop(run, `surface-spec justify failed on node ${run.node}: ${result.stderr.trim()}`)
      }
      written = true
    }
    if (!written) {
      run.attempts += 1
      if (run.attempts >= MAX_ATTEMPTS) {
        return stop(run, `node ${run.node} failed ${run.attempts} justify calls.`)
      }
    } else {
      const parts = await readParts($, run.capture)
      if ('error' in parts) {
        return stop(run, parts.error)
      }
      const node = nextNode(parts)
      if (node === undefined) {
        return { result: STOP_PROMPT }
      }
      run.node = node.id
      run.attempts = 0
    }
    const prompt = await nodePrompt($, run.capture, run.node)
    return typeof prompt === 'string' ? { result: prompt } : stop(run, prompt.error)
  }).catch(($, e, next) => (next.called ? next(e) : { deny: `${$.plugin.name}: its justify hook failed.` }))

  on('tool.check', { tool: `mcp__surface-tools__${TOOL_NAME}` }, () => ({ decision: 'allow' }))

  // The agent's answer reports the run: an error unless every node is justified.
  on('turn.complete', async ($, e, next) => {
    const run = e.agentId === undefined ? undefined : runs.get(e.agentId)
    if (e.agentId === undefined || run === undefined) {
      return next(e)
    }
    runs.delete(e.agentId)
    busyCaptures.delete(run.capture)
    const parts = await readParts($, run.capture)
    if ('error' in parts) {
      return next({ ...e, answer: `ERROR: ${parts.error}` })
    }
    const unjustified = parts.filter(p => !p.justified).length
    if (run.failure !== undefined) {
      return next({ ...e, answer: `ERROR: ${run.failure} ${unjustified} nodes of ${run.capture} are unjustified.` })
    }
    if (unjustified > 0) {
      return next({ ...e, answer: `ERROR: ${AGENT_TYPE} stopped with ${unjustified} nodes of ${run.capture} unjustified.` })
    }
    return next({ ...e, answer: `Every node of ${run.capture} is justified.` })
  })

  on('prompt.attachment', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined || KEPT_ATTACHMENTS.has(e.type) || !(await isJustifyAgent($, e.agentId))) {
      return result
    }
    return { ...result, text: null }
  })
}
