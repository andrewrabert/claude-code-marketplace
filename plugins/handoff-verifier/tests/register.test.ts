import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const PLAN = { 'verifiers/global': { plan: ['run the tests'] } }

// The session the plugin keys its store on.
const inSession = (on: On) => {
  on('session.id', () => ({ value: 'session-1' }))
  on('session.root', () => ({ value: '/repo' }))
}

test('a plan verifier denies ExitPlanMode with its text and a token', async ($, on) => {
  inSession(on)
  mock.store(on, PLAN)
  on('tool.call', { tool: 'ExitPlanMode' }, () => ({ result: { plan: null, isAgent: false } }))

  const denied = await $.tool.call({ tool: 'ExitPlanMode' })

  expect(denied.deny).toMatch(/run the tests/)
  expect(denied.deny).toMatch(/token "[0-9a-f]{16}"/)
})

test('a confirmed gate lets exactly one ExitPlanMode through', async ($, on) => {
  inSession(on)
  mock.store(on, { ...PLAN, 'gate/session-1/plan': { token: 't', verified: true } })
  on('tool.call', { tool: 'ExitPlanMode' }, () => ({ result: { plan: null, isAgent: false } }))

  const passed = await $.tool.call({ tool: 'ExitPlanMode' })
  const denied = await $.tool.call({ tool: 'ExitPlanMode' })

  expect(passed.deny).toBeUndefined()
  expect(denied.deny).toMatch(/run the tests/)
})

test('no verifier leaves ExitPlanMode alone', async ($, on) => {
  inSession(on)
  mock.store(on)
  on('tool.call', { tool: 'ExitPlanMode' }, () => ({ result: { plan: null, isAgent: false } }))

  const passed = await $.tool.call({ tool: 'ExitPlanMode' })

  expect(passed.deny).toBeUndefined()
})

// A command as the person types it at the prompt.
const run = (command: string, args = '') => ({
  command,
  args,
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 80 },
}) as const

// What the commands log: rows the person sees, never the command's text.
const logged = (on: On) => {
  const lines: string[] = []
  on('ui.log', (_$, e) => {
    lines.push(e.text)
    return { value: undefined }
  })
  return lines
}

test('/hv-add, /hv and /hv-rm log, never answer with text', async ($, on) => {
  inSession(on)
  mock.store(on)
  const lines = logged(on)

  const added = await $.command.run(run('hv-add', 'project/stop run the tests'))
  expect(added.text).toBeUndefined()
  await $.command.run(run('hv-add', 'plan check the plan'))
  await $.command.run(run('hv-rm', 'project/stop/0'))

  expect(lines).toEqual(['added project/stop/0', 'added session/plan/0', 'removed project/stop/0'])
})

const PANE = {
  plugin: 'handoff-verifier',
  component: 'Pane',
  requestId: 'handoff-verifier',
  props: {
    title: 'Handoff verifiers',
    isFocused: true,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

test('the /hv pane lists each active entry by its address', async ($, on) => {
  inSession(on)
  mock.store(on, { 'verifiers/global': { stop: ['run the tests'] } })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ text: /global\/stop\/0/ })).toBeDefined()
    expect(await ui.find({ text: /run the tests/ })).toBeDefined()
    await ui.unmount()
  }
})

test('a mistaken command answers its error as text, not a log row', async ($, on) => {
  inSession(on)
  mock.store(on)
  const lines = logged(on)

  const noText = await $.command.run(run('hv-add', 'stop'))
  const badMode = await $.command.run(run('hv-add', 'nope text'))
  const noEntry = await $.command.run(run('hv-rm', 'session/stop/0'))

  expect(lines).toEqual([])
  expect(noText.text).toMatch(/^usage: \/hv-add/)
  expect(badMode.text).toMatch(/^usage: \/hv-add/)
  expect(noEntry.text).toMatch(/^no entry at session\/stop\/0/)
})
