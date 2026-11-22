import type { Register } from 'claude-code'

import { openEdit } from './application/edit-workflow.ts'
import { openReview, scanReview } from './application/review-workflow.ts'
import { DUPLICATE_REVIEW_REFUSAL, type Review } from './domain/agents/review.ts'
import { taskOf } from './application/task-lookup.ts'
import { Refusal } from './domain/refusal.ts'
import { AgentCall, AgentId, isAgentType, isResumable, RESUME_REFUSAL, type Task, Tasks } from './domain/session.ts'
import { createSystems } from './infrastructure/systems.ts'
import { runEditTool, runReviewTool } from './interface/commands.ts'
import { parseAgentPrompt, PROMPT_FORMATS } from './interface/inputs.ts'
import {
  EDIT_TOOL_NAMES,
  EDIT_TOOLS,
  ENVELOPE_KEYS,
  ownerOf,
  REVIEW_TOOL_NAMES,
  REVIEW_TOOLS,
  TOOL_PATTERN,
  TOOL_PREFIX,
} from './interface/tools.ts'

const tasks = new Tasks()

const TOOL_USE_ID = /<tool-use-id>([^<]*)<\/tool-use-id>/
const RESULT = /<result>[\s\S]*<\/result>/
const NOTIFICATION_END = '</task-notification>'

const escapeXml = (text: string): string => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')

const unescapeXml = (text: string): string => text.replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&')

type Block = { readonly type: string; readonly [field: string]: unknown }

// A block's text, when it is a text block.
const textOf = (block: Block): string | undefined =>
  block.type === 'text' && typeof block.text === 'string' ? block.text : undefined

// A notification's text with its result, or a result where it carried none.
const withResult = (notification: string, result: string): string => {
  const element = `<result>${escapeXml(result)}</result>`
  if (RESULT.test(notification)) {
    return notification.replace(RESULT, () => element)
  }
  return notification.includes(NOTIFICATION_END)
    ? notification.replace(NOTIFICATION_END, () => `${element}\n${NOTIFICATION_END}`)
    : `${notification}\n${element}`
}

// A notification block, with a review's outcome as its result.
const withOutcome = (block: Block): Block => {
  const text = textOf(block)
  const call = text === undefined ? undefined : TOOL_USE_ID.exec(text)?.[1]
  const review = call === undefined ? undefined : tasks.reviewSpawnedBy(AgentCall.of(unescapeXml(call)))
  if (text === undefined || review === undefined) {
    return block
  }
  tasks.release(review)
  return { ...block, text: withResult(text, review.callerResult().text) }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    for (const tool of [...REVIEW_TOOLS, ...EDIT_TOOLS]) {
      await $.tool.register(tool)
    }
    return started
  })

  // A jevrev agent's prompt is its input: checked here, before the agent
  // starts, and replaced by its task's brief.
  on('agent.spawn', async ($, e, next) => {
    const type = e.subagentType
    if (e.resume !== undefined) {
      if (tasks.isReviewAgent(e.resume.agentId) || !isResumable(type)) {
        return { deny: RESUME_REFUSAL }
      }
      return next(e)
    }
    if (!isAgentType(type)) {
      return next(e)
    }
    const systems = createSystems($)
    let task: Task
    try {
      const asked = parseAgentPrompt(type, e.prompt)
      task = asked.kind === 'review' ? await openReview(systems, asked.request) : await openEdit(systems, asked.request)
    } catch (error) {
      if (error instanceof Refusal) {
        return { deny: `${type} takes a prompt of ${PROMPT_FORMATS[type]}: ${error.message}.` }
      }
      throw error
    }
    if (task.kind === 'edit') {
      const spawned = await next({ ...e, prompt: task.brief() })
      if (spawned.agentId === undefined) {
        await systems.fileSystem.removeWorkspaces([task.workspace])
        return spawned
      }
      tasks.record(AgentId.of(spawned.agentId), AgentCall.of(e.tool_use_id), e.name, task)
      return spawned
    }
    // A review runs in the background under the exact prompt it was called
    // with, which its opening row carries until session.append briefs it.
    if (!tasks.claim(e.prompt, task)) {
      await systems.fileSystem.removeWorkspaces([task.workspace])
      return { deny: `${type}: ${DUPLICATE_REVIEW_REFUSAL}.` }
    }
    let spawned: Awaited<ReturnType<typeof next>>
    try {
      spawned = await next({ ...e, background: true })
    } catch (error) {
      tasks.release(task)
      await systems.fileSystem.removeWorkspaces([task.workspace])
      throw error
    }
    if (spawned.agentId === undefined) {
      tasks.release(task)
      await systems.fileSystem.removeWorkspaces([task.workspace])
      return spawned
    }
    tasks.record(AgentId.of(spawned.agentId), AgentCall.of(e.tool_use_id), e.name, task)
    return spawned
  }).catch((_, e, next) =>
    next.called || (!isAgentType(e.subagentType) && !(e.resume !== undefined && tasks.isReviewAgent(e.resume.agentId)))
      ? next(e)
      : { deny: `${e.subagentType} spawn check failed: ${next.error.message ?? next.error.kind}.` },
  )

  // Nor is a message delivered to one, by id or name.
  on('session.send', async ($, e, next) => {
    if (tasks.isReviewAgent(e.to)) {
      return { isDelivered: false, reason: RESUME_REFUSAL }
    }
    return next(e)
  })

  on('tool.call', { tool: TOOL_PATTERN }, async ($, e) => {
    const name = e.tool.slice(TOOL_PREFIX.length)
    const args = Object.fromEntries(Object.entries(e).filter(([key]) => !ENVELOPE_KEYS.has(key)))
    const systems = createSystems($)
    const task = await taskOf(systems.runtime, tasks, e.agentId === undefined ? undefined : AgentId.of(e.agentId))
    try {
      if (task?.kind === 'review' && REVIEW_TOOL_NAMES.has(name)) {
        return { result: await runReviewTool(systems, task, name, args) }
      }
      if (task?.kind === 'edit' && EDIT_TOOL_NAMES.has(name)) {
        return { result: await runEditTool(systems, task, name, args) }
      }
      return { deny: `only a ${ownerOf(name)} agent can use ${name}.` }
    } catch (error) {
      if (error instanceof Refusal) {
        return { deny: error.message }
      }
      throw error
    }
  })

  // A review agent's opening row is the prompt it was called with: the scan
  // runs here and the row becomes the review's brief. The caller reads a
  // review's outcome, never the review agent's own words: the result its
  // completion notification carries is replaced, and its prompt is free for
  // another review.
  on('session.append', async ($, e, next) => {
    if (e.origin.kind === 'task-notification') {
      return next({ ...e, message: { ...e.message, content: e.message.content.map(withOutcome) } })
    }
    if (e.agentId === undefined || e.message.type !== 'user') {
      return next(e)
    }
    let review: Review | undefined
    for (const block of e.message.content) {
      const text = textOf(block)
      if (text !== undefined) {
        review ??= tasks.takeUnbriefed(text)
      }
    }
    if (review === undefined) {
      return next(e)
    }
    const brief = await scanReview(createSystems($), review)
    return next({ ...e, message: { ...e.message, content: [{ type: 'text', text: brief }] } })
  })

  // A resumed agent keeps its task, so workspaces last until the session ends.
  on('session.end', async ($, e, next) => {
    await createSystems($).fileSystem.removeWorkspaces(tasks.clear())
    return next(e)
  })
}
