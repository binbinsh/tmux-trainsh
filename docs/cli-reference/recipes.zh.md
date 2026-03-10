# Recipe 文件

管理 Python recipe 文件和模板。

## 何时使用

- 从模板创建新的 recipe。
- 查看或打印内置 recipe。

## 命令

```bash
train recipes --help
```

## CLI 帮助输出

```text
[subcommand] [args...]

Subcommands:
  list             - List available recipes and bundled examples
  show <name>      - Show recipe details
  syntax           - Show full DSL syntax reference
  new <name>       - Create a new recipe from template
  edit <name>      - Open recipe in editor
  rm <name>        - Remove a recipe

Recipes are stored in: ~/.config/tmux-trainsh/recipes/ (.py)
Runtime commands live at the top level:
  train run|resume|status|logs|jobs|schedule ...
Available templates:
  minimal | feature-tour
```

## 说明

- 语法说明在 [Python Recipes](../python-recipes.md) 和 [Package Reference](../package-reference/_index.md)。
