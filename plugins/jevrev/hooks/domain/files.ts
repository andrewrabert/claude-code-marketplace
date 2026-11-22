import type { ReviewFile } from './jevrev.ts'
import { Refusal } from './refusal.ts'

// An absolute path as an agent's input gives it, not yet looked up.
export class AbsolutePath {
  private constructor(private readonly path: string) {}

  static parse(value: unknown, refusal: string): AbsolutePath {
    if (typeof value !== 'string' || !value.startsWith('/')) {
      throw new Refusal(refusal)
    }
    return new AbsolutePath(value)
  }

  toString(): string {
    return this.path
  }
}

// A directory's physical path, as the file system resolved it.
export class Directory {
  private constructor(private readonly path: string) {}

  static resolved(path: string): Directory {
    return new Directory(path)
  }

  holds(path: string): boolean {
    return path === this.path || path.startsWith(this.path === '/' ? '/' : `${this.path}/`)
  }

  // `path`, which this directory holds, relative to it.
  relative(path: string): string {
    return path === this.path ? '.' : path.slice(this.path === '/' ? 1 : this.path.length + 1)
  }

  get length(): number {
    return this.path.length
  }

  toString(): string {
    return this.path
  }
}

// The temp directory of one agent's task.
export class Workspace {
  private constructor(private readonly path: string) {}

  static made(path: string): Workspace {
    return new Workspace(path)
  }

  toString(): string {
    return this.path
  }
}

export interface FileSystem {
  physicalDirectory(path: AbsolutePath): Promise<Directory | undefined>
  makeWorkspace(): Promise<Workspace>
  removeReviewFile(file: ReviewFile): Promise<void>
  removeWorkspaces(workspaces: readonly Workspace[]): Promise<void>
}
