import { Refusal } from './refusal.ts'

const GITHUB_NAME = /^[\w.-]+$/

export class GithubRepo {
  private constructor(
    readonly host: string,
    readonly org: string,
    readonly name: string,
  ) {}

  static parse(host: unknown, org: unknown, name: unknown): GithubRepo {
    for (const [key, value] of Object.entries({ host, org, name })) {
      if (typeof value !== 'string' || !GITHUB_NAME.test(value)) {
        throw new Refusal(`repo.${key} is not a GitHub name`)
      }
    }
    return new GithubRepo(host as string, org as string, name as string)
  }

  get slug(): string {
    return `${this.org}/${this.name}`
  }

  toString(): string {
    return `${this.host}/${this.slug}`
  }
}

export class PullRequestNumber {
  private constructor(private readonly number: number) {}

  static parse(value: unknown): PullRequestNumber {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
      throw new Refusal('pr is not a pull request number')
    }
    return new PullRequestNumber(value)
  }

  toString(): string {
    return String(this.number)
  }
}

// The commit a pull request's head pointed to when its review started.
export class CommitId {
  private constructor(private readonly sha: string) {}

  static of(sha: string): CommitId {
    return new CommitId(sha)
  }

  toString(): string {
    return this.sha
  }
}

export interface Github {
  pullRequestHead(repo: GithubRepo, pr: PullRequestNumber): Promise<CommitId>
}
