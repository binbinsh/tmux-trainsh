# Write your first recipe

This tutorial shows the shortest end-to-end workflow: define a recipe, open a tmux session, run commands, wait for completion, and emit a notification.

## Create a starter file

```bash
train recipes new demo --template minimal
```

## Replace it with a small session-oriented recipe

```python
from trainsh.pyrecipe import *

recipe("demo", callbacks=["console", "sqlite"])
var("MESSAGE", "hello from trainsh")

main = session("main", on="local")
printed = main('echo "$MESSAGE"')
done = main.idle(timeout="30s", after=printed)
notice("$MESSAGE", after=done)
main.close(after=done)
```

## Run it

```bash
train run demo
```

## Inspect it

```bash
train status
train logs
train jobs
```

## What happened

- `recipe(...)` declared the workflow and its top-level metadata
- `session(...)` opened a durable execution context
- `main(...)` added a command step inside that session
- `main.idle(...)` blocked until the session became idle
- `notice(...)` sent a notification through configured channels

## Next

- [Python recipes](../python-recipes.md)
- [Session API](../package-reference/session-api.md)
- [tmux sessions](../concepts/tmux-sessions.md)
