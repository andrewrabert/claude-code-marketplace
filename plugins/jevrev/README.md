# jevrev

Review code with jev through the [jevrev](https://github.com/andrewrabert/jevrev) CLI, which must be on `PATH`, with the rule sets in `JEVREV_RULES` (directories separated by `:`). jevrev scans and posts with its own GitHub token (`GITHUB_TOKEN`); the hook looks up the pull request head through `gh`. The edit sandbox needs `uv`.

## Agents

Each agent's prompt is its input, a JSON object. `hooks/register.ts` checks it at spawn, refusing any other prompt before the agent starts, records the agent's task, and gives the agent its task's brief as its prompt instead.

- `jevrev:review`: `{"kind": "github", "repo": {"host": "H", "org": "O", "name": "N"}, "pr": N}`, `{"kind": "local", "git_dir": "/abs", "diff": "DIFF"}` or `{"kind": "local-full", "git_dir": "/abs", "head": "REV"}`. It scans once what its input names, as the agent starts, (`scan-github --pr`, `scan-git --diff DIFF`, or `scan-git --rev head`), confirms or rejects every finding, and calls `finish`, which with `github` posts the confirmed findings on the pull request. The report, `jevrev show --format md` and the posted review's URL, is kept by the hook: the agent never sees it, and the caller reads it as the result of the agent's completion notification in place of anything the agent says (or the reason the review was cancelled). A review agent always runs in the background. Its opening prompt is the exact JSON it was called with until the scan replaces it with the findings; while it runs, a second review of the same JSON is refused.
- `jevrev:edit`: `{"scope": ["/abs", ...], "instructions": "..."}`. It edits files in a sandbox that mounts each scope directory read-write at its own path. Each `write` or `edit` result carries jev's review of the file's changes from `HEAD`, or of the whole file outside git, and the agent fixes or disputes each finding.

## Tools

Each tool serves only the agent whose task it belongs to; the main loop and other agents are refused.

- Review: `scan` (no arguments; once), `confirm_finding`, `reject_finding`, `finish` (fails while a finding has no verdict; posts for `github`), `cancel`, and `read_source`, a file of the source as scanned: `jevrev target read`.
- Edit: `bash`, `read`, `write`, `edit`. Each call runs `scripts/jevrev-bash.py` once in a bashkit sandbox with the scope mounted and the agent's own temp directory at `/tmp`.

Each agent's temp directory, holding its review files, is removed when the session ends.
