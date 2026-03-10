# 帮助中心

集中查看帮助主题和命令入口。

## 何时使用

- 在不通读整站文档的情况下快速找到正确命令。
- 通过 `train help recipe` 直接进入 recipe 语法说明。

## 命令

```bash
train help
```

## CLI 帮助输出

```text
tmux-trainsh Help

Help Topics
  recipe      Python recipe syntax, examples, and lifecycle
  recipes     Recipe file management commands
  run         Recipe execution options
  resume      Resume behavior and constraints
  status      Session and live job inspection
  logs        Execution log inspection
  jobs        Job history inspection
  schedule    Scheduler commands
  transfer    File transfer commands
  host        Host management
  storage     Storage backend management
  secrets     Secret management
  config      Configuration and tmux settings
  vast        Vast.ai management
  colab       Google Colab integration
  pricing     Pricing and currency tools
  update      Update checks

Examples
  train help
  train help recipe
  train help run
  train help schedule
  train help host
```

## 说明

- 使用 `train help recipe` 查看语法和示例。
- 使用 `train <command> --help` 查看命令自己的参数。
