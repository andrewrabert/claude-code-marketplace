import { Edit, type EditRequest, OUTSIDE_SCOPE, type SandboxArguments, type SandboxTool, Scope, scopeRootIsNotADirectory, writeReviewFailure, writeReviewFindings } from '../domain/agents/edit.ts'
import type { Directory } from '../domain/files.ts'
import { Refusal } from '../domain/refusal.ts'
import type { Systems } from '../domain/systems.ts'

export const openEdit = async (systems: Systems, request: EditRequest): Promise<Edit> => {
  const roots: Directory[] = []
  for (const root of request.scope) {
    const dir = await systems.fileSystem.physicalDirectory(root)
    if (dir === undefined) {
      throw scopeRootIsNotADirectory(root)
    }
    roots.push(dir)
  }
  return new Edit(new Scope(roots), await systems.fileSystem.makeWorkspace(), request.instructions)
}

// jev's review of the changes a write or edit made to a file.
const reviewWrite = async (systems: Systems, edit: Edit, path: string): Promise<string | undefined> => {
  const placement = edit.scope.place(path)
  if (placement === undefined) {
    return writeReviewFailure(path, OUTSIDE_SCOPE)
  }
  const scope = edit.writeScan(path, placement, await systems.git.hasHead(placement.root))
  const file = edit.nextReviewFile()
  try {
    return (await systems.jevrev.scan(file, scope)) ? writeReviewFindings(path, await systems.jevrev.pending(file)) : undefined
  } catch (error) {
    if (error instanceof Refusal) {
      return writeReviewFailure(path, error.message)
    }
    throw error
  } finally {
    await systems.fileSystem.removeReviewFile(file)
  }
}

export const runSandboxTool = async (systems: Systems, edit: Edit, tool: SandboxTool, args: SandboxArguments): Promise<string> => {
  const reply = await systems.sandbox.run(edit.scope, edit.workspace, tool, args)
  const written = edit.writtenFile(tool, args.file_path)
  return edit.toolReply(reply, written === undefined ? undefined : await reviewWrite(systems, edit, written))
}
