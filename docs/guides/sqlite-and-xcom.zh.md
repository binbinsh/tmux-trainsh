# SQLite 与 XCom

这两个能力解决的是相关但不同的问题。

## SQLite helper

当你需要结构化本地状态时，使用 SQLite helper：

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

## XCom helper

当你只是想在任务间传递很小的值时，使用 XCom helper：

```python
push = xcom_push("result", value="ok")
pull = xcom_pull("result", task_ids=["push"], output_var="RESULT_COPY", after=push)
```

## 经验法则

- 小型运行时值用 XCom
- 持久化结构化记录用 SQLite
- 大型产物用文件或存储后端

## 相关参考

- [SQLite and XCom reference](../package-reference/sqlite-and-xcom.md)
- [Notifications and misc reference](../package-reference/notifications-and-misc.md)
