import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const inSession = (on: On) => {
  on('session.id', () => ({ value: 'session-1' }))
  on('session.root', () => ({ value: '/repo' }))
}

test('a stop verifier blocks Stop with its text', async ($, on) => {
  inSession(on)
  mock.store(on, { 'verifiers/global': { stop: ['check the diff'] } })
  on('classic.Stop', () => ({}))
  const result = await $.classic.Stop({ stop_hook_active: false })
  expect(result.block).toMatch(/check the diff/)
})

test('a submit verifier adds context to the prompt', async ($, on) => {
  inSession(on)
  mock.store(on, { 'verifiers/global': { submit: ['be terse'] } })
  on('classic.UserPromptSubmit', () => ({}))
  const result = await $.classic.UserPromptSubmit({ prompt: 'hi' })
  expect(result.additionalContext?.join('\n')).toMatch(/be terse/)
})
