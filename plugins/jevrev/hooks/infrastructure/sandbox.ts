import type { EngineInterface } from 'claude-code'

import type { Sandbox } from '../domain/agents/edit.ts'
import { Refusal } from '../domain/refusal.ts'
import { MAX_RUN } from './shell.ts'

// Each call runs scripts/jevrev-bash.py once, which exits 1 with the reason on stderr when the call fails.
export function sandbox($: EngineInterface): Sandbox {
  return {
    run: async (scope, workspace, tool, args) => {
      const call = await $.process.run(
        [
          `${$.plugin.root}/scripts/jevrev-bash.py`,
          ...scope.roots.flatMap(root => ['--root', `${root}`]),
          '--tmp',
          `${workspace}`,
          tool,
        ],
        { ...MAX_RUN, stdin: JSON.stringify(args) },
      )
      if (call.exitCode !== 0) {
        throw new Refusal(call.stderr.trim() || `jevrev-bash.py exited with ${call.exitCode}.`)
      }
      return call.stdout
    },
  }
}
