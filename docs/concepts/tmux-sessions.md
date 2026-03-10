# tmux sessions

`trainsh` uses tmux as the durable execution substrate for long-running commands.

## Why tmux is central

tmux gives you:

- long-lived shell state
- pane output that can be waited on
- reconnection after terminal disconnects
- a natural place for training jobs to run

## Session-oriented API

The main API is:

```python
main = session("main", on="gpu")
main(...)
main.bg(...)
main.idle(...)
main.wait(...)
main.close(...)
```

This style is the Python replacement for the old session-oriented DSL.

## Related pages

- [Session API](../package-reference/session-api.md)
- [Write your first recipe](../tutorials/first-recipe.md)
