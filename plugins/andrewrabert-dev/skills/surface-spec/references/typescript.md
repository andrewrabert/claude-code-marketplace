# TypeScript Surface Spec

A surface spec for one change, stated as an equation: the set of TypeScript declarations the combined diff adds equals the set under `## Additions`, and the set it deletes equals the set under `## Deletions`.

- One document covers one change, in both directions: additions and deletions.
- Both direction sections are always present. An empty `## Additions` section holds the phrase `No additions.` in place of file sections. An empty `## Deletions` section holds the phrase `No deletions.`
- Constrained declaration kinds: `function`, `class`, `interface`, `type`, `enum`. Bodies, private helpers, and formatting sit outside the equation and stay free.
- Does not document rationale, behavior, implementation, or any file content beyond declarations.
- Begins with a title, `# Surface Spec: TypeScript`, followed by the equation as one binding sentence.
- Each direction section holds one `### <specific file>` section per file that holds a constrained declaration; each file section holds one fenced `typescript` block.
- Declarations are written in declaration-file (`.d.ts`) form: modifiers intact (`export`, `default`, `abstract`, `static`, `readonly`, `private`, `protected`, `async`), no bodies.
- A function is a `;`-terminated signature stub. Each overload signature is its own stub. Methods and constructors sit inside their class, decorators intact.
- A module-scope arrow function or function expression bound to a `const` is a `function` declaration, written as `const <name>: (<params>) => <return>;`.
- A class is its full definition: `extends` and `implements` clauses, properties with their types, and method stubs.
- An interface, type alias, or enum is its full definition, members included.

## Format

````markdown
# Surface Spec: TypeScript
The set of `function`, `class`, `interface`, `type`, and `enum`
declarations the resulting combined diff adds must equal the declarations
under `## Additions`, and the set it deletes must equal the declarations
under `## Deletions`.

## Additions

### <specific_file>
```typescript
<declarations>
```

## Deletions

### <specific_file>
```typescript
<declarations>
```
````

## Example

````markdown
# Surface Spec: TypeScript
The set of `function`, `class`, `interface`, `type`, and `enum`
declarations the resulting combined diff adds must equal the declarations
under `## Additions`, and the set it deletes must equal the declarations
under `## Deletions`.

## Additions

### src/platform-abi/instance.ts
```typescript
export type InstanceSource = 'derived' | 'random';

export class InstanceId {
  readonly uuid: string;
  readonly source: InstanceSource;

  constructor(uuid: string, source: InstanceSource);

  static derive(configDir: string): InstanceId;
}

export interface Identified {
  instanceId(): InstanceId;
}

export function defaultConfigDir(): string;

export async function resolveInstance(configDir: string): Promise<InstanceId>;
```

### src/daemon/daemon.ts
```typescript
export enum DaemonState {
  Starting = 'starting',
  Running = 'running',
  Stopped = 'stopped',
}

export class Daemon implements Identified {
  private state: DaemonState;

  constructor(instanceId: InstanceId);

  instanceId(): InstanceId;
}

export const runDaemon: (configDir: string) => Promise<void>;
```

## Deletions

### src/platform-abi/instance.ts
```typescript
export class InstanceId {
  static create(): InstanceId;
}
```
````

## Example: additions only

````markdown
# Surface Spec: TypeScript
The set of `function`, `class`, `interface`, `type`, and `enum`
declarations the resulting combined diff adds must equal the declarations
under `## Additions`, and the set it deletes must equal the declarations
under `## Deletions`.

## Additions

### src/platform-abi/instance.ts
```typescript
export function defaultConfigDir(): string;
```

## Deletions

No deletions.
````
