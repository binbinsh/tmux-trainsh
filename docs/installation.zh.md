# 安装

## 环境要求

- Python 3.10 或更高版本
- `tmux`
- 可选但常用：`rsync`、`rclone`

## 作为工具安装

```bash
uv tool install tmux-trainsh
```

如果你只是想直接使用 `trainsh`，这是最简单的安装方式。

## 本地开发安装

```bash
git clone https://github.com/binbinsh/tmux-trainsh
cd tmux-trainsh
uv pip install -e .
```

刷新导出的 Hugo 文档：

```bash
python scripts/generate_docs.py
```

## 基本检查

确认 CLI 可用：

```bash
train --help
train help recipe
```

确认 `tmux` 已安装：

```bash
tmux -V
```

## 下一步

1. [快速浏览](quicktour.md)
2. [开始使用](getting-started.md)
3. [编写第一个 recipe](tutorials/first-recipe.md)
