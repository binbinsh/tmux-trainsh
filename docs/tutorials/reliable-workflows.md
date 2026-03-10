# Build reliable workflows

The main reason to use `trainsh` instead of ad hoc shell scripts is reliability. This tutorial shows the features that make long-running jobs restartable and observable.

## Start with defaults

```python
defaults(
    retry=2,
    retry_delay="30s",
    timeout="2h",
    backoff=True,
    on_success=["echo success {step_id}"],
    on_failure=["echo failure {step_id}"],
)
```

## Add explicit waits and merge points

```python
latest = latest_only(fail_if_unknown=False)
branch = choose("RUN_KIND", when='MODE == "prod"', then="prod", else_="dev", after=latest)
join(after=branch)
```

## Persist small state

```python
push = xcom_push("health_body", from_var="HEALTH_BODY")
pull = xcom_pull("health_body", task_ids=["push"], output_var="HEALTH_BODY_COPY", after=push)
```

## Persist workflow state

```python
setup = sql_script("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, status TEXT);", db="$SQLITE_DB")
record = sql_exec("INSERT INTO runs(status) VALUES ('done')", db="$SQLITE_DB", after=setup)
```

## Observe artifacts

```python
wait = storage_wait("artifacts", "/runs/$RUN_NAME/done.txt", timeout="30m")
```

## Related pages

- [SQLite and XCom](../guides/sqlite-and-xcom.md)
- [Notifications and callbacks](../guides/notifications-and-callbacks.md)
- [Runtime metadata](../concepts/runtime-metadata.md)
