# brewup.py

在 macOS 上升级 Homebrew 包和 cask。

## Recipe 名称

```text
brewup
```

## 查看这个示例

```bash
train recipes show brewup
```

## 运行这个示例

```bash
train run brewup
```

## 源码

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
