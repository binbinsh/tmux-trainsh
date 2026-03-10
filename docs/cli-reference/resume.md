# Resume

Resume the latest interrupted or failed run for one recipe.

## When to use it

- Continue from the latest persisted runtime state.
- Restart after interruption without rebuilding tmux state manually.

## Command

```bash
train resume --help
```

## CLI help output

```text
Usage: train resume <name> [options]

Options:
  --var NAME=VALUE  Override variable while resuming

Host overrides are not supported when resuming.
```

## Notes

- Resume restores saved hosts and tmux state. Only `--var` overrides are supported.
