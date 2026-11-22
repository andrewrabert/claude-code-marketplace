import type { EngineInterface } from 'claude-code'

import type { Systems } from '../domain/systems.ts'
import { agentRuntime } from './agent-runtime.ts'
import { fileSystem } from './file-system.ts'
import { gitRepositories } from './git.ts'
import { github } from './github.ts'
import { jevrev } from './jevrev.ts'
import { sandbox } from './sandbox.ts'

export function createSystems($: EngineInterface): Systems {
  return {
    fileSystem: fileSystem($),
    git: gitRepositories($),
    github: github($),
    jevrev: jevrev($),
    sandbox: sandbox($),
    runtime: agentRuntime($),
  }
}
