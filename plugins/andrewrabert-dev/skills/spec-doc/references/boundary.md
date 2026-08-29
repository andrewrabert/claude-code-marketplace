# The implementation boundary

How to read the source and write nothing that came from it.

---

## The test

For every sentence: **would this stay true after a full rewrite in another
language?**

If no, the sentence is implementation.

Do not delete it. Ask what promise the mechanism keeps, and write that instead.
The mechanism was there for a reason, and the reason is usually the guarantee a
caller needs.

---

## The rewrite

Each row: the leak, then what it was protecting.

| Leak | Write instead |
|---|---|
| The program writes a temporary file and renames it. | A write either fully replaces the file or leaves it unchanged. A reader never observes a partial file. |
| Paths are held as a `RelPath` newtype. | A path MUST NOT contain a `..` component, and MUST NOT begin with a separator. |
| Credentials are macaroons with caveats. | A credential MUST only narrow what its holder already has. One that reaches further is refused, not trimmed. |
| The index is a B-tree keyed by path. | Results are returned in case-insensitive path order. |
| Retries use exponential backoff with jitter. | A failed request is retried. A caller MUST NOT assume a fixed interval between attempts. |
| Parsing uses a streaming reader, so memory stays flat. | An input of any size is accepted. This document sets no size limit. |
| The cache is invalidated on write. | A read after a write observes the write. |
| Tokens are hashed with Argon2id. | A stored credential MUST NOT be recoverable from the store. |
| The server is single-threaded per connection. | Requests on one connection are answered in the order they were sent. |
| Config is parsed with a dotenv library. | Each line binds one name to one value. A `#` begins a comment. |

The pattern: a mechanism sentence names a noun a caller cannot see. A guarantee
sentence names only what a caller can do and what they then observe.

---

## Where leaks hide

**Error text.** An error naming a library, a file path inside the program, or a
type is a leak. Specify what an error identifies, not how it is worded, unless
the wording is the contract.

**Performance claims.** "Fast", "constant time", "streams" — all describe the
current build. Promise a complexity bound only when you will hold every future
implementation to it.

**Limits that are really buffer sizes.** A cap at 40 KB is a leak unless it is a
promise. Decide which it is. If a promise, state it as a number in the surface
section. If not, do not mention it.

**Sample values.** A vendor name, a product name, a model id, or a real hostname
in an example says what the thing was built against. Use neutral values.

| Leaky example value | Neutral |
|---|---|
| `type: BigQuery Table` | `type: Table` |
| `generated_by: reference_agent/gemini-2.5-pro` | `generated_by: agent/1.0` |
| `https://console.cloud.google.com/...` | `https://example.com/...` |
| `--auth-db /var/lib/app/auth.redb` | `--auth-db <path>` |

**Field names that describe storage.** A field called `row_id` or `blob` names a
storage model. If the name is the contract, keep it and say so. If you are
designing, pick a name that describes the value.

**Ordering that is incidental.** If the current implementation returns results in
insertion order, that is not a promise until you write it down. Either promise
an order or state that the order is unspecified. Silence is the one option that
fails, because callers will depend on what they observe.

---

## The dependency direction

A spec constrains the implementation. The implementation does not constrain the
spec.

So:

- When the source does something you would not promise, do not promise it. Put
  the question under Deferred.
- When the source does something inconsistent, specify the behavior you want and
  report the discrepancy to the user. Do not specify the bug.
- When the source leaves something undefined, leave it undefined. Write "the
  order is unspecified" rather than describing what happens to occur.

Report every one of these to the user. A spec that quietly diverges from the
source is worse than no spec.

---

## Reading order

1. **The help output and the tests.** These are the surface as its author
   intended it. Start here.
2. **The argument and type definitions.** These give the exact names, the
   defaults, and which arguments are optional.
3. **The validation and refusal paths.** These give the rules. Most of a good
   spec's precision comes from reading what the code refuses.
4. **The happy path last, and lightly.** This is where mechanism lives, and
   where a spec writer picks up leaks.

Read the README only to find claims to check. Never to source facts. A README
states what was true when it was written.
