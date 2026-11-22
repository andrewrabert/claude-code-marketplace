import type { CommitId, GithubRepo, PullRequestNumber } from '../github.ts'
import type { Diff, Revision } from '../git.ts'
import type { AbsolutePath, Directory, Workspace } from '../files.ts'
import { ReviewFile } from '../jevrev.ts'
import { Refusal } from '../refusal.ts'
import { REVIEW_AGENT } from '../session.ts'

export type Verdict = 'confirm' | 'reject'

// A finding's place in its review, as the scan numbered it.
export class FindingIndex {
  private constructor(private readonly index: number) {}

  static parse(value: unknown): FindingIndex {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
      throw new Refusal('index must be a positive integer.')
    }
    return new FindingIndex(value)
  }

  toString(): string {
    return String(this.index)
  }
}

// Why an agent judged a finding as it did, or why it cancelled its review.
export class Reason {
  private constructor(private readonly text: string) {}

  static parse(value: unknown): Reason {
    if (typeof value !== 'string' || value === '') {
      throw new Refusal('reason must be a non-empty string.')
    }
    return new Reason(value)
  }

  toString(): string {
    return this.text
  }
}

export const READ_LINE_LIMIT = 2000

const lineNumber = (value: unknown, key: string): number => {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    throw new Refusal(`${key} must be a positive integer.`)
  }
  return value
}

// A file of a review's source, by a path kept inside the source.
export class SourcePath {
  private constructor(private readonly path: string) {}

  static parse(value: unknown): SourcePath {
    if (value !== undefined && (typeof value !== 'string' || value === '')) {
      throw new Refusal('file must be a non-empty string.')
    }
    const given = typeof value === 'string' ? value : ''
    const parts = given.split('/').filter(part => part !== '' && part !== '.')
    if (given === '' || given.startsWith('/') || parts.includes('..')) {
      throw new Refusal('file must be a path relative to the source, without "..".')
    }
    return new SourcePath(parts.join('/'))
  }

  get segments(): readonly string[] {
    return this.path.split('/')
  }

  toString(): string {
    return this.path
  }
}

// The lines of a file one read returns, at most READ_LINE_LIMIT of them.
export class LineRange {
  private constructor(
    readonly start: number,
    readonly end: number,
  ) {}

  static parse(start: unknown, end: unknown): LineRange {
    const first = start === undefined ? 1 : lineNumber(start, 'start')
    const last = Math.min(end === undefined ? Number.MAX_SAFE_INTEGER : lineNumber(end, 'end'), first + READ_LINE_LIMIT - 1)
    if (last < first) {
      throw new Refusal('end must not be before start.')
    }
    return new LineRange(first, last)
  }

  toString(): string {
    return `${this.start}..${this.end}`
  }
}

// The numbered lines of a read.
export const excerpt = (path: SourcePath, range: LineRange, lines: string): string =>
  lines || `${path} has no lines in ${range}.`

// What a jevrev:review input asks for, before its git dir and pull request are looked up.
export type ReviewRequest =
  | { readonly kind: 'github'; readonly repo: GithubRepo; readonly pr: PullRequestNumber }
  | { readonly kind: 'local'; readonly gitDir: AbsolutePath; readonly diff: Diff }
  | { readonly kind: 'local-full'; readonly gitDir: AbsolutePath; readonly head: Revision }

// What a review audits, once its git dir and pull request are looked up.
export type ReviewTarget =
  | { readonly kind: 'github'; readonly repo: GithubRepo; readonly pr: PullRequestNumber; readonly head: CommitId }
  | { readonly kind: 'local'; readonly dir: Directory; readonly diff: Diff }
  | { readonly kind: 'local-full'; readonly dir: Directory; readonly head: Revision }

export const gitDirIsNotADirectory = (): Refusal => new Refusal('git_dir is not a directory')

export const notACommit = (rev: Revision, dir: Directory): Refusal => new Refusal(`${rev} is not a commit of ${dir}`)

const END_TURN = 'End your turn and reply with only "Done".'

export const COMPLETE_REPLY = END_TURN

const NO_FINDINGS_BRIEF = `There are no findings. ${END_TURN}`

export const FAILED_BRIEF = `The review failed. ${END_TURN}`

export const DUPLICATE_REVIEW_REFUSAL = 'a review of this input is already running'

const UNFINISHED_OUTCOME = `${REVIEW_AGENT} ended without finishing its review; nothing was posted.`

type Phase =
  | { readonly name: 'judging' }
  | { readonly name: 'finished'; readonly report: string; readonly postedUrl: string | undefined }
  | { readonly name: 'cancelled'; readonly reason: string }

// A jevrev:review agent's task, scanned as the agent starts. Its caller reads
// its outcome as the completion notification's result, in place of anything
// the agent says.
export class Review {
  readonly kind = 'review'
  readonly file: ReviewFile
  private phase: Phase = { name: 'judging' }

  constructor(
    readonly target: ReviewTarget,
    readonly workspace: Workspace,
  ) {
    this.file = ReviewFile.in(workspace, 'review.redb')
  }

  get postsToPullRequest(): boolean {
    return this.target.kind === 'github'
  }

  // The findings without a verdict, as jevrev prints them; empty when the scan found nothing.
  brief(pending: string): string {
    return pending === '' ? NO_FINDINGS_BRIEF : pending
  }

  ensureOpen(): void {
    if (this.phase.name !== 'judging') {
      throw new Refusal(`The review is complete. ${END_TURN}`)
    }
  }

  finish(report: string, postedUrl: string | undefined): void {
    this.ensureOpen()
    this.phase = { name: 'finished', report, postedUrl }
  }

  // A finish that fails ends the review too.
  cancel(reason: string): void {
    this.ensureOpen()
    this.phase = { name: 'cancelled', reason }
  }

  callerResult(): { readonly text: string; readonly isError: boolean } {
    const phase = this.phase
    switch (phase.name) {
      case 'finished':
        return {
          text: phase.postedUrl === undefined ? phase.report : `${phase.report}\n\nPosted: ${phase.postedUrl}`,
          isError: false,
        }
      case 'cancelled':
        return { text: `${REVIEW_AGENT} could not finish its review; nothing was posted: ${phase.reason}`, isError: true }
      case 'judging':
        return { text: UNFINISHED_OUTCOME, isError: true }
    }
  }
}
