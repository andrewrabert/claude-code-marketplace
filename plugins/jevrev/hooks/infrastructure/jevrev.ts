import type { EngineInterface } from 'claude-code'

import type { Jevrev, ScanScope } from '../domain/jevrev.ts'
import { Refusal } from '../domain/refusal.ts'
import { output, MAX_RUN } from './shell.ts'

// A gitignore pattern matching exactly `path`, relative to the scanned directory.
const exactPattern = (path: string): string => `/${path.replace(/[\\*?[\]!#]/g, char => `\\${char}`)}`

const scanArgs = (scope: ScanScope): readonly string[] => {
  switch (scope.kind) {
    case 'github':
      return ['scan-github', scope.repo.slug, '--pr', `${scope.pr}`, '--github-host', scope.repo.host]
    case 'local':
      return ['scan-git', `${scope.dir}`, '--diff', `${scope.diff}`]
    case 'local-full':
      return ['scan-git', `${scope.dir}`, '--rev', `${scope.head}`]
    case 'file-changes':
      return ['scan-git', `${scope.root}`, '--diff', 'HEAD', '--include', exactPattern(scope.path)]
    case 'file':
      return ['scan', scope.path]
  }
}

export function jevrev($: EngineInterface): Jevrev {
  const run = async (file: string, argv: readonly string[]): Promise<string> => {
    const ran = await $.process.run(['jevrev', '--review', file, ...argv], MAX_RUN)
    if (ran.exitCode !== 0) {
      throw new Refusal(output(ran) || `jevrev ${argv[0]} exited with ${ran.exitCode}.`)
    }
    return output(ran)
  }
  return {
    // jevrev exits 0 with no findings, 1 with findings and 2 on an error.
    scan: async (file, scope) => {
      const argv = scanArgs(scope)
      const ran = await $.process.run(['jevrev', '--review', `${file}`, ...argv], MAX_RUN)
      if (ran.exitCode !== 0 && ran.exitCode !== 1) {
        throw new Refusal(`jevrev ${argv[0]} failed: ${output(ran)}`)
      }
      return ran.exitCode === 1
    },
    pending: async file => {
      const ran = await $.process.run(['jevrev', '--review', `${file}`, 'pending', '--format', 'json'], MAX_RUN)
      if (ran.exitCode !== 0) {
        throw new Refusal(output(ran) || `jevrev pending exited with ${ran.exitCode}.`)
      }
      const stdout = ran.stdout.trimEnd()
      const lines = stdout === '' ? [] : stdout.split('\n')
      const findings: string[] = []
      for (const line of lines) {
        const { rule, probability, state, index, file, start, end, flags, violation, accepted, ...unexpected } = JSON.parse(line)
        const keys = Object.keys(unexpected)
        if (keys.length > 0) {
          throw new Refusal(`jevrev pending printed unexpected keys ${keys.join(', ')}`)
        }
        findings.push(JSON.stringify({ index, file, start, end, flags, violation, accepted }))
      }
      return findings.join('\n')
    },
    // jevrev's --lines fails on lines past the file's end, so read it all and keep `range`;
    // every numbered line is non-empty, so an empty one is only the split's trailing piece.
    readLines: async (file, path, range) => {
      const ran = await $.process.run(['jevrev', '--review', `${file}`, 'target', 'read', '--line-number', '--', `${path}`], MAX_RUN)
      if (ran.exitCode !== 0) {
        throw new Refusal(`cannot read ${path}: ${output(ran)}`)
      }
      return ran.stdout
        .split('\n')
        .slice(range.start - 1, range.end)
        .filter(line => line !== '')
        .map(line => `${line}\n`)
        .join('')
    },
    record: (file, verdict, index, reason) => run(`${file}`, [verdict, `${index}`, `${reason}`]),
    submitToPullRequest: file => run(`${file}`, ['submit-github']),
    report: file => run(`${file}`, ['show', '--format', 'md']),
  }
}
