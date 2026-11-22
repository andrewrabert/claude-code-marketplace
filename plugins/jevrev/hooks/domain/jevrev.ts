import type { WriteScan } from './agents/edit.ts'
import type { FindingIndex, LineRange, Reason, ReviewTarget, SourcePath, Verdict } from './agents/review.ts'
import type { Workspace } from './files.ts'

// The path jevrev's --review takes: the file a scan writes its findings to,
// and every later command reads and records verdicts in.
export class ReviewFile {
  private constructor(private readonly path: string) {}

  static in(workspace: Workspace, name: string): ReviewFile {
    return new ReviewFile(`${workspace}/${name}`)
  }

  toString(): string {
    return this.path
  }
}

// What one jevrev scan reviews: a review's target, or a file an edit wrote.
export type ScanScope = ReviewTarget | WriteScan

export interface Jevrev {
  // Whether the scan found anything.
  scan(file: ReviewFile, scope: ScanScope): Promise<boolean>
  // The findings without a verdict, one JSON line each: index, file, start, end, flags, violation and accepted.
  pending(file: ReviewFile): Promise<string>
  // Lines `range` of `path` as the scan read it, each begun with its number and a tab.
  readLines(file: ReviewFile, path: SourcePath, range: LineRange): Promise<string>
  record(file: ReviewFile, verdict: Verdict, index: FindingIndex, reason: Reason): Promise<string>
  submitToPullRequest(file: ReviewFile): Promise<string>
  report(file: ReviewFile): Promise<string>
}
