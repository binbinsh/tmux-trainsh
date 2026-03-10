# Help Hub

Centralized help topics and entry points.

## When to use it

- Find the right command without reading the full site first.
- Jump to recipe syntax with `train help recipe`.

## Command

```bash
train help
```

## CLI help output

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

## Notes

- Use `train help recipe` for syntax and examples.
- Use `train <command> --help` for command-local flags.
