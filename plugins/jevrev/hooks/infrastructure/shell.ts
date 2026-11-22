import type { EngineInterface } from 'claude-code'

export type Run = { exitCode: number; stdout: string; stderr: string }

// The longest run the engine allows; it refuses a larger timeoutMs.
export const MAX_RUN = { timeoutMs: 600_000 } as const

// Runs a sh script with `argv` as its positional arguments, so no argument is
// read as shell syntax.
export function sh($: EngineInterface, script: string, argv: readonly string[]): Promise<Run> {
  return $.process.run(['sh', '-c', script, 'sh', ...argv], MAX_RUN)
}

export const output = (run: { stdout: string; stderr: string }): string =>
  [run.stdout.trimEnd(), run.stderr.trimEnd()].filter(text => text !== '').join('\n')
