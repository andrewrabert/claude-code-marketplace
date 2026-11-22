import { runSandboxTool } from '../application/edit-workflow.ts'
import { finish, judgeFinding, readSource } from '../application/review-workflow.ts'
import { type Edit, isSandboxTool } from '../domain/agents/edit.ts'
import { FindingIndex, LineRange, Reason, type Review, SourcePath } from '../domain/agents/review.ts'
import { Refusal } from '../domain/refusal.ts'
import { EDIT_AGENT, REVIEW_AGENT } from '../domain/session.ts'
import type { Systems } from '../domain/systems.ts'

// A tool call's arguments, as the model gave them.
export type ToolArguments = Readonly<Record<string, unknown>>

export const runReviewTool = async (systems: Systems, review: Review, name: string, args: ToolArguments): Promise<string> => {
  switch (name) {
    case 'confirm_finding':
    case 'reject_finding': {
      const index = args.index === undefined ? undefined : FindingIndex.parse(args.index)
      const reason = args.reason === undefined ? undefined : Reason.parse(args.reason)
      if (index === undefined || reason === undefined) {
        throw new Refusal('index and reason are required.')
      }
      return judgeFinding(systems, review, name === 'confirm_finding' ? 'confirm' : 'reject', index, reason)
    }
    case 'finish':
      return finish(systems, review)
    case 'read_source': {
      const path = SourcePath.parse(args.file)
      return readSource(systems, review, path, LineRange.parse(args.start, args.end))
    }
    default:
      throw new Refusal(`${name} is not a tool of ${REVIEW_AGENT}.`)
  }
}

export const runEditTool = async (systems: Systems, edit: Edit, name: string, args: ToolArguments): Promise<string> => {
  if (!isSandboxTool(name)) {
    throw new Refusal(`${name} is not a tool of ${EDIT_AGENT}.`)
  }
  return runSandboxTool(systems, edit, name, args)
}
