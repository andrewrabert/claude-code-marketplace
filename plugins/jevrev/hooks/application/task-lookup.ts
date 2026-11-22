import { type AgentId, type AgentRuntime, isAgentType, type Task, type Tasks } from '../domain/session.ts'

// How long an agent's first call waits for its spawn to record its task.
const BIND_WAIT_MS = 5_000

// A jevrev agent's task, waiting briefly for its spawn hook when its first
// call races ahead of it.
export const taskOf = async (runtime: AgentRuntime, tasks: Tasks, agent: AgentId | undefined): Promise<Task | undefined> => {
  if (agent === undefined) {
    return undefined
  }
  const known = tasks.of(agent)
  if (known !== undefined) {
    return known
  }
  if (!isAgentType(await runtime.typeOf(agent))) {
    return undefined
  }
  for (let waited = 0; waited < BIND_WAIT_MS; waited += 50) {
    await runtime.sleep(50)
    const task = tasks.of(agent)
    if (task !== undefined) {
      return task
    }
  }
  return undefined
}
