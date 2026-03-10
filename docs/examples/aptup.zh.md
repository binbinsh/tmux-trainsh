# aptup.py

通过受管 tmux 会话更新 Debian 或 Ubuntu 主机。

## Recipe 名称

```text
aptup
```

## 查看这个示例

```bash
train recipes show aptup
```

## 运行这个示例

```bash
train run aptup
```

## 源码

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
