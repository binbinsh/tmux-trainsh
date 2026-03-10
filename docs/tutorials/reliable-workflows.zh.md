# 构建可靠工作流

使用 `trainsh` 而不是临时 shell 脚本的核心原因，是长时间任务更可恢复、更可观测。这个教程展示让工作流更可靠的关键功能。

## 先设置默认项

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

## 增加显式等待和合流点

```python
latest = latest_only(fail_if_unknown=False)
branch = choose("RUN_KIND", when='MODE == "prod"', then="prod", else_="dev", after=latest)
join(after=branch)
```

## 持久化小型状态

```python
push = xcom_push("health_body", from_var="HEALTH_BODY")
pull = xcom_pull("health_body", task_ids=["push"], output_var="HEALTH_BODY_COPY", after=push)
```

## 持久化工作流状态

```python
setup = sql_script("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, status TEXT);", db="$SQLITE_DB")
record = sql_exec("INSERT INTO runs(status) VALUES ('done')", db="$SQLITE_DB", after=setup)
```

## 观察产物是否就绪

```python
wait = storage_wait("artifacts", "/runs/$RUN_NAME/done.txt", timeout="30m")
```

## 相关页面

- [SQLite 与 XCom](../guides/sqlite-and-xcom.md)
- [通知与回调](../guides/notifications-and-callbacks.md)
- [运行时元数据](../concepts/runtime-metadata.md)
