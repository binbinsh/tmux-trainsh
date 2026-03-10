# Schedule and resume runs

This tutorial covers two different concerns:

- running recipes on a schedule
- recovering from interruption with `resume`

## Add scheduling metadata

Declare metadata directly in `recipe(...)`:

```python
recipe("nightly-train", schedule="@every 30m", owner="ml", tags=["nightly", "train"])
```

## Inspect schedules

```bash
train schedule list
train schedule status
```

## Run the scheduler

```bash
train schedule run --once
train schedule run --forever
```

## Resume a run

```bash
train resume my-recipe
train resume my-recipe --var MODEL=llama-70b
```

`resume` restores saved runtime state, host resolution, and tmux session mapping. It intentionally does not allow host overrides.

## When to use `latest_only`

Scheduled recipes often benefit from:

```python
latest_only(fail_if_unknown=False)
```

This prevents stale scheduled runs from doing duplicate work when a newer run already exists.

## Related pages

- [Executors and scheduling](../concepts/executors.md)
- [Runtime metadata](../concepts/runtime-metadata.md)
- [Control flow](../package-reference/control-flow.md)
