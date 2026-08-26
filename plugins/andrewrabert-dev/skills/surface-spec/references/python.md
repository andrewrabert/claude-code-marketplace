# Python Surface Spec

A surface spec for one change, stated as an equation: the set of Python declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- Both direction sections are always present. An empty `## Additions` section holds the phrase `No additions.` in place of file sections. An empty `## Deletions` section holds the phrase `No deletions.`
- Constrained declaration kinds: `def`, `class`. Bodies, private helpers, and formatting sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any file content beyond declarations.
- Begins with a title, `# Surface Spec: Python`, followed by the equation as one binding sentence.
- Each direction section holds one `### <specific file>` section per file that holds a constrained declaration; each file section holds one fenced `python` block.
- A function is a signature stub with a `: ...` body. Methods sit inside their class, decorators intact.
- A class is its full definition, attributes included.
- An interface is a protocol: `class <Name>(Protocol)` with method stubs.

## Format

````markdown
# Surface Spec: Python
The set of `def` and `class` declarations the resulting combined diff
adds must equal the declarations under `## Additions`, and the set it
deletes must equal the declarations under `## Deletions`.

## Additions

### <specific_file>
```python
<declarations>
```

## Deletions

### <specific_file>
```python
<declarations>
```
````

## Example

````markdown
# Surface Spec: Python
The set of `def` and `class` declarations the resulting combined diff
adds must equal the declarations under `## Additions`, and the set it
deletes must equal the declarations under `## Deletions`.

## Additions

### src/platform_abi/instance.py
```python
class InstanceId:
    uuid: UUID

    def __init__(self, uuid: UUID) -> None: ...

    @classmethod
    def derive(cls, config_dir: Path) -> "InstanceId": ...


class Identified(Protocol):
    def instance_id(self) -> InstanceId: ...


def default_config_dir() -> Path: ...


async def resolve_instance(config_dir: Path) -> InstanceId: ...
```

### src/daemon/daemon.py
```python
class Daemon(Identified):
    def __init__(self, instance_id: InstanceId) -> None: ...

    def instance_id(self) -> InstanceId: ...


async def run_daemon(config_dir: Path) -> None: ...
```

## Deletions

### src/platform_abi/instance.py
```python
class InstanceId:
    @classmethod
    def new(cls) -> "InstanceId": ...
```
````

## Example: additions only

````markdown
# Surface Spec: Python
The set of `def` and `class` declarations the resulting combined diff
adds must equal the declarations under `## Additions`, and the set it
deletes must equal the declarations under `## Deletions`.

## Additions

### src/platform_abi/instance.py
```python
def default_config_dir() -> Path: ...
```

## Deletions

No deletions.
````
