import type { Color, Register } from 'claude-code'

// Broad->narrow: the order the hooks concatenate them in.
const SCOPES = ['global', 'project', 'session'] as const
type Scope = (typeof SCOPES)[number]

// The moment each verifier fires. `all` is merged into every other mode at
// runtime, not duplicated into each.
const MODES = ['submit', 'stop', 'plan', 'ask', 'all'] as const
type Mode = (typeof MODES)[number]

const GATES = { plan: 'ExitPlanMode', ask: 'AskUserQuestion' } as const
type GateMode = keyof typeof GATES

type Verifiers = Partial<Record<Mode, string[]>>
type Gate = { token: string; verified: boolean }
type Args = Readonly<Record<string, unknown>>

const TOOL_PREFIX = 'mcp__handoff-verifier__'
const TOOL_PATTERN = /^mcp__handoff-verifier__/
const CONFIRM_TOOL = `${TOOL_PREFIX}confirm`

class ToolError extends Error {}

// What the helpers reach through. The engine admits `$` only as `$.noun.method(...)`
// at a hook's call site, so each hook builds this from its own `$`.
type Ctx = {
  sessionId: string
  root: string
  get: (key: string) => Promise<unknown>
  set: (key: string, value: unknown) => Promise<void>
  delete: (key: string) => Promise<void>
  redraw: () => void
}

const isOneOf = <T extends string>(list: readonly T[], value: unknown): value is T =>
  typeof value === 'string' && (list as readonly string[]).includes(value)

const verifiersKey = (ctx: Ctx, scope: Scope) => {
  switch (scope) {
    case 'global':
      return 'verifiers/global'
    case 'project':
      return `verifiers/project/${ctx.root}`
    case 'session':
      return `verifiers/session/${ctx.sessionId}`
  }
}

const gateKey = (sessionId: string, mode: GateMode) => `gate/${sessionId}/${mode}`

const load = async (ctx: Ctx, scope: Scope) =>
  ((await ctx.get(verifiersKey(ctx, scope))) ?? {}) as Verifiers

const entries = async (ctx: Ctx, scope: Scope, mode: Mode) =>
  (await load(ctx, scope))[mode] ?? []

const save = async (ctx: Ctx, scope: Scope, mode: Mode, list: string[]) => {
  const key = verifiersKey(ctx, scope)
  const { [mode]: _, ...rest } = await load(ctx, scope)
  const next: Verifiers = list.length ? { ...rest, [mode]: list } : rest
  if (Object.keys(next).length) {
    await ctx.set(key, next)
  } else {
    await ctx.delete(key)
  }
  // The /hv pane draws from the store, so every write redraws it.
  ctx.redraw()
}

// What a mode's hook injects: each scope's `all` entries then its own,
// scopes joined broad->narrow.
const joined = async (ctx: Ctx, mode: Mode) => {
  const parts: string[] = []
  for (const scope of SCOPES) {
    const verifiers = await load(ctx, scope)
    const list = mode === 'all'
      ? verifiers.all ?? []
      : [...(verifiers.all ?? []), ...(verifiers[mode] ?? [])]
    if (list.length) {
      parts.push(list.join('\n\n'))
    }
  }
  return parts.join('\n\n')
}

const newToken = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(8)), byte =>
    byte.toString(16).padStart(2, '0'),
  ).join('')

const proceed = (tool: string, token: string) =>
  'TO PROCEED: only after you have audited every constraint above and judge ZERO ' +
  `violations remain, call the \`${CONFIRM_TOOL}\` tool with token "${token}" to ` +
  `confirm this ${tool} gate. That confirmation unlocks exactly one ${tool} call — ` +
  `retry ${tool} immediately after. Do not confirm while any constraint is still violated.`

// The deny text for a gated call, or undefined to let it through. A confirmed
// token is spent here, so it lets exactly one call through.
const gateDenial = async (ctx: Ctx, mode: GateMode) => {
  const body = await joined(ctx, mode)
  if (!body) {
    return undefined
  }
  const key = gateKey(ctx.sessionId, mode)
  const held = (await ctx.get(key)) as Gate | undefined
  if (held?.verified) {
    await ctx.delete(key)
    return undefined
  }
  const token = held?.token ?? newToken()
  if (!held) {
    await ctx.set(key, { token, verified: false } satisfies Gate)
  }
  return `${body}\n\n${proceed(GATES[mode], token)}`
}

const scopeArg = (args: Args, isRequired = false): Scope => {
  const { scope } = args
  if (scope === undefined || scope === '') {
    if (isRequired) {
      throw new ToolError('read requires scope')
    }
    return 'session'
  }
  if (!isOneOf(SCOPES, scope)) {
    throw new ToolError(`unknown scope: ${JSON.stringify(scope)}`)
  }
  return scope
}

const modeArg = (args: Args): Mode => {
  const { mode } = args
  if (!isOneOf(MODES, mode)) {
    throw new ToolError(`unknown mode: ${JSON.stringify(mode)}`)
  }
  return mode
}

const indexArg = (args: Args) => {
  const { index } = args
  if (typeof index !== 'number' || !Number.isInteger(index)) {
    throw new ToolError('index must be an integer')
  }
  return index
}

const stringArg = (args: Args, name: string) => {
  const value = args[name]
  return typeof value === 'string' ? value : ''
}

const checkIndex = (list: readonly string[], index: number) => {
  if (!list.length) {
    throw new ToolError('no entries')
  }
  if (index < 0 || index >= list.length) {
    throw new ToolError(`index ${index} out of range (0..${list.length - 1})`)
  }
}

const render = (list: readonly string[]) =>
  list.map((text, i) => `${i}: ${text}`).join('\n')

const SCOPE_PROP = {
  type: 'string',
  enum: SCOPES,
  description:
    'Where the verifier lives. global = every project on this machine; project = ' +
    'this project on this machine, persisting across sessions (stored outside the ' +
    'repo, so it is NOT shared with collaborators or committed); session = this ' +
    'session only. The hooks concatenate the active scopes broad->narrow (global, ' +
    'then project, then session). DEFAULTS TO session, and session is the only safe ' +
    'default: its blast radius is zero and a wrong guess costs nothing, whereas ' +
    'project and global persist and are messy to discover and undo. Use a broader ' +
    "scope ONLY on an explicit instruction — project for 'for this project / across " +
    "my sessions here', global for 'all my projects / everywhere on this machine'. " +
    "Do NOT infer breadth from tone, repetition, or words like 'always'; 'always " +
    "remind yourself' still means session unless they say where.",
}

const MODE_PROP = {
  type: 'string',
  enum: MODES,
  description:
    'Which self-check. submit = a reminder injected each time you submit a prompt, at ' +
    'the start of a turn (the mirror of stop). stop = a reminder fed back when Claude ' +
    'finishes a turn, forcing one more reasoning turn before the turn ends. plan = a ' +
    'gate that blocks ExitPlanMode until the agent self-certifies via the confirm ' +
    'tool. ask = a gate that blocks AskUserQuestion the same way, forcing a real ' +
    'attempt before interrupting the user. all = applies to every mode; stored once ' +
    "and merged into each event's read at runtime.",
}

const INDEX_PROP = {
  type: 'integer',
  description:
    'Zero-based position of the entry, as shown by read/list. Indices are ' +
    'EPHEMERAL — they renumber whenever an entry is removed. Re-read the ' +
    'verifier before targeting an index, and make one mutation at a time.',
}

type Tool = {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  run: (ctx: Ctx, args: Args) => Promise<string>
}

const TOOLS: readonly Tool[] = [
  {
    name: 'list',
    description:
      'List every active verifier across all scopes — use this whenever the user asks ' +
      "what handoff verifiers are on ('are any verifiers active?', 'list my handoff " +
      "verifiers', 'what's set for this project / globally?'). Returns JSON " +
      '{mode: {"scope/index": text}} with the full text of every entry, so you can ' +
      'read and target entries by their scope/index. Takes no arguments.',
    inputSchema: { type: 'object', properties: {} },
    run: async ctx => {
      const out: Record<string, Record<string, string>> = {}
      for (const mode of [...MODES].sort()) {
        for (const scope of SCOPES) {
          for (const [i, text] of (await entries(ctx, scope, mode)).entries()) {
            out[mode] = { ...out[mode], [`${scope}/${i}`]: text }
          }
        }
      }
      return JSON.stringify(out, null, 2)
    },
  },
  {
    name: 'read',
    description:
      "Read a verifier's entries for one (scope, mode); errors if it is not set. " +
      'Returns each entry on its own line prefixed by its current index (`0: ...`). ' +
      'Use those indices to target edit/remove. Use list first to see what exists, ' +
      'then read the specific combination whose entries you need.',
    inputSchema: {
      type: 'object',
      properties: { scope: SCOPE_PROP, mode: MODE_PROP },
      required: ['scope', 'mode'],
    },
    run: async (ctx, args) => {
      const scope = scopeArg(args, true)
      const mode = modeArg(args)
      const list = await entries(ctx, scope, mode)
      if (!list.length) {
        throw new ToolError(`no ${mode} verifier at ${scope} scope`)
      }
      return render(list)
    },
  },
  {
    name: 'write',
    description:
      'Append a new entry to a verifier — use this to add a stop reminder, plan gate, ' +
      "or ask gate ('remind yourself to run tests before finishing', 'gate plan mode " +
      "so you double-check', 'add an ask verifier so you try first'). Each entry is " +
      'independent; the hook joins all entries for the mode. Creates the verifier if ' +
      "it does not exist. Returns the re-numbered list, the new entry last. To change " +
      'existing text use edit; to delete use remove.',
    inputSchema: {
      type: 'object',
      properties: {
        scope: SCOPE_PROP,
        mode: MODE_PROP,
        content: {
          type: 'string',
          description: 'Text of the entry to append; must not be empty.',
        },
      },
      required: ['mode', 'content'],
    },
    run: async (ctx, args) => {
      const scope = scopeArg(args)
      const mode = modeArg(args)
      const content = stringArg(args, 'content').trim()
      if (!content) {
        throw new ToolError('content must not be empty')
      }
      const list = [...(await entries(ctx, scope, mode)), content]
      await save(ctx, scope, mode, list)
      return `added ${mode} entry at ${scope} scope\n${render(list)}`
    },
  },
  {
    name: 'edit',
    description:
      'Exact-string replace within a single verifier entry — like the native Edit ' +
      'tool, but addressed by (scope, mode, index) instead of a file path. Use it to ' +
      "tweak existing text ('soften the global stop reminder') without rewriting it. " +
      'old_string must be present and unique within that entry unless replace_all is ' +
      'set. Re-read first: indices renumber after a remove.',
    inputSchema: {
      type: 'object',
      properties: {
        scope: SCOPE_PROP,
        mode: MODE_PROP,
        index: INDEX_PROP,
        old_string: {
          type: 'string',
          description: 'Exact text to replace; must be unique unless replace_all.',
        },
        new_string: { type: 'string', description: 'Replacement text.' },
        replace_all: {
          type: 'boolean',
          description: 'Replace every occurrence (default false).',
        },
      },
      required: ['mode', 'index', 'old_string', 'new_string'],
    },
    run: async (ctx, args) => {
      const scope = scopeArg(args)
      const mode = modeArg(args)
      const index = indexArg(args)
      const oldString = stringArg(args, 'old_string')
      const newString = stringArg(args, 'new_string')
      if (!oldString) {
        throw new ToolError('old_string must not be empty')
      }
      if (oldString === newString) {
        throw new ToolError('old_string and new_string are identical')
      }
      const list = await entries(ctx, scope, mode)
      checkIndex(list, index)
      const text = list[index] ?? ''
      const count = text.split(oldString).length - 1
      if (count === 0) {
        throw new ToolError(`old_string not found in ${scope} ${mode} entry ${index}`)
      }
      if (count > 1 && args.replace_all !== true) {
        throw new ToolError(
          `old_string is not unique in ${scope} ${mode} entry ${index} ` +
            `(${count} matches); pass replace_all to replace every match`,
        )
      }
      const newText = text.split(oldString).join(newString).trim()
      if (!newText) {
        throw new ToolError('entry text must not be empty')
      }
      await save(ctx, scope, mode, list.with(index, newText))
      return `edited ${mode} entry ${index} at ${scope} scope\n${index}: ${newText}`
    },
  },
  {
    name: 'remove',
    description:
      'Remove a single entry from a verifier, addressed by (scope, mode, index). Use ' +
      'list/read to see current indices first. Returns the re-numbered list; removing ' +
      'the last entry turns the verifier off entirely. Indices are ephemeral — remove ' +
      'one entry at a time and re-read before the next.',
    inputSchema: {
      type: 'object',
      properties: { scope: SCOPE_PROP, mode: MODE_PROP, index: INDEX_PROP },
      required: ['mode', 'index'],
    },
    run: async (ctx, args) => {
      const scope = scopeArg(args)
      const mode = modeArg(args)
      const index = indexArg(args)
      const list = await entries(ctx, scope, mode)
      checkIndex(list, index)
      const rest = list.toSpliced(index, 1)
      await save(ctx, scope, mode, rest)
      return rest.length
        ? `removed ${mode} entry ${index} at ${scope} scope\n${render(rest)}`
        : `removed ${mode} entry ${index} at ${scope} scope — verifier now empty`
    },
  },
  {
    name: 'confirm',
    description:
      "Confirm you have satisfied a plan or ask gate's constraints, using the token " +
      "shown in the gate's denial message. Call this only AFTER the gated tool " +
      '(ExitPlanMode or AskUserQuestion) has been blocked and shown its constraints ' +
      'and token, and only once you genuinely comply. Unlocks exactly one retry of ' +
      'that gated call.',
    inputSchema: {
      type: 'object',
      properties: {
        mode: {
          type: 'string',
          enum: Object.keys(GATES),
          description: 'plan (ExitPlanMode gate) or ask (AskUserQuestion gate).',
        },
        token: {
          type: 'string',
          description:
            "The token shown in the gate's denial message. Proves you saw this " +
            'specific gate; a stale or wrong token is rejected.',
        },
      },
      required: ['mode', 'token'],
    },
    run: async (ctx, args) => {
      const mode = modeArg(args)
      if (!(mode in GATES)) {
        throw new ToolError(`confirm applies to plan or ask (got ${JSON.stringify(mode)})`)
      }
      const key = gateKey(ctx.sessionId, mode as GateMode)
      const held = (await ctx.get(key)) as Gate | undefined
      if (held === undefined || held.token !== stringArg(args, 'token')) {
        throw new ToolError(
          `no matching pending ${mode} verification — make the gated call first so ` +
            'its constraints and token are shown, then confirm with that exact token',
        )
      }
      await ctx.set(key, { ...held, verified: true } satisfies Gate)
      return `${mode} verification confirmed — now retry your call once`
    },
  },
]

// The slash commands: /hv shows what is active, /hv-add and /hv-rm change it.
// A target is `<mode>` or `<scope>/<mode>`, an entry `<scope>/<mode>/<index>`,
// the address /hv prints.
const COMMANDS = [
  { name: 'hv', description: 'Show active handoff verifiers and their scopes' },
  {
    name: 'hv-add',
    description: 'Add a handoff verifier entry',
    argumentHint: '[scope/]<mode> <text>',
  },
  {
    name: 'hv-rm',
    description: 'Remove a handoff verifier entry',
    argumentHint: '<scope>/<mode>/<index>',
  },
] as const
type Command = (typeof COMMANDS)[number]['name']

// What a command run comes to: a change, logged as a transcript row the model
// never reads, or a mistake, answered as the command's text and drawn in the
// error colour. That text is a row the model reads.
type Outcome = { log: string } | { error: string }

const USAGE: Record<Command, Outcome> = {
  hv: { error: 'usage: /hv   (takes no arguments; opens the list of active verifiers)' },
  'hv-add': {
    error:
      `usage: /hv-add [scope/]<mode> <text>   scope: ${SCOPES.join('|')} ` +
      `(default session), mode: ${MODES.join('|')}`,
  },
  'hv-rm': { error: 'usage: /hv-rm <scope>/<mode>/<index>   (addresses as /hv shows them)' },
}

const parseTarget = (target: string) => {
  const parts = target.split('/')
  const [scope, mode] = parts.length === 1 ? ['session', parts[0]] : parts
  if (parts.length > 2 || !isOneOf(SCOPES, scope) || !isOneOf(MODES, mode)) {
    return undefined
  }
  return { scope, mode }
}

const PANE = 'handoff-verifier'
const ADDRESS_WIDTH = 18

// How the /hv pane colours each scope, broad to narrow.
const SCOPE_COLOR: Record<Scope, Color> = {
  global: 'claude',
  project: 'suggestion',
  session: 'success',
}

type Active = { scope: Scope; mode: Mode; index: number; text: string }

const active = async (ctx: Ctx) => {
  const rows: Active[] = []
  for (const mode of MODES) {
    for (const scope of SCOPES) {
      for (const [index, text] of (await entries(ctx, scope, mode)).entries()) {
        rows.push({ scope, mode, index, text })
      }
    }
  }
  return rows
}

const addEntry = async (ctx: Ctx, args: string): Promise<Outcome> => {
  const [target = ''] = args.trim().split(/\s/, 1)
  const parsed = parseTarget(target)
  const text = args.trim().slice(target.length).trim()
  if (!parsed || !text) {
    return USAGE['hv-add']
  }
  const list = [...(await entries(ctx, parsed.scope, parsed.mode)), text]
  await save(ctx, parsed.scope, parsed.mode, list)
  return { log: `added ${parsed.scope}/${parsed.mode}/${list.length - 1}` }
}

const removeEntry = async (ctx: Ctx, args: string): Promise<Outcome> => {
  const address = args.trim()
  const [scope = '', mode = '', position = '', ...rest] = address.split('/')
  const parsed = parseTarget(`${scope}/${mode}`)
  const index = Number(position)
  if (!parsed || rest.length || !/^\d+$/.test(position)) {
    return USAGE['hv-rm']
  }
  const list = await entries(ctx, parsed.scope, parsed.mode)
  if (list[index] === undefined) {
    return { error: `no entry at ${address} — run /hv for current addresses` }
  }
  await save(ctx, parsed.scope, parsed.mode, list.toSpliced(index, 1))
  return { log: `removed ${parsed.scope}/${parsed.mode}/${index}` }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await Promise.all([
      ...TOOLS.map(({ name, description, inputSchema }) =>
        $.tool.register({ name, description, inputSchema }),
      ),
      ...COMMANDS.map(command => $.command.register(command)),
    ])
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    for (const mode of Object.keys(GATES) as GateMode[]) {
      await $.store.delete(gateKey(e.sessionId, mode))
    }
    return next(e)
  })

  on('command.run', { command: /^hv(-add|-rm)?$/ }, async ($, e) => {
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    if (e.command === 'hv' && !e.args.trim()) {
      const opened = await $.ui.open({
        id: PANE,
        title: 'Handoff verifiers',
        focus: true,
        closeOnEscape: true,
      })
      if (!opened.isPlaced) {
        $.ui.log(`/hv list is waiting: ${opened.reason}`)
      }
      return {}
    }
    const outcome =
      e.command === 'hv-add'
        ? await addEntry(ctx, e.args)
        : e.command === 'hv-rm'
          ? await removeEntry(ctx, e.args)
          : USAGE.hv
    if ('error' in outcome) {
      return { text: outcome.error }
    }
    $.ui.log(outcome.log)
    return {}
  }).catch((_$, e, next) => {
    if (next.called) {
      return next(e)
    }
    return { text: `/${e.command} failed` }
  })

  // A command's text is only ever a mistake, so its row draws in the error
  // colour. The row is inline: a Text, never a Box.
  on(
    'ui.render',
    { component: 'CommandOutput', props: { command: /^hv(-add|-rm)?$/ } },
    async ($, e) => {
      const { Text } = $.ui.resolve(e)
      return <Text color="error">{e.props.text}</Text>
    },
  )

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    const rows = await active(ctx)
    return (
      <Box flexDirection="column">
        {rows.length === 0 && <Text dimColor>none active — add one with /hv-add</Text>}
        {rows.map(({ scope, mode, index, text }) => (
          <Box key={`${scope}/${mode}/${index}`} flexDirection="row" columnGap={1}>
            <Box flexShrink={0} width={ADDRESS_WIDTH}>
              <Text>
                <Text color={SCOPE_COLOR[scope]}>{scope}</Text>
                <Text dimColor>/</Text>
                <Text weight="semibold">{mode}</Text>
                <Text dimColor>/{index}</Text>
              </Text>
            </Box>
            <Box flexGrow={1} flexShrink={1}>
              <Text wrap="wrap">{text}</Text>
            </Box>
          </Box>
        ))}
        <Text dimColor>Esc close · /hv-add · /hv-rm &lt;address&gt;</Text>
      </Box>
    )
  })

  on('tool.call', { tool: TOOL_PATTERN }, async ($, e, next) => {
    const tool = TOOLS.find(({ name }) => `${TOOL_PREFIX}${name}` === e.tool)
    if (tool === undefined) {
      return next(e)
    }
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    try {
      return { result: await tool.run(ctx, e) }
    } catch (error) {
      if (error instanceof ToolError) {
        return { deny: `error: ${error.message}` }
      }
      throw error
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { deny: `${$.plugin.name}: its ${e.tool} tool failed.` },
  )

  on('tool.call', { tool: 'ExitPlanMode' }, async ($, e, next) => {
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    const deny = await gateDenial(ctx, 'plan')
    return deny === undefined ? next(e) : { deny }
  }).catch(($, e, next) =>
    next.called ? next(e) : { deny: `${$.plugin.name}: its plan gate failed.` },
  )

  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    const deny = await gateDenial(ctx, 'ask')
    return deny === undefined ? next(e) : { deny }
  }).catch(($, e, next) =>
    next.called ? next(e) : { deny: `${$.plugin.name}: its ask gate failed.` },
  )

  on('classic.UserPromptSubmit', async ($, e, next) => {
    const result = await next(e)
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    const body = await joined(ctx, 'submit')
    return body
      ? { ...result, additionalContext: [...(result.additionalContext ?? []), body] }
      : result
  })

  // stop_hook_active: this turn already continues from a Stop block, so the
  // reminder forces one more reasoning turn, not a loop.
  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    if (e.stop_hook_active) {
      return result
    }
    const ctx: Ctx = {
      sessionId: await $.session.id(),
      root: await $.session.root(),
      get: key => $.store.get(key),
      set: (key, value) => $.store.set(key, value),
      delete: key => $.store.delete(key),
      redraw: () => $.ui.invalidate('ui.render'),
    }
    const body = await joined(ctx, 'stop')
    if (!body) {
      return result
    }
    return { ...result, block: result.block ? `${result.block}\n\n${body}` : body }
  })
}
