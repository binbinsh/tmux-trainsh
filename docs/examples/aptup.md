# aptup.py

Update a Debian or Ubuntu machine through a managed tmux session.

## Recipe name

```text
aptup
```

## Show this example

```bash
train recipes show aptup
```

## Run this example

```bash
train run aptup
```

## Source

```python
from trainsh.pyrecipe import *

recipe("aptup", callbacks=["console", "sqlite"])

update = session("update", on="local")
refresh = update("sudo apt update")
upgrade = update("sudo apt -y dist-upgrade", after=refresh)
cleanup = update("sudo apt -y autoremove", after=upgrade)
noticed = notice("apt upgrade complete!", after=cleanup)
update.close(after=noticed)
```
