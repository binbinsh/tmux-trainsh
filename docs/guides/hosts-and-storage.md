# Hosts and storage

`trainsh` separates compute from artifact locations.

## Hosts

Hosts represent where commands run.

Common patterns:

- `local` for workstation tasks
- SSH hosts for persistent remote machines
- Vast-backed hosts for on-demand GPU instances
- Colab-backed hosts for notebook-driven compute

Useful commands:

```bash
train host add
train host list
train host test <name>
train host ssh <name>
```

## Storage

Storage aliases represent where files live outside a tmux session.

Useful commands:

```bash
train storage add
train storage list
train storage test <name>
```

## When to use `transfer` vs storage helpers

- Use `transfer(...)` when copying between host-style endpoints and local paths.
- Use `storage_*` helpers when the destination is a storage alias and you want existence checks, metadata, sync, or object-store semantics.

## Related reference

- [Transfer](../package-reference/transfer.md)
- [Storage](../package-reference/storage.md)
- [Workflow helpers](../package-reference/workflow-helpers.md)
