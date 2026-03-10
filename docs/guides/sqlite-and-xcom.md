# SQLite and XCom

These features solve two related but different problems.

## SQLite helpers

Use SQLite helpers when you want structured local state:

```python
setup = sql_script(
    "CREATE TABLE IF NOT EXISTS metrics(step TEXT, loss REAL);",
    db="$SQLITE_DB",
)
write = sql_exec(
    "INSERT INTO metrics(step, loss) VALUES ('train', 0.42)",
    db="$SQLITE_DB",
    after=setup,
)
rows = sql_query(
    "SELECT step, loss FROM metrics",
    db="$SQLITE_DB",
    into="METRICS",
    after=write,
)
```

## XCom helpers

Use XCom helpers for small values passed between tasks:

```python
push = xcom_push("result", value="ok")
pull = xcom_pull("result", task_ids=["push"], output_var="RESULT_COPY", after=push)
```

## Rule of thumb

- Use XCom for small runtime values.
- Use SQLite for durable structured records.
- Use files or storage for large artifacts.

## Related reference

- [SQLite and XCom reference](../package-reference/sqlite-and-xcom.md)
- [Notifications and misc reference](../package-reference/notifications-and-misc.md)
