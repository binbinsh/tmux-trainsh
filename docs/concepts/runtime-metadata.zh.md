# 运行时元数据

`trainsh` 会持久化工作流运行状态，使得运行结果可查看，并在很多情况下可恢复。

## 保存了什么

运行时元数据库会记录：

- DAG 与运行元数据
- task instance 状态
- try number
- XCom 值

这些元数据也支撑了 `latest_only` 和调度器的部分行为。

## 为什么重要

运行时元数据支撑了：

- `train jobs`
- `train status`
- `train logs`
- `train resume <name>`

## 相关页面

- [调度与恢复运行](../tutorials/scheduling-and-resume.md)
- [SQLite 与 XCom](../guides/sqlite-and-xcom.md)
