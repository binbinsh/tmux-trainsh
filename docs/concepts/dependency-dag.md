# Dependency DAG

Every Python recipe is compiled into a normalized DAG.

## The basic unit

Each helper call adds a step. Dependencies are expressed with `after=...`.

```python
clone = main("git clone ...")
train = main.bg("python train.py", after=clone)
done = main.idle(after=train)
```

## Why this matters

The DAG model is what enables:

- executor-based scheduling
- retries and timeouts
- trigger rules
- branch and join behavior
- runtime metadata persistence

## Sequential vs parallel execution

Even `sequential` still follows dependency semantics. It is effectively dependency scheduling with a worker limit of one.

## Related pages

- [Executors and scheduling](executors.md)
- [Control flow guide](../guides/branching-and-control-flow.md)
