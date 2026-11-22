import type { AbsolutePath, Directory, Workspace } from '../files.ts'
import { ReviewFile } from '../jevrev.ts'
import { Refusal } from '../refusal.ts'

export class Instructions {
  private constructor(private readonly text: string) {}

  static parse(value: unknown): Instructions {
    if (typeof value !== 'string' || value.trim() === '') {
      throw new Refusal('instructions are missing')
    }
    return new Instructions(value.trim())
  }

  toString(): string {
    return this.text
  }
}

// What a jevrev:edit input asks for, before its scope directories are looked up.
export type EditRequest = { readonly scope: readonly AbsolutePath[]; readonly instructions: Instructions }

export const scopeRootIsNotADirectory = (root: AbsolutePath): Refusal => new Refusal(`${root} is not a directory`)

// A file under a scope directory: the deepest one holding it, and its path from there.
export type Placement = { readonly root: Directory; readonly path: string }

// The directories an edit agent's sandbox mounts read-write.
export class Scope {
  constructor(readonly roots: readonly Directory[]) {}

  place(path: string): Placement | undefined {
    const root = this.roots.filter(dir => dir.holds(path)).sort((a, b) => b.length - a.length)[0]
    return root === undefined ? undefined : { root, path: root.relative(path) }
  }
}

export type SandboxTool = 'bash' | 'read' | 'write' | 'edit'

const SANDBOX_TOOLS: ReadonlySet<string> = new Set<SandboxTool>(['bash', 'read', 'write', 'edit'])

export const isSandboxTool = (name: string): name is SandboxTool => SANDBOX_TOOLS.has(name)

const isWriteTool = (tool: SandboxTool): boolean => tool === 'write' || tool === 'edit'

// What jev reviews after a write: the file's changes from HEAD in a git
// repository, else the whole file.
export type WriteScan =
  | { readonly kind: 'file-changes'; readonly root: Directory; readonly path: string }
  | { readonly kind: 'file'; readonly path: string }

export const OUTSIDE_SCOPE = 'the file is outside your scope.'

export const writeReviewFindings = (path: string, pending: string): string => `jev review of ${path}:\n${pending}`

export const writeReviewFailure = (path: string, reason: string): string => `jev review of ${path} failed: ${reason}`

// A jevrev:edit agent's task.
export class Edit {
  readonly kind = 'edit'
  private reviews = 0

  constructor(
    readonly scope: Scope,
    readonly workspace: Workspace,
    readonly instructions: Instructions,
  ) {}

  brief(): string {
    return [...this.scope.roots.map(root => `${root} (read-write)`), 'instructions:', `${this.instructions}`].join('\n')
  }

  // The file a call wrote, when jev reviews it.
  writtenFile(tool: SandboxTool, filePath: unknown): string | undefined {
    return isWriteTool(tool) && typeof filePath === 'string' ? filePath.replace(/\/+$/, '') : undefined
  }

  writeScan(path: string, placement: Placement, inGit: boolean): WriteScan {
    return inGit ? { kind: 'file-changes', root: placement.root, path: placement.path } : { kind: 'file', path }
  }

  nextReviewFile(): ReviewFile {
    this.reviews += 1
    return ReviewFile.in(this.workspace, `edit-${this.reviews}.redb`)
  }

  toolReply(output: string, writeReview: string | undefined): string {
    return writeReview === undefined ? output : `${output}\n\n${writeReview}`
  }
}

// A sandbox tool call's arguments, which the sandbox checks itself.
export type SandboxArguments = Readonly<Record<string, unknown>>

export interface Sandbox {
  run(scope: Scope, workspace: Workspace, tool: SandboxTool, args: SandboxArguments): Promise<string>
}
