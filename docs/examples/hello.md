# hello.py

Minimal local tmux session and notification flow.

## Recipe name

```text
hello-world
```

## Show this example

```bash
train recipes show hello
```

## Run this example

```bash
train run hello-world
```

## Source

```python
from trainsh.pyrecipe import *

recipe("hello-world", callbacks=["console", "sqlite"])
var("MESSAGE", "Hello from trainsh")

hello = session("hello", on="local")
printed = hello('echo "$MESSAGE"')
noticed = notice("$MESSAGE", after=printed)
hello.close(after=noticed)
```
