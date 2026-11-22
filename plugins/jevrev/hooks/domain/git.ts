import type { Directory } from './files.ts'
import { Refusal } from './refusal.ts'

// A revision passed to git, never read as an option.
export class Revision {
  private constructor(private readonly name: string) {}

  static parse(value: unknown): Revision {
    if (typeof value !== 'string' || value === '' || value.startsWith('-') || value.includes('..')) {
      throw new Refusal(`${JSON.stringify(value)} is not a git revision`)
    }
    return new Revision(value)
  }

  toString(): string {
    return this.name
  }
}

// A diff in git diff's syntax, passed to jevrev scan-git --diff: REV, the
// changes from REV to the files on disk; A..B; or A...B. Never read as an option.
export class Diff {
  private constructor(private readonly spec: string) {}

  static parse(value: unknown): Diff {
    if (typeof value !== 'string' || value === '' || value.startsWith('-')) {
      throw new Refusal(`${JSON.stringify(value)} is not a git diff`)
    }
    return new Diff(value)
  }

  toString(): string {
    return this.spec
  }
}

export interface GitRepositories {
  isCommit(dir: Directory, rev: Revision): Promise<boolean>
  hasHead(dir: Directory): Promise<boolean>
}
