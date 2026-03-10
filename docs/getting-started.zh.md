# 开始使用

这是一份实践型配置清单。如果你想先快速过一遍流程，请先看 [快速浏览](quicktour.md)。

## 安装并验证

按照 [安装](installation.md) 完成安装后，执行：

```bash
train --help
train help recipe
tmux -V
```

## 配置密钥

设置工作流需要的凭据：

```bash
train secrets set VAST_API_KEY
train secrets set HF_TOKEN
train secrets set OPENAI_API_KEY
```

## 添加算力

至少添加一个主机：

```bash
train host add
train host list
train host test <name>
```

## 添加存储

如果你的工作流会发布或下载产物：

```bash
train storage add
train storage list
train storage test <name>
```

## 创建并查看 recipe

```bash
train recipes new demo --template minimal
train recipes show demo
train help recipe
```

## 运行、查看和恢复

```bash
train run demo
train status
train logs
train jobs
train resume demo
```

## 添加调度元数据

在 recipe 文件顶部添加注释：

```python
# schedule: @every 15m
# owner: ml
# tags: nightly,train
```

然后查看或运行调度器：

```bash
train schedule list
train schedule run --once
train schedule run --forever
train schedule status
```
