import type { McpToolName, Register, ToolCallInput } from 'claude-code'

const CODE_REVIEW_TOOL = /^mcp__plugin_bashkit-agents_code-review__/

type CodeReviewCall = Extract<ToolCallInput, { tool: McpToolName }>

const isCodeReviewCall = (e: ToolCallInput): e is CodeReviewCall =>
  CODE_REVIEW_TOOL.test(e.tool)

export const register: Register = on => {
  // Every code-review call is keyed to the calling session, or to the
  // subagent inside it, so concurrent reviews keep separate sandboxes.
  on('tool.call', { tool: CODE_REVIEW_TOOL }, async ($, e, next) => {
    if (!isCodeReviewCall(e)) {
      return next(e)
    }
    if (e.session_id != null) {
      return { deny: 'session_id cannot be set.' }
    }
    const sessionId = await $.session.id()
    return next({
      ...e,
      session_id: e.agentId ? `${sessionId}/${e.agentId}` : sessionId,
    })
  }).catch(($, e, next) =>
    next.called ? next(e) : { deny: `${$.plugin.name}: its session_id hook failed.` },
  )

  on('tool.check', { tool: CODE_REVIEW_TOOL }, () => ({ decision: 'allow' }))
}
