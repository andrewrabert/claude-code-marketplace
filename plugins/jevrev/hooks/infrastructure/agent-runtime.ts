import type { EngineInterface } from 'claude-code'

import type { AgentRuntime } from '../domain/session.ts'

export function agentRuntime($: EngineInterface): AgentRuntime {
  return {
    typeOf: async agent => (await $.agent.list()).find(listed => listed.id === `${agent}`)?.type,
    sleep: ms => $.clock.sleep(ms),
  }
}
