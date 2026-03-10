# 主机与存储

`trainsh` 会把计算位置和产物位置分开建模。

## 主机

主机代表命令真正运行的位置。

常见模式：

- `local` 适合本机任务
- SSH 主机适合长期存在的远端机器
- Vast 主机适合按需 GPU 实例
- Colab 主机适合 notebook 驱动的算力环境

常用命令：

```bash
train host add
train host list
train host test <name>
train host ssh <name>
```

## 存储

存储别名代表 tmux session 之外的文件位置。

常用命令：

```bash
train storage add
train storage list
train storage test <name>
```

## `transfer` 和 storage helper 的选择

- 当你需要在 host 风格端点和本地路径之间复制时，用 `transfer(...)`
- 当目标是存储别名，并且你需要做存在性检查、元数据查询、同步或对象存储语义时，用 `storage_*`

## 相关参考

- [Transfer](../package-reference/transfer.md)
- [Storage](../package-reference/storage.md)
- [Workflow helpers](../package-reference/workflow-helpers.md)
