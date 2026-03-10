# Recipes

Manage Python recipe files and starter templates.

## When to use it

- Create a new recipe from a starter template.
- Inspect or print bundled recipes.

## Command

```bash
train recipes --help
```

## CLI help output

```text
[subcommand] [args...]

Subcommands:
  list             - List available recipes and bundled examples
  show <name>      - Show recipe details
  new <name>       - Create a new recipe from template
  edit <name>      - Open recipe in editor
  rm <name>        - Remove a recipe

Recipes are stored in: ~/.config/tmux-trainsh/recipes/ (.py)
Runtime commands live at the top level:
  train run|resume|status|logs|jobs|schedule ...
Available templates:
  minimal | feature-tour
```

## Notes

- Syntax lives in [Python Recipes](../python-recipes.md) and [Package Reference](../package-reference/_index.md).
