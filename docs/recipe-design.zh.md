# Recipe 系统设计

> 状态说明：这份文档主要保留历史上的 TOML 设计背景。
> 当前仓库里活跃维护的产品路径是 Python `.py` recipe API。

## 总览

这份设计文档描述的是早期的 Recipe 系统目标：把固定的 Task/Session 流程扩展成可组合、可依赖、可恢复的工作流引擎。

主要设计目标包括：

- 原子操作：SSH、文件同步、Vast 操作等基础积木
- 操作组：把多个原子操作组合成顺序或并行组
- 依赖图：step 之间声明依赖，允许并行执行
- 执行控制：暂停、恢复、取消和重试
- 持久化：把 recipe 保存为声明式文件

## 当前产品路径

当前推荐使用：

- `~/.config/tmux-trainsh/recipes/*.py`
- `from trainsh.pyrecipe import *`
- `train run / resume / status / logs / jobs / schedule`

当前 tmux 运行时行为是：

- `tmux.open @host as name` 对应 detached tmux session
- 远端 tmux 操作通过 SSH 上的 tmux CLI 执行
- 本地 `train` 退出后，远端 tmux 中的命令仍会继续运行
- `train status --last` 会显示最近运行任务和 attach 提示
- live/bridge/window session 统一采用 `train_<job_name>_<index>` 命名

## 核心概念

### Step

Step 是 recipe 的基本执行单元。每个 step：

- 在 recipe 内有唯一 ID
- 包含一个原子操作或操作组
- 可以声明依赖
- 会跟踪执行状态和输出

### 目标主机

早期设计里，recipe 更强调“声明主机需求”而不是绑定具体主机。当前 Python DSL 通常会这样表达：

```python
from trainsh.pyrecipe import *

recipe("gpu-demo")
host("gpu", "placeholder")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=16)
ready = vast_wait(timeout="5m", after=pick)
```

后续步骤一般通过 `session(..., on="gpu")` 或 `shell(..., host="gpu")` 使用这个已解析的主机别名。

### 操作类别

历史设计里的操作大致覆盖这些类别：

- 命令执行：`run_commands`
- 传输：`transfer`
- Git 与模型下载：`git_clone`、`hf_download`
- Vast.ai：`vast_start`、`vast_stop`、`vast_copy`
- tmux：`tmux_new`、`tmux_send`、`tmux_capture`、`tmux_kill`
- Google Drive：挂载和卸载
- 控制流：`sleep`、`wait_condition`、`assert`
- 工具类：`set_var`、`get_value`、`http_request`、`notice`
- SSH 与 Rsync

当前 Python API 已经把这些能力的大部分以更统一的 helper 方式暴露出来，例如 `session(...)`、`transfer(...)`、`sql_*`、`http_*`、`choose(...)`、`latest_only(...)`。

## 依赖图与执行

历史设计和当前产品都共享一个核心思想：recipe 会被组织成 DAG。

运行引擎会：

1. 根据依赖构建 DAG
2. 检查环
3. 按拓扑顺序调度
4. 在无依赖冲突时并行执行

当前 Python 运行时已经把这条路径落地到新的 DAG 处理器和调度器中。

## 变量与插值

变量插值一直是设计重点。历史语法主要关注：

- 普通变量
- 目标主机变量
- Secret 引用

在当前 Python recipe 中，这些能力仍然保留，只是表达方式从 TOML 迁移到了更扁平的 Python authoring DSL。

## 结论

这份文档应被理解为“历史设计背景”，不是当前的主 API 说明。实际使用时，请优先阅读：

- [Python recipes](python-recipes.md)
- [Package reference](package-reference/_index.md)
- [tmux sessions](concepts/tmux-sessions.md)
- [Dependency DAG](concepts/dependency-dag.md)
