A plan declares only the destination.

````
# <noun phrase naming what exists at the end>

## Result

### <logical group>

#### <path or glob>

<optional sentence naming the change>

```<lang>
<finished declarations for changed public API>
```

```<lang>
<finished non-API lines>
```

## Order

- <required sequence and the consequence of violating it>

## True when done

- <newly true assertion>
````

Omit `Order` unless sequence affects correctness.

### Result

Headings mirror the change's structure; each leaf is a path or glob. Under a
leaf, use at most one sentence followed by fenced blocks.

Declare the changed API — every changed type, field, parameter, return, and
error, and nothing unchanged — in the target language's declaration syntax:

- Format declarations with the language formatter and separate items with a
  blank line.
- Put behavior absent from the signature in comments above the item, one clause
  per line.
- Prefix a removed declaration with `-`.
- Collapse derived or mechanical trait implementations to one line.
- Show a whole enum when all variants are new; otherwise show changed variants.
- Show generic bounds only when changed.

For non-API edits, show only finished lines; the sentence names the affected
symbol, key, or call. Use the target's native notation for non-code surfaces.

### True when done

Each bullet states an outcome that is false before the change and true after it.
Omit commands, tools, and file-existence checks.

### Example

````
# InstanceId derives from the config dir path

## Result

### src/platform_abi/src/instance.rs

The id becomes a pure function of the config dir; the random constructor goes
away.

```rust
impl InstanceId {
    // the id is the v5 uuid of the config dir's canonical path
    pub fn derive(config_dir: &Path) -> InstanceId;
    - pub fn new() -> InstanceId;
}
```

### src/platform_abi/Cargo.toml

The `uuid` dependency line becomes:

```toml
uuid = { version = "1", features = ["v5"] }
```

### src/**/*.rs

Every `InstanceId::new()` call site becomes:

```rust
InstanceId::derive(&config_dir)
```

## True when done

- The same config dir yields the same instance id across restarts.
- Two config dirs never share an instance id.
- Nothing on disk stores the instance id.
````

### Forbidden

- Rationale, alternatives, history, or present behavior.
- Steps implied by `Result`.
- Deferred, optional, hedged, or undecided work.
- Unchanged API.
- Line numbers or approximate locators.
- Prose beyond the optional sentence under a leaf.
