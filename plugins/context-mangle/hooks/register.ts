import type { EngineInterface, PromptComposeSection, Register } from 'claude-code'

const AGENT_TYPE = 'context-mangle:run'

const TOOL_NAME = 'respond'

// The tool an agent calls to rewrite its own context: scripts/proxy.py applies
// each call it finds in a request's messages (MANGLE_TOOL there). The call's
// result is always MANGLE_RESULT, so nothing tells the agent what it matched.
const MANGLE_TOOL_NAME = 'mangle'

const MANGLE_RESULT = 'OK'

// The tag name around a settings field: a JSON object of config keys that
// scripts/proxy.py cuts from a request's system prompt (an agent's definition)
// or first message (a spawn's prompt) and applies to that request.
const SETTINGS_TAG = 'context-mangle'

// The prompt that ends the run: the run's settings field names it, so the
// proxy offers its request no tool.
const STOP_PROMPT = 'Reply with the single word "Done" then stop.'

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

// The proxy's start, made at the first spawn: true once API requests go through
// it. Reset when it exits, so the next spawn starts another.
let proxyStarted: Promise<boolean> | undefined

// The global config at configPath, which lists every value it takes:
//
//   system_prompt: null sends the default system prompt; a string replaces it,
//     as --system-prompt does, and "" sends none.
//   tools.minimal_descriptions: true blanks every tool's description and
//     strips the annotations of every tool's input schema (scripts/proxy.py).
//   tools.only: null offers every tool; a list of names offers only those
//     tools (scripts/proxy.py).
//   tools.remove: the names of the tools left out of every request
//     (scripts/proxy.py).
//   minimal_reminders: true leaves every MINOR_ATTACHMENTS reminder out of
//     every request.
//   no_reminders: true leaves every attachment out of every request.
//
// The session's start and each render re-read it and write it back with every
// missing or invalid value set to its default and every unknown key removed.
// An agent's settings field (SETTINGS_TAG) overrides its keys for that agent's
// requests, and adds the ones only a field takes: see scripts/proxy.py.
type Config = {
  system_prompt: string | null
  tools: { minimal_descriptions: boolean; only: string[] | null; remove: string[] }
  minimal_reminders: boolean
  no_reminders: boolean
}

// The attachment types minimal_reminders leaves out: the IDE's, remote and cloud
// sessions', the Claude app's and shared memory's, budgets', rarely used modes',
// the engine's nudges, and session_context (the email and git status).
const MINOR_ATTACHMENTS = new Set([
  'selected_lines_in_ide',
  'selected_lines_in_diff',
  'opened_file_in_ide',
  'remote_session_change',
  'dir_sync_notice',
  'tool_hosts_notice',
  'tool_hosts_correction',
  'claude_app_notice',
  'artifact_opening_prefetch',
  'cowork_memory_context',
  'account_memory_recall',
  'widget_context_hint',
  'budget_usd',
  'token_usage',
  'output_token_usage',
  'total_tokens_reminder',
  'auto_mode',
  'auto_mode_exit',
  'ultra_effort_enter',
  'ultra_effort_exit',
  'workflow_keyword_request',
  'workflow_size_guideline_change',
  'ultrathink_effort',
  'advisor_tool',
  'sandbox_instructions',
  'language',
  'prefix_delta',
  'critical_system_reminder',
  'batching_reminder',
  'secondary_reminder',
  'silent_turn_reminder',
  'elapsed_time_reminder',
  'output_limit_note',
  'todo_reminder',
  'task_reminder',
  'tool_search_usage_reminder',
  'bash_output_audience_note',
  'date',
  'date_change',
  'model',
  'session_context',
])

// The section that carries the config's system_prompt.
const SYSTEM_PROMPT_SECTION = 'context-mangle:system_prompt'

// The config's update in progress: each waits for the one before it, so no
// write overwrites another's.
let configUpdate: Promise<unknown> = Promise.resolve()

// context-mangle.json in CLAUDE_CONFIG_DIR, else in ~/.claude.
const configPath = async ($: EngineInterface): Promise<string> => {
  const base = (await $.env.get('CLAUDE_CONFIG_DIR')) || `${await $.env.get('HOME')}/.claude`
  return `${base}/context-mangle.json`
}

const asObject = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

// The config read from value, its invalid values replaced by their defaults.
const normalizeConfig = (value: unknown): Config => {
  const fields = asObject(value)
  const tools = asObject(fields.tools)
  return {
    system_prompt: typeof fields.system_prompt === 'string' ? fields.system_prompt : null,
    tools: {
      minimal_descriptions: typeof tools.minimal_descriptions === 'boolean' ? tools.minimal_descriptions : false,
      only: Array.isArray(tools.only) ? tools.only.filter(name => typeof name === 'string') : null,
      remove: Array.isArray(tools.remove) ? tools.remove.filter(name => typeof name === 'string') : [],
    },
    minimal_reminders: typeof fields.minimal_reminders === 'boolean' ? fields.minimal_reminders : false,
    no_reminders: typeof fields.no_reminders === 'boolean' ? fields.no_reminders : false,
  }
}

// Updates the config after every update before it, so no write overwrites another's.
const queueConfigUpdate = ($: EngineInterface): Promise<Config> => {
  const update = configUpdate.then(() => updateConfig($))
  configUpdate = update.catch(() => undefined)
  return update
}

const formatConfig = (config: Config) => `${JSON.stringify(config, null, 2)}\n`

// The config at configPath, written back when it lacks a value or holds an
// invalid one. A file that is not JSON is left as it is and read as the defaults.
async function updateConfig($: EngineInterface): Promise<Config> {
  const path = await configPath($)
  let text: string | undefined
  if (await $.fs.exists(path)) {
    try {
      text = await $.fs.read(path)
    } catch (error) {
      $.ui.log(`${$.plugin.name}: reading ${path} failed, so the defaults apply: ${String(error)}`)
      return normalizeConfig(undefined)
    }
  }
  let value: unknown
  if (text !== undefined) {
    try {
      value = JSON.parse(text)
    } catch {
      $.ui.log(`${$.plugin.name}: ${path} is not JSON, so the defaults apply and it is left unchanged.`)
      return normalizeConfig(undefined)
    }
  }
  const config = normalizeConfig(value)
  const formatted = formatConfig(config)
  if (text === undefined || JSON.stringify(value) !== JSON.stringify(config)) {
    try {
      await $.fs.write(path, formatted)
    } catch (error) {
      $.ui.log(`${$.plugin.name}: writing ${path} failed: ${String(error)}`)
    }
  }
  return config
}

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
    '--tag',
    SETTINGS_TAG,
    '--config',
    await configPath($),
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

// A settings field holding value, its `<` escaped so no text in it closes the tag.
const settingsField = (value: object): string =>
  `<${SETTINGS_TAG}>${JSON.stringify(value).replaceAll('<', '\\u003c')}</${SETTINGS_TAG}>`

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    // Written here too, so the proxy reads a complete config even in a session
    // whose system prompt the engine never composes (--system-prompt).
    await queueConfigUpdate($)
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
    await $.tool.register({
      name: MANGLE_TOOL_NAME,
      description:
        'Rewrites your own context with Python re.sub(pattern, replacement) on every later request. target "messages" rewrites the messages before this call; target "system" rewrites the system prompt. It cannot be undone.',
      inputSchema: {
        type: 'object',
        properties: {
          target: { type: 'string', enum: ['messages', 'system'] },
          pattern: { type: 'string' },
          replacement: { type: 'string' },
        },
        required: ['target', 'pattern', 'replacement'],
        additionalProperties: false,
      },
      isDeferred: false,
    })
    // Started here, so an --agent session's first request already goes through it.
    if (!(await ensureProxy($))) {
      $.ui.log(`${$.plugin.name}: its proxy did not start; requests are sent without their settings applied.`)
    }
    return started
  })

  // Only the default system prompt is composed here: an agent's own replaces it.
  on('prompt.compose', async ($, e, next) => {
    const systemPrompt = (await queueConfigUpdate($)).system_prompt
    if (systemPrompt === null) {
      return next(e)
    }
    const sections: PromptComposeSection[] = systemPrompt
      ? [{ id: SYSTEM_PROMPT_SECTION, text: systemPrompt, scope: 'session' }]
      : []
    return { sections }
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
      prompt: `${settingsField({ system_prompt: spec.systemPrompt, stop_prompt: STOP_PROMPT })}${prompt}`,
    })
    if (spawned.agentId !== undefined) {
      runs.set(spawned.agentId, { resultsFile: spec.resultsFile, prompt, source: spec.source })
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

  // The proxy applies the call: see scripts/proxy.py.
  on('tool.call', { tool: new RegExp(`^mcp__context-mangle__${MANGLE_TOOL_NAME}$`) }, () => ({
    result: MANGLE_RESULT,
  }))

  on('tool.check', { tool: `mcp__context-mangle__${MANGLE_TOOL_NAME}` }, () => ({ decision: 'allow' }))

  on('turn.complete', (_, e, next) => {
    if (e.agentId !== undefined) {
      runs.delete(e.agentId)
    }
    return next(e)
  })

  on('prompt.attachment', async ($, e, next) => {
    const config = await queueConfigUpdate($)
    if (config.no_reminders || (config.minimal_reminders && MINOR_ATTACHMENTS.has(e.type))) {
      return { text: null }
    }
    return next(e)
  })
}
