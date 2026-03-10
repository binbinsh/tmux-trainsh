# Branching and control flow

`trainsh` recipes form a DAG. Control-flow helpers let you express decision points and merge behavior explicitly.

## Basic branch

```python
branch = choose("RUN_PATH", when='MODE == "production"', then="prod", else_="dev")
```

## Short-circuit

```python
check = short_circuit("READY == true")
```

Aliases:

- `skip_if(...)`
- `skip_if_not(...)`

## latest_only

```python
latest = latest_only(fail_if_unknown=False)
```

This is mainly useful for scheduled jobs.

## Join behavior

Use `join(...)` or the explicit trigger-rule helpers:

```python
merge = join(after=[left, right])
done = on_all_done(after=merge)
```

## Related pages

- [Dependency DAG](../concepts/dependency-dag.md)
- [Control flow reference](../package-reference/control-flow.md)
- [Control helpers](../package-reference/control-helpers.md)
