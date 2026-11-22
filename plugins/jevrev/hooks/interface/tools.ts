import type { ToolSpec } from 'claude-code'

import { EDIT_AGENT, PLUGIN, REVIEW_AGENT } from '../domain/session.ts'

export const TOOL_PREFIX = `mcp__${PLUGIN}__`

export const TOOL_PATTERN = new RegExp(`^${TOOL_PREFIX}`)

// The keys of a tool.call input that are not the tool's arguments.
export const ENVELOPE_KEYS: ReadonlySet<string> = new Set(['tool', 'tool_use_id', 'agentId', 'requestMeta'])

const VERDICT_SCHEMA = {
  type: 'object',
  properties: { index: { type: 'integer', minimum: 1 }, reason: { type: 'string' } },
  required: ['index', 'reason'],
}

export const REVIEW_TOOLS: readonly ToolSpec[] = [
  { name: 'read_source', description: 'Read a file.', inputSchema: {
    type: 'object',
    properties: { file: { type: 'string' }, start: { type: 'integer', minimum: 1 }, end: { type: 'integer', minimum: 1 } },
    required: ['file'],
  } },
  { name: 'confirm_finding', description: 'Confirm a finding.', inputSchema: VERDICT_SCHEMA },
  { name: 'reject_finding', description: 'Reject a finding.', inputSchema: VERDICT_SCHEMA },
  { name: 'finish', description: 'Finish the review.', inputSchema: { type: 'object', properties: {} } },
]

// The edit agent's sandbox tools: each call runs scripts/jevrev-bash.py once.
export const EDIT_TOOLS: readonly ToolSpec[] = [
  {
    name: 'bash',
    description:
      'Run a shell command. Standard output and standard error are returned together, followed by the exit ' +
      'code when it is nonzero. Each call starts a new shell: the working directory and variables do not carry ' +
      'over. /tmp is your own and keeps its files.',
    inputSchema: {
      type: 'object',
      properties: { command: { type: 'string' }, description: { type: 'string' } },
      required: ['command', 'description'],
    },
  },
  {
    name: 'read',
    description: 'Read a text file with numbered lines. The path must be absolute. Use offset and limit to select a range of lines.',
    inputSchema: {
      type: 'object',
      properties: {
        file_path: { type: 'string' },
        limit: { type: ['integer', 'null'], minimum: 0 },
        offset: { type: ['integer', 'null'], minimum: 0 },
      },
      required: ['file_path'],
    },
  },
  {
    name: 'write',
    description:
      'Write a text file. The path must be absolute, and missing parent directories are created. The result ' +
      "carries jev's review of the file's changes.",
    inputSchema: {
      type: 'object',
      properties: { content: { type: 'string' }, file_path: { type: 'string' } },
      required: ['file_path', 'content'],
    },
  },
  {
    name: 'edit',
    description:
      'Replace exact text in a file. By default the old text must occur exactly once; set replace_all to ' +
      "replace every occurrence. The result carries jev's review of the file's changes.",
    inputSchema: {
      type: 'object',
      properties: {
        file_path: { type: 'string' },
        new_string: { type: 'string' },
        old_string: { type: 'string' },
        replace_all: { default: false, type: 'boolean' },
      },
      required: ['file_path', 'old_string', 'new_string'],
    },
  },
]

export const REVIEW_TOOL_NAMES: ReadonlySet<string> = new Set(REVIEW_TOOLS.map(tool => tool.name))

export const EDIT_TOOL_NAMES: ReadonlySet<string> = new Set(EDIT_TOOLS.map(tool => tool.name))

// The agent type whose tasks a tool serves.
export const ownerOf = (name: string): string => (REVIEW_TOOL_NAMES.has(name) ? REVIEW_AGENT : EDIT_AGENT)
