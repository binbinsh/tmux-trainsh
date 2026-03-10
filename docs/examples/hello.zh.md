# hello.py

最小化的本地 tmux 会话和通知流程。

## Recipe 名称

```text
hello-world
```

## 查看这个示例

```bash
train recipes show hello
```

## 运行这个示例

```bash
train run hello-world
```

## 源码

```python
from trainsh.pyrecipe import *

recipe("hello-world", callbacks=["console", "sqlite"])
var("MESSAGE", "Hello from trainsh")

hello = session("hello", on="local")
printed = hello('echo "$MESSAGE"')
noticed = notice("$MESSAGE", after=printed)
hello.close(after=noticed)
```
