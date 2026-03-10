# trainsh 文档

`trainsh` 是一个以终端为中心的工作流系统，面向长时间运行的 GPU 任务和自动化任务。

它把这些能力组合到一起：

- 基于 tmux 的持久会话，用于稳定执行命令
- 通过 SSH、Colab 和 Vast.ai 连接远端主机
- 本地和云端存储后端
- 带 DAG 调度、重试、超时、回调和运行时元数据的 Python recipes

## 文档导航

### 快速开始

- [安装](installation.md)
- [快速浏览](quicktour.md)
- [开始使用](getting-started.md)

### 教程

- [编写第一个 recipe](tutorials/first-recipe.md)
- [运行远端 GPU 训练](tutorials/remote-gpu-training.md)
- [构建可靠工作流](tutorials/reliable-workflows.md)
- [调度与恢复运行](tutorials/scheduling-and-resume.md)

### 指南

- [Python recipes](python-recipes.md)
- [主机与存储](guides/hosts-and-storage.md)
- [分支与控制流](guides/branching-and-control-flow.md)
- [SQLite 与 XCom](guides/sqlite-and-xcom.md)
- [通知与回调](guides/notifications-and-callbacks.md)

### 概念

- [依赖 DAG](concepts/dependency-dag.md)
- [tmux 会话](concepts/tmux-sessions.md)
- [运行时元数据](concepts/runtime-metadata.md)
- [执行器与调度](concepts/executors.md)

### 参考

- [Package reference](package-reference/_index.md)
- [CLI reference](cli-reference/_index.md)
- [示例](examples/_index.md)

### 内部设计

- [Recipe 设计](recipe-design.md)
- [存储设计](storage-design.md)
- [Secrets](secrets.md)
- [文档系统](documentation.md)

## 推荐阅读顺序

1. [安装](installation.md)
2. [快速浏览](quicktour.md)
3. [编写第一个 recipe](tutorials/first-recipe.md)
4. [Python recipes](python-recipes.md)
5. [Package reference](package-reference/_index.md)

## 本地生成文档

```bash
python scripts/generate_docs.py
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```
