import type { Edit } from './agents/edit.ts'
import type { Review } from './agents/review.ts'
import type { Workspace } from './files.ts'

export const PLUGIN = 'jevrev'

export const REVIEW_AGENT = `${PLUGIN}:review` as const

export const EDIT_AGENT = `${PLUGIN}:edit` as const

export type AgentType = typeof REVIEW_AGENT | typeof EDIT_AGENT

export const isAgentType = (type: string | undefined): type is AgentType =>
  type === REVIEW_AGENT || type === EDIT_AGENT

// A review's outcome is settled once its first run ends; an edit agent resumes with its sandbox.
export const isResumable = (type: string): boolean => type !== REVIEW_AGENT

export const RESUME_REFUSAL = `a ${REVIEW_AGENT} agent cannot be resumed; spawn a new one.`

export type Task = Review | Edit

// An agent loop of this session, as the engine names it.
export class AgentId {
  private constructor(private readonly id: string) {}

  static of(id: string): AgentId {
    return new AgentId(id)
  }

  toString(): string {
    return this.id
  }
}

// The Agent tool call that spawned an agent.
export class AgentCall {
  private constructor(private readonly toolUseId: string) {}

  static of(toolUseId: string): AgentCall {
    return new AgentCall(toolUseId)
  }

  toString(): string {
    return this.toolUseId
  }
}

// The tasks of this session's jevrev agents, by agent, by the call that
// spawned each review, and by every id and name a review agent is addressed by.
// A running review is held by the exact prompt it was spawned with, until its
// completion notification; one not yet briefed is held by it too.
export class Tasks {
  private readonly byAgent = new Map<string, Task>()
  private readonly reviewsByCall = new Map<string, Review>()
  private readonly reviewAddresses = new Set<string>()
  private readonly runningReviews = new Map<string, Review>()
  private readonly unbriefedReviews = new Map<string, Review>()

  // False when a review spawned with the same prompt is still running.
  claim(prompt: string, review: Review): boolean {
    if (this.runningReviews.has(prompt)) {
      return false
    }
    this.runningReviews.set(prompt, review)
    this.unbriefedReviews.set(prompt, review)
    return true
  }

  // Frees the review's prompt for another review.
  release(review: Review): void {
    for (const held of [this.runningReviews, this.unbriefedReviews]) {
      for (const [prompt, task] of held) {
        if (task === review) {
          held.delete(prompt)
        }
      }
    }
  }

  // The review whose agent's opening prompt is this text, once: it is briefed after.
  takeUnbriefed(text: string): Review | undefined {
    const review = this.unbriefedReviews.get(text)
    this.unbriefedReviews.delete(text)
    return review
  }

  record(agent: AgentId, call: AgentCall, name: string | undefined, task: Task): void {
    this.byAgent.set(`${agent}`, task)
    if (task.kind === 'review') {
      this.reviewsByCall.set(`${call}`, task)
      this.reviewAddresses.add(`${agent}`)
      if (name !== undefined) {
        this.reviewAddresses.add(name)
      }
    }
  }

  of(agent: AgentId): Task | undefined {
    return this.byAgent.get(`${agent}`)
  }

  // By an agent id or a name.
  isReviewAgent(address: string): boolean {
    return this.reviewAddresses.has(address)
  }

  reviewSpawnedBy(call: AgentCall): Review | undefined {
    return this.reviewsByCall.get(`${call}`)
  }

  // Forgets every task, giving back their workspaces.
  clear(): Workspace[] {
    const workspaces = [...this.byAgent.values()].map(task => task.workspace)
    this.byAgent.clear()
    this.reviewsByCall.clear()
    this.reviewAddresses.clear()
    this.runningReviews.clear()
    this.unbriefedReviews.clear()
    return workspaces
  }
}

export interface AgentRuntime {
  typeOf(agent: AgentId): Promise<string | undefined>
  sleep(ms: number): Promise<void>
}
