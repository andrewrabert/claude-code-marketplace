import type { EngineInterface } from 'claude-code'

import type { GitRepositories } from '../domain/git.ts'
import { sh } from './shell.ts'

export function gitRepositories($: EngineInterface): GitRepositories {
  return {
    isCommit: async (dir, rev) =>
      (await sh($, 'cd -- "$1" && git rev-parse --verify --quiet "$2^{commit}"', [`${dir}`, `${rev}`])).exitCode === 0,
    hasHead: async dir => (await sh($, 'cd -- "$1" && git rev-parse --verify --quiet HEAD', [`${dir}`])).exitCode === 0,
  }
}
