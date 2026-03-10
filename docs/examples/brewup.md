# brewup.py

Upgrade Homebrew packages and casks on macOS.

## Recipe name

```text
brewup
```

## Show this example

```bash
train recipes show brewup
```

## Run this example

```bash
train run brewup
```

## Source

```python
from trainsh.pyrecipe import *

recipe("brewup", callbacks=["console", "sqlite"])

update = session("update", on="local")
refresh = update("brew update")
upgrade = update("brew upgrade", after=refresh)
casks = update("brew upgrade --greedy --cask $(brew list --cask)", after=upgrade)
cleanup = update("brew cleanup", after=casks)
noticed = notice("brew upgrade complete!", after=cleanup)
update.close(after=noticed)
```
