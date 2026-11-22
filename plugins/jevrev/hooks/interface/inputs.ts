import { type EditRequest, Instructions } from '../domain/agents/edit.ts'
import type { ReviewRequest } from '../domain/agents/review.ts'
import { AbsolutePath } from '../domain/files.ts'
import { Diff, Revision } from '../domain/git.ts'
import { GithubRepo, PullRequestNumber } from '../domain/github.ts'
import { Refusal } from '../domain/refusal.ts'
import { type AgentType, EDIT_AGENT, REVIEW_AGENT } from '../domain/session.ts'

export const PROMPT_FORMATS: Readonly<Record<AgentType, string>> = {
  [REVIEW_AGENT]:
    'a JSON object, one of {"kind": "github", "repo": {"host": "<host>", "org": "<org>", "name": "<name>"}, "pr": N}, ' +
    '{"kind": "local", "git_dir": "<absolute path>", "diff": "<git diff: REV, A..B or A...B>"} or ' +
    '{"kind": "local-full", "git_dir": "<absolute path>", "head": "<revision>"}',
  [EDIT_AGENT]: 'a JSON object {"scope": ["<absolute path of a directory>", ...], "instructions": "<the edit instructions>"}',
}

type Fields = Record<string, unknown>

const isFields = (value: unknown): value is Fields => typeof value === 'object' && value !== null && !Array.isArray(value)

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

const rejectExtra = (extra: Fields): void => {
  if (Object.keys(extra).length > 0) {
    throw new Refusal(`unknown keys ${Object.keys(extra).join(', ')}`)
  }
}

const gitDir = (value: unknown): AbsolutePath => AbsolutePath.parse(value, 'git_dir is not an absolute path')

const parseReviewRequest = (input: Fields): ReviewRequest => {
  const { kind, ...rest } = input
  if (kind === 'github') {
    const { repo, pr, ...extra } = rest
    rejectExtra(extra)
    if (!isFields(repo)) {
      throw new Refusal('repo is not an object with host, org and name')
    }
    const { host, org, name, ...repoExtra } = repo
    rejectExtra(repoExtra)
    return { kind, repo: GithubRepo.parse(host, org, name), pr: PullRequestNumber.parse(pr) }
  }
  if (kind === 'local') {
    const { git_dir, diff, ...extra } = rest
    rejectExtra(extra)
    return { kind, gitDir: gitDir(git_dir), diff: Diff.parse(diff) }
  }
  if (kind === 'local-full') {
    const { git_dir, head, ...extra } = rest
    rejectExtra(extra)
    return { kind, gitDir: gitDir(git_dir), head: Revision.parse(head) }
  }
  throw new Refusal('kind is not "github", "local" or "local-full"')
}

const parseEditRequest = (input: Fields): EditRequest => {
  const { scope, instructions, ...extra } = input
  rejectExtra(extra)
  const refusal = 'scope is not a non-empty array of absolute paths'
  if (!Array.isArray(scope) || scope.length === 0) {
    throw new Refusal(refusal)
  }
  return { scope: scope.map(root => AbsolutePath.parse(root, refusal)), instructions: Instructions.parse(instructions) }
}

export type AgentRequest =
  | { readonly kind: 'review'; readonly request: ReviewRequest }
  | { readonly kind: 'edit'; readonly request: EditRequest }

// A jevrev agent's prompt is its input, a JSON object.
export const parseAgentPrompt = (type: AgentType, prompt: string): AgentRequest => {
  const input = parseJson(prompt.trim())
  if (!isFields(input)) {
    throw new Refusal('the prompt is not a JSON object')
  }
  return type === REVIEW_AGENT
    ? { kind: 'review', request: parseReviewRequest(input) }
    : { kind: 'edit', request: parseEditRequest(input) }
}
