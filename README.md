# Claude Code Marketplace

Personal Claude Code plugins and skills.

## Plugins

| Plugin             | Description                                                                                                                                                                                                                                                                                                                                                                    |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `andrewrabert-dev` | Development agents                                                                                                                                                                                                                                                                                                                                                             |
| `handoff-verifier` | Self-verification hooks managed by MCP tools: a Stop reminder that forces one more reasoning turn before a turn ends, plus ExitPlanMode and AskUserQuestion gates that block the tool until you self-certify the constraints are met via a token confirm. Each check is set per global, project, or session scope, and the hook concatenates the active scopes broad-to-narrow |
| `noted`            | noted - https://github.com/andrewrabert/noted                                                                                                                                                                                                                                                                                                                                  |
| `session-findings` | Mine Claude Code session transcripts into self-contained per-session findings notes (bugs, development friction, reusable learnings) via a deterministic digest pass plus model classification; includes the digest/render scripts and a resumable sweep harness that writes findings.json and findings.md keyed by deterministic session id                                   |
| `terse`            | Mirror of the global Stop-hook verifier: answer only what was asked, lead with the direct answer, drop all filler                                                                                                                                                                                                                                                              |

### andrewrabert-dev

_No skills._

### handoff-verifier

_No skills._

### noted

| Skill             | Description                                                                                                                                                                                                              |
|-------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `domain-modeling` | Build and sharpen a project's domain model. Use when the user wants to pin down domain terminology or a ubiquitous language, record an architectural decision, or when another skill needs to maintain the domain model. |
| `grill-me`        | A relentless interview to sharpen a plan or design.                                                                                                                                                                      |
| `grill-with-docs` | A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.                                                                                                               |
| `grilling`        | Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.                                                                 |
| `log`             | Use when explicitly asked to journal or log the conversation (e.g. /log) — capture an immutable, timestamped entry via the noted MCP LogNote tool.                                                                       |

### session-findings

| Skill              | Description                                                                                                                                                                                                                                                                                                     |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze-sessions` | Use when analyzing Claude Code session history to learn what bugs were fixed, where development got stuck, or what lessons recur — mines transcripts into self-contained per-session findings notes (bugs, friction, learnings) and supports a resumable multi-session sweep whose learnings can feed verifiers |

### terse

| Skill    | Description                                                                                                                                                  |
|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `terse`  | Restate your previous response per the terse rules — answer only what was asked, lead with the answer, telegraphic fragments, symbols over words, no filler. |
| `unslop` | Cut AI tells from any writing. Must always apply.                                                                                                            |

## Usage

```
/plugin marketplace add andrewrabert/claude-code-marketplace
/plugin install <plugin>@andrewrabert-marketplace
```
