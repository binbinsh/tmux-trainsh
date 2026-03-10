# Package Reference

这一节是 Python 编写 API 的技术参考，对应公开入口：

```python
from trainsh.pyrecipe import *
```

当你已经理解产品结构，只是需要查具体顶层 helper、参数名或返回类型时，请从这里开始。

## 参考地图

| 页面 | 关注点 | 链接 |
| --- | --- | --- |
| Recipe 编写 | 顶层 authoring 语法是 recipe 的起点，用来声明工作流元数据、变量、主机别名、存储别名、执行器设置，以及共享默认项。 | [打开](recipe-builder.md) |
| 基础 Provider | 这些 helper 覆盖 shell 命令、Python 片段、通知，以及一些直接的任务原语。 | [打开](basic-providers.md) |
| 工作流 Helper | 工作流 helper 覆盖 Git 操作、主机探测、SSH 命令、变量捕获，以及轻量级的 HTTP 或文件等待。 | [打开](workflow-helpers.md) |
| 控制流 | 控制流 helper 实现 latest-only、分支、短路判断和条件等待等能力。 | [打开](control-flow.md) |
| Session API | 绑定后的 session 对象会把后续步骤附着到同一个 tmux 会话上，这是表达长时间远端任务的核心 API。 | [打开](session-api.md) |
| HTTP 与网络 | HTTP helper 覆盖直接请求别名、JSON helper，以及用于健康检查的轮询式 sensor。 | [打开](network.md) |
| SQLite 与 XCom | SQLite helper 用于本地数据库查询，XCom 风格 helper 用于通过 sqlite 元数据持久化和读取小型运行时值。 | [打开](sqlite-and-xcom.md) |
| 通知与杂项 | 杂项 helper 覆盖显式失败步骤、Webhook 风格通知，以及 XCom push/pull 操作。 | [打开](notifications-and-misc.md) |
| 存储 | 存储 helper 提供上传、下载、复制、移动、同步、查看元数据，以及等待存储路径等能力。 | [打开](storage.md) |
| 传输 | 传输 helper 用于在本地路径、远端主机和存储端点之间移动文件或目录。 | [打开](transfer.md) |
| 控制 Helper | 控制 helper 用于直接管理 tmux 会话、添加 sleep，以及定义显式 trigger-rule 合流点。 | [打开](control-helpers.md) |
| 公共模型 | 工厂函数和导出的模型对象。 | [打开](public-models.md) |
