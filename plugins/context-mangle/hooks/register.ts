import type { EngineInterface, Register } from 'claude-code'

const AGENT_TYPE = 'context-mangle:run'

const TOOL_NAME = 'respond'

// The tag name around agents/ask.md's prompt: scripts/proxy.py cuts each request
// whose system prompt holds its opening and closing tags.
const ASK_TAG = 'context-mangle:ask'

// Opens the agent's spawn prompt, ahead of {"system_prompt", "prompt"}:
// scripts/proxy.py rewrites each request whose first message holds it.
const MARKER = '<context-mangle/>'

// The prompt that ends the run: on every other one, the proxy draws the reply
// again while it calls no tool.
const STOP_PROMPT = 'Reply with the single word "Done" then stop.'

// The attachment types the agent's requests carry, by type; every other
// attachment, whoever authored it, is left out.
const KEPT_ATTACHMENTS: ReadonlySet<string> = new Set()

// How long the proxy may take to print its port before a spawn is refused.
const PROXY_START_MS = 10_000

const PROMPT_FORMAT =
  'exactly {"system_prompt": "<text>", "results_file": "<absolute path>", "prompts": ["<text>", ...]}, or the same with "prompt_script": "<absolute path>" in place of "prompts"'

// Where a run's prompts come from: a list, the next one at `next`, or a script
// that is given the results file and prints the next prompt.
type Source = { prompts: string[]; next: number } | { script: string }

// One running agent: its results file, the prompt it is answering, and the source of the next.
type Run = { resultsFile: string; prompt: string; source: Source }

// The running agents, by agentId.
const runs = new Map<string, Run>()

// Whether each agentId seen at prompt.attachment is a run agent's.
const runAgents = new Map<string, boolean>()

// The proxy's start, made at the first spawn: true once API requests go through
// it. Reset when it exits, so the next spawn starts another.
let proxyStarted: Promise<boolean> | undefined

type Spec = { systemPrompt: string; resultsFile: string; source: Source }

const parseSpec = (prompt: string): Spec | { error: string } => {
  let value: unknown
  try {
    value = JSON.parse(prompt)
  } catch {
    return { error: 'the prompt is not JSON' }
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { error: 'the prompt is not a JSON object' }
  }
  const known = ['system_prompt', 'results_file', 'prompts', 'prompt_script']
  const extra = Object.keys(value).filter(key => !known.includes(key))
  if (extra.length > 0) {
    return { error: `unknown keys ${extra.join(', ')}` }
  }
  const fields = value as Record<string, unknown>
  if (typeof fields.system_prompt !== 'string') {
    return { error: 'system_prompt must be a string' }
  }
  if (typeof fields.results_file !== 'string' || !fields.results_file.startsWith('/')) {
    return { error: 'results_file must be an absolute path' }
  }
  if ((fields.prompts === undefined) === (fields.prompt_script === undefined)) {
    return { error: 'exactly one of prompts and prompt_script must be given' }
  }
  if (fields.prompts !== undefined) {
    if (!Array.isArray(fields.prompts) || !fields.prompts.every(p => typeof p === 'string')) {
      return { error: 'prompts must be an array of strings' }
    }
    return {
      systemPrompt: fields.system_prompt,
      resultsFile: fields.results_file,
      source: { prompts: fields.prompts as string[], next: 0 },
    }
  }
  if (typeof fields.prompt_script !== 'string' || !fields.prompt_script.startsWith('/')) {
    return { error: 'prompt_script must be an absolute path' }
  }
  return { systemPrompt: fields.system_prompt, resultsFile: fields.results_file, source: { script: fields.prompt_script } }
}

// The next prompt from the source, or undefined when it has none.
const nextPrompt = async ($: EngineInterface, source: Source, resultsFile: string): Promise<string | undefined> => {
  if ('prompts' in source) {
    const prompt = source.prompts[source.next]
    source.next += 1
    return prompt
  }
  const run = await $.process.run([source.script, resultsFile])
  return run.exitCode === 0 ? run.stdout : undefined
}

// Appends one result to the results file as a JSON line.
const appendResult = async ($: EngineInterface, resultsFile: string, prompt: string, response: string) => {
  const line = `${JSON.stringify({ prompt, response })}\n`
  return $.process.run(['sh', '-c', 'cat >> "$1"', 'sh', resultsFile], { stdin: line })
}

// Starts scripts/proxy.py and points the engine's API requests at it. The URL it
// forwards to is kept in CONTEXT_MANGLE_UPSTREAM, so a reload of this module
// forwards to the same one and not to the proxy it replaces.
async function startProxy($: EngineInterface): Promise<boolean> {
  const upstream =
    (await $.env.get('CONTEXT_MANGLE_UPSTREAM')) || (await $.env.get('ANTHROPIC_BASE_URL')) || 'https://api.anthropic.com'
  const argv = [
    `${$.plugin.root}/scripts/proxy.py`,
    '--upstream',
    upstream,
    '--marker',
    MARKER,
    '--stop-prompt',
    STOP_PROMPT,
    '--ask-tag',
    ASK_TAG,
  ]
  // CONTEXT_MANGLE_PROXY_LOG names the file the proxy appends each exchange to.
  const log = await $.env.get('CONTEXT_MANGLE_PROXY_LOG')
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
  await $.env.set('CONTEXT_MANGLE_UPSTREAM', upstream)
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

const isRunAgent = async ($: EngineInterface, agentId: string): Promise<boolean> => {
  const known = runAgents.get(agentId)
  if (known !== undefined) {
    return known
  }
  const info = (await $.agent.list()).find(a => a.id === agentId)
  if (info === undefined) {
    return false
  }
  const isRun = info.type === AGENT_TYPE
  runAgents.set(agentId, isRun)
  return isRun
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: TOOL_NAME,
      description: 'Respond',
      inputSchema: {
        type: 'object',
        properties: { response: { type: 'string' } },
        required: ['response'],
        additionalProperties: false,
      },
      isDeferred: false,
    })
    // Started here, so an --agent context-mangle:ask session's first request
    // already goes through it.
    if (!(await ensureProxy($))) {
      $.ui.log(`${$.plugin.name}: its proxy did not start; context-mangle:ask requests carry every turn.`)
    }
    return started
  })

  on('agent.spawn', { subagentType: AGENT_TYPE }, async ($, e, next) => {
    const spec = parseSpec(e.prompt)
    if ('error' in spec) {
      return { deny: `${AGENT_TYPE} takes a prompt of ${PROMPT_FORMAT}: ${spec.error}.` }
    }
    const prompt = await nextPrompt($, spec.source, spec.resultsFile)
    if (prompt === undefined) {
      return { deny: 'the prompt source has no prompt.' }
    }
    if (!(await ensureProxy($))) {
      return { deny: `${$.plugin.name}: its proxy did not start.` }
    }
    const spawned = await next({
      ...e,
      prompt: `${MARKER}${JSON.stringify({ system_prompt: spec.systemPrompt, prompt })}`,
    })
    if (spawned.agentId !== undefined) {
      runs.set(spawned.agentId, { resultsFile: spec.resultsFile, prompt, source: spec.source })
      runAgents.set(spawned.agentId, true)
    }
    return spawned
  }).catch((_, e, next) => (next.called ? next(e) : { deny: `${AGENT_TYPE} spawn check failed.` }))

  // The result is the agent's next prompt, or the stop prompt once the source has none.
  on('tool.call', { tool: new RegExp(`^mcp__context-mangle__${TOOL_NAME}$`) }, async ($, e) => {
    const run = e.agentId === undefined ? undefined : runs.get(e.agentId)
    if (run === undefined) {
      return { deny: `only a ${AGENT_TYPE} agent can use this tool.` }
    }
    const response = 'response' in e && typeof e.response === 'string' ? e.response : ''
    const appended = await appendResult($, run.resultsFile, run.prompt, response)
    if (appended.exitCode !== 0) {
      $.ui.log(`${$.plugin.name}: appending to ${run.resultsFile} failed: ${appended.stderr.trim()}`)
    }
    const prompt = await nextPrompt($, run.source, run.resultsFile)
    if (prompt === undefined) {
      return { result: STOP_PROMPT }
    }
    run.prompt = prompt
    return { result: prompt }
  }).catch(($, e, next) => (next.called ? next(e) : { deny: `${$.plugin.name}: its respond hook failed.` }))

  on('tool.check', { tool: `mcp__context-mangle__${TOOL_NAME}` }, () => ({ decision: 'allow' }))

  on('turn.complete', (_, e, next) => {
    if (e.agentId !== undefined) {
      runs.delete(e.agentId)
    }
    return next(e)
  })

  on('prompt.attachment', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined || KEPT_ATTACHMENTS.has(e.type) || !(await isRunAgent($, e.agentId))) {
      return result
    }
    return { ...result, text: null }
  })
}
