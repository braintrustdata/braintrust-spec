# Dataset versioning: overview

## What is dataset versioning?

**Dataset versioning** lets users refer to a specific state of a dataset without copying the dataset into a new object each time it changes.

Every change to a dataset advances its **head version**. Braintrust exposes that version as an opaque string identifier (`xact_id`). Users can then work with dataset state in three ways:

- by exact **version**
- by named **snapshot**
- by **environment tag** such as `staging` or `production`

This makes it possible to:

- run experiments against a reproducible dataset state
- promote a dataset version through environments
- roll back the live head to an earlier state
- keep a stable audit trail of how a dataset evolved over time

The feature is designed so existing dataset usage keeps working: if the caller does not specify a version, snapshot, or environment, the SDK continues to operate on the current head version.

## How it works

```text
 Developer / SDK                          Braintrust API                    Consumers
+---------------------------+            +---------------------------+      +----------------------+
|                           |            |                           |      |                      |
| insert / update / delete  | ---------> | append dataset changes    |      | initDataset({        |
|                           |            | new head version          |      |   version })         |
| createSnapshot("v1")      | ---------> | snapshot name -> version  |      | initDataset({        |
|                           |            |                           |      |   snapshotName })    |
| setEnvironmentTag("prod") | ---------> | environment -> version    |      | initDataset({        |
|                           |            |                           |      |   environment })     |
| restorePreview(version)   | ---------> | diff target vs head       |      | initExperiment(...)  |
| restore(version)          | ---------> | write compensating rows   |      | persists resolved    |
|                           |            | new head version          |      | dataset_version      |
+---------------------------+            +---------------------------+      +----------------------+
```

1. **Mutation**: Dataset row writes create new dataset state and advance the head version.
2. **Snapshotting**: A snapshot stores a human-readable name that points at a dataset version.
3. **Environment tagging**: An environment tag stores a movable alias from an environment slug to a dataset version.
4. **Resolution**: When a caller selects a dataset by snapshot or environment, the SDK resolves that selector to a concrete version before doing work that requires reproducibility.
5. **Restore**: Restore computes the difference between the current head and a target version, then writes compensating rows so the new head matches the target state while preserving history.

## Key concepts

**Dataset version**

An immutable identifier for a specific dataset state. SDKs should treat this as an opaque string and avoid assuming a particular format beyond “version-like string”.

**Head version**

The latest version of the dataset. This is what callers get when they initialize a dataset with no selector.

**Snapshot**

A named reference to a dataset version. Snapshots are useful for human-readable checkpoints such as `baseline`, `weekly-build-42`, or `before-cleanup`.

SDKs should expose snapshot lifecycle operations:

- create snapshot
- list snapshots
- update snapshot metadata
- delete snapshot

Snapshots are intended to be checkpoint-like, but SDKs may also support intentionally moving an existing named snapshot to a new version when requested.

**Environment tag**

A mutable alias from an environment slug to a dataset version. Environments are useful for promotion workflows such as `dev -> staging -> production`.

Environment tags are conceptually different from snapshots:

- snapshots are usually named historical checkpoints
- environment tags are usually deployment-style aliases that move over time

The underlying environment-tag abstraction is shared with other versioned objects, including prompts.

**Selector precedence**

When multiple dataset selectors are provided, SDKs should resolve them in this order:

1. `version`
2. `snapshotName`
3. `environment`

This ensures an explicit version always wins over indirect references.

**Concrete version persistence**

A dataset may be selected by snapshot or environment, but reproducible runs should persist the resolved concrete dataset version. For example, experiment registration should record `dataset_version` after resolving the selector, rather than relying on an environment tag that may later move.

**Backward compatibility**

Code that does not use dataset versioning must continue to behave as it did before. Existing dataset reads and writes should default to the live head version.

## Expected SDK capabilities

A dataset-versioning-capable SDK should support the following behaviors:

- initialize a dataset at head, by exact version, by snapshot name, or by environment tag
- expose the current dataset version for a dataset object
- create, list, update, and delete snapshots
- resolve snapshot names to versions
- resolve environment tags to versions
- assign an environment tag to a dataset version
- optionally create the target environment if the SDK chooses to provide that convenience
- preview a restore before applying it
- restore the dataset head to a target version
- resolve snapshot and environment selectors to concrete versions before registering experiments or other reproducibility-sensitive operations

## Example

```pseudocode
# Open the live dataset
dataset = initDataset(
    project = "Support bot",
    dataset = "customer-faq",
)

# Mutate the live head
dataset.insert({ id: "q1", input: "Capital of France?", expected: "Paris" })
dataset.flush()

# Capture a named checkpoint
baseline = dataset.createSnapshot(
    name = "baseline",
    description = "Initial FAQ baseline",
)

# Promote that version to an environment
dataset.setEnvironmentTag(
    environment = "staging",
    version = baseline.xact_id,
)

# Load the same dataset in three different ways
byVersion = initDataset(
    project = "Support bot",
    dataset = "customer-faq",
    version = baseline.xact_id,
)

bySnapshot = initDataset(
    project = "Support bot",
    dataset = "customer-faq",
    snapshotName = "baseline",
)

byEnvironment = initDataset(
    project = "Support bot",
    dataset = "customer-faq",
    environment = "staging",
)

# Preview and apply a rollback to the baseline version
preview = dataset.restorePreview(version = baseline.xact_id)
# preview => { rows_to_restore: ..., rows_to_delete: ... }

result = dataset.restore(version = baseline.xact_id)
# result => { xact_id: new_head_version, rows_restored: ..., rows_deleted: ... }
```

## Versions vs. snapshots vs. environments

**Version** is the exact dataset state to use.

- immutable
- best for strict reproducibility
- usually machine-generated

**Snapshot** is a named reference to a version.

- human-readable
- good for checkpoints and milestones
- resolved to a concrete version before reproducible execution

**Environment** is a movable alias to a version.

- human-readable
- good for promotion workflows
- expected to move over time
- resolved to a concrete version before reproducible execution

The typical workflow is:

1. edit a live dataset until it reaches a useful state
2. capture that state as a snapshot
3. assign or move an environment tag to that version
4. run experiments or remote eval jobs against the resolved version
5. restore the dataset head to an earlier version if needed

## Restore semantics

Restore is intentionally not an in-place rewind of history.

Instead:

1. the system computes which rows differ between the current head and the target version
2. `restorePreview` reports how many rows would be reinserted or updated and how many rows would be deleted
3. `restore` writes compensating dataset rows so the new head matches the target state
4. the system returns the new head version produced by that restore

This preserves an append-only history while still giving users rollback behavior.

If the current head already matches the target version, restore should be a no-op and return counts of zero.

## Automations and downstream consumers

Environment tag updates may be useful beyond SDK reads:

- automation systems may trigger on environment updates
- webhook consumers can react to “promote this dataset version to staging” events
- remote eval flows can accept `dataset_version` or `dataset_environment` and resolve them to a concrete version before execution

This means SDK authors should think of dataset versioning as more than local convenience methods. It is a shared contract across SDKs, APIs, automations, and evaluation runtimes.

## Further reading

| Document | Purpose |
|----------|---------|
| [contracts.md](contracts.md) | Snapshot, environment-tag, and restore APIs and data shapes |
