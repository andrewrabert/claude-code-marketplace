import type { EngineInterface } from 'claude-code'

import { CommitId, type Github } from '../domain/github.ts'
import { Refusal } from '../domain/refusal.ts'
import { output, sh } from './shell.ts'

export function github($: EngineInterface): Github {
  return {
    pullRequestHead: async (repo, pr) => {
      const head = await sh($, 'gh pr view "$2" --repo "$1" --json headRefOid --jq .headRefOid', [`${repo}`, `${pr}`])
      const sha = head.stdout.trim()
      if (head.exitCode !== 0 || sha === '') {
        throw new Refusal(`gh pr view failed: ${output(head)}`)
      }
      return CommitId.of(sha)
    },
  }
}
