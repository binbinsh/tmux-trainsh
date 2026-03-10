# Executors and scheduling

Executors control how the DAG is scheduled once a recipe is loaded.

## Supported executor names

The Python runtime supports aliases such as:

- `sequential`
- `thread_pool`
- `process_pool`
- `local`
- `airflow`
- `celery`
- `dask`
- `debug`

Kubernetes is intentionally unsupported.

## How they behave

- `sequential` respects the DAG but limits concurrency to one worker
- thread-pool style executors allow dependency-based parallelism
- pools can throttle specific classes of work

## Where to set them

```python
recipe(
    "demo",
    executor="thread_pool",
    workers=4,
)
```

## Related pages

- [Dependency DAG](dependency-dag.md)
- [Recipe authoring](../package-reference/recipe-builder.md)
