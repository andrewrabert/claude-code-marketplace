import type { EngineInterface } from 'claude-code'

import { Directory, type FileSystem, Workspace } from '../domain/files.ts'
import { Refusal } from '../domain/refusal.ts'
import { output, sh, MAX_RUN } from './shell.ts'

export function fileSystem($: EngineInterface): FileSystem {
  return {
    physicalDirectory: async path => {
      const run = await sh($, '[ -d "$1" ] && cd -- "$1" && pwd -P', [`${path}`])
      const dir = run.stdout.trim()
      return run.exitCode === 0 && dir !== '' ? Directory.resolved(dir) : undefined
    },
    makeWorkspace: async () => {
      const made = await sh($, 'mktemp -d "${TMPDIR:-/tmp}/claude-code-jevrev.XXXXXX"', [])
      if (made.exitCode !== 0) {
        throw new Refusal(`mktemp failed: ${output(made)}`)
      }
      return Workspace.made(made.stdout.trim())
    },
    removeReviewFile: async file => {
      await $.process.run(['rm', '-f', '--', `${file}`], MAX_RUN)
    },
    removeWorkspaces: async workspaces => {
      if (workspaces.length > 0) {
        await $.process.run(['rm', '-rf', '--', ...workspaces.map(workspace => `${workspace}`)], MAX_RUN)
      }
    },
  }
}
