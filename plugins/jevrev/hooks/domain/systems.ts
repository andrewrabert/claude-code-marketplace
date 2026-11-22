import type { Sandbox } from './agents/edit.ts'
import type { FileSystem } from './files.ts'
import type { GitRepositories } from './git.ts'
import type { Github } from './github.ts'
import type { Jevrev } from './jevrev.ts'
import type { AgentRuntime } from './session.ts'

// The outside systems the agents' tasks use.
export type Systems = {
  readonly fileSystem: FileSystem
  readonly git: GitRepositories
  readonly github: Github
  readonly jevrev: Jevrev
  readonly sandbox: Sandbox
  readonly runtime: AgentRuntime
}
