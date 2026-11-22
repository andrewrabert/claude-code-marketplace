import {
  COMPLETE_REPLY,
  excerpt,
  FAILED_BRIEF,
  type FindingIndex,
  gitDirIsNotADirectory,
  type LineRange,
  notACommit,
  type Reason,
  Review,
  type ReviewRequest,
  type ReviewTarget,
  type SourcePath,
  type Verdict,
} from '../domain/agents/review.ts'
import type { AbsolutePath, Directory } from '../domain/files.ts'
import type { Revision } from '../domain/git.ts'
import type { Systems } from '../domain/systems.ts'

const localRepository = async (systems: Systems, gitDir: AbsolutePath, revisions: readonly Revision[]): Promise<Directory> => {
  const dir = await systems.fileSystem.physicalDirectory(gitDir)
  if (dir === undefined) {
    throw gitDirIsNotADirectory()
  }
  for (const rev of revisions) {
    if (!(await systems.git.isCommit(dir, rev))) {
      throw notACommit(rev, dir)
    }
  }
  return dir
}

const lookUp = async (systems: Systems, request: ReviewRequest): Promise<ReviewTarget> => {
  switch (request.kind) {
    case 'github':
      return { ...request, head: await systems.github.pullRequestHead(request.repo, request.pr) }
    case 'local':
      return { kind: 'local', dir: await localRepository(systems, request.gitDir, []), diff: request.diff }
    case 'local-full':
      return { kind: 'local-full', dir: await localRepository(systems, request.gitDir, [request.head]), head: request.head }
  }
}

export const openReview = async (systems: Systems, request: ReviewRequest): Promise<Review> => {
  const target = await lookUp(systems, request)
  return new Review(target, await systems.fileSystem.makeWorkspace())
}

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

// Scans the review's target, finishing the review at once when the scan
// found nothing, and gives the brief its agent starts with. A scan that
// fails cancels the review.
export const scanReview = async (systems: Systems, review: Review): Promise<string> => {
  let found: boolean
  let pending = ''
  try {
    found = await systems.jevrev.scan(review.file, review.target)
    if (found) {
      pending = await systems.jevrev.pending(review.file)
    }
  } catch (error) {
    review.cancel(messageOf(error))
    return FAILED_BRIEF
  }
  if (!found) {
    await finish(systems, review)
  }
  return review.brief(pending)
}

export const judgeFinding = async (
  systems: Systems,
  review: Review,
  verdict: Verdict,
  index: FindingIndex,
  reason: Reason,
): Promise<string> => {
  review.ensureOpen()
  return systems.jevrev.record(review.file, verdict, index, reason)
}

// A finish that fails cancels the review with its error, which its caller
// reads; the agent ends its turn either way.
export const finish = async (systems: Systems, review: Review): Promise<string> => {
  review.ensureOpen()
  try {
    const report = await systems.jevrev.report(review.file)
    const posted = review.postsToPullRequest ? await systems.jevrev.submitToPullRequest(review.file) : undefined
    review.finish(report, posted)
  } catch (error) {
    review.cancel(messageOf(error))
  } finally {
    await systems.fileSystem.removeReviewFile(review.file)
  }
  return COMPLETE_REPLY
}

export const readSource = async (systems: Systems, review: Review, path: SourcePath, range: LineRange): Promise<string> => {
  review.ensureOpen()
  return excerpt(path, range, await systems.jevrev.readLines(review.file, path, range))
}
