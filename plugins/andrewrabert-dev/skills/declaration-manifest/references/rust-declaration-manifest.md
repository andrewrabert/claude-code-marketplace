# Rust Declaration Manifest

A manifest for one change, stated as an equation: the set of Rust declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- A direction with no declarations gets no section; an absent section means the empty set.
- Constrained declaration kinds: `fn`, `struct`, `trait`, `impl`. Bodies, private helpers, and formatting sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any file content beyond declarations.
- Begins with a title, `# Declaration Manifest: Rust`, followed by the equation as one binding sentence.
- Each direction section holds one `### <specific file>` section per file that holds a constrained declaration; each file section holds one fenced `rust` block.
- A function is a `;`-terminated signature stub. Methods and associated functions sit inside their `impl` block.
- A struct or trait is its full definition, private fields included.
- A trait implementation is one line: `impl <Trait> for <Type>;`.

## Format

````markdown
# Declaration Manifest: Rust
The set of `fn`, `struct`, `trait`, and `impl` declarations the resulting
combined diff adds must equal the declarations under `## Additions`, and
the set it deletes must equal the declarations under `## Deletions`.

## Additions

### <specific_file>
```rust
<declarations>
```

## Deletions

### <specific_file>
```rust
<declarations>
```
````

## Example

````markdown
# Declaration Manifest: Rust
The set of `fn`, `struct`, `trait`, and `impl` declarations the resulting
combined diff adds must equal the declarations under `## Additions`, and
the set it deletes must equal the declarations under `## Deletions`.

## Additions

### src/platform_abi/src/instance.rs
```rust
pub struct InstanceId {
    pub uuid: Uuid,
}

pub trait Identified {
    fn instance_id(&self) -> InstanceId;
}

impl InstanceId {
    pub fn new(uuid: Uuid) -> InstanceId;

    pub fn derive(config_dir: &Path) -> InstanceId;
}

pub fn default_config_dir() -> PathBuf;

pub async fn resolve_instance(config_dir: &Path) -> InstanceId;
```

### src/daemon/src/daemon.rs
```rust
pub struct Daemon {
    instance_id: InstanceId,
}

impl Daemon {
    pub fn new(instance_id: InstanceId) -> Daemon;
}

impl Identified for Daemon;

pub async fn run_daemon(config_dir: &Path) -> ();
```

## Deletions

### src/platform_abi/src/instance.rs
```rust
impl InstanceId {
    pub fn new() -> InstanceId;
}
```
````
