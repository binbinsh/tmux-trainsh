# CLI 参考

CLI 围绕两类能力组织：

- 顶层工作流命令，用来运行、恢复、查看和调度任务
- 资源管理命令，用来管理主机、存储、密钥和云资源

如果你想先按任务路径快速上手，请先看 [快速浏览](../quicktour.md)。当你需要精确的命令语法时，再使用这一节。

## 命令索引

| 命令 | 用途 | 页面 |
| --- | --- | --- |
| `train help` | 集中查看帮助主题和命令入口。 | [打开](help.md) |
| `train run` | 立即执行一个 recipe。 | [打开](run.md) |
| `train resume` | 恢复某个 recipe 最近一次中断或失败的运行。 | [打开](resume.md) |
| `train status` | 查看当前和最近的会话状态。 | [打开](status.md) |
| `train logs` | 查看当前任务或指定任务的执行日志。 | [打开](logs.md) |
| `train jobs` | 查看最近的任务状态历史。 | [打开](jobs.md) |
| `train schedule` | 查看和运行定时 recipe。 | [打开](schedule.md) |
| `train recipes` | 管理 Python recipe 文件和模板。 | [打开](recipes.md) |
| `train transfer` | 在主机和存储后端之间复制数据。 | [打开](transfer.md) |
| `train host` | 管理 SSH、本地、Colab 和 Vast 主机。 | [打开](host.md) |
| `train storage` | 管理本地路径、R2、B2、S3 等存储后端。 | [打开](storage.md) |
| `train secrets` | 存储并查看 API key 与凭据。 | [打开](secrets.md) |
| `train config` | 查看和修改运行时与 tmux 配置。 | [打开](config.md) |
| `train vast` | 管理 Vast.ai 实例。 | [打开](vast.md) |
| `train colab` | 管理 Google Colab 主机。 | [打开](colab.md) |
| `train pricing` | 查看汇率并估算成本。 | [打开](pricing.md) |
| `train update` | 检查 trainsh 的新版本。 | [打开](update.md) |
