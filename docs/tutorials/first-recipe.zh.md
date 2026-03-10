# 编写第一个 recipe

这个教程展示最短的一条端到端路径：定义 recipe、打开 tmux 会话、执行命令、等待完成并发送通知。

## 创建起始文件

```bash
train recipes new demo --template minimal
```

## 替换成一个小型 session 风格 recipe

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

## 运行

```bash
train run demo
```

## 查看

```bash
train status
train logs
train jobs
```

## 发生了什么

- `recipe(...)` 声明了工作流和顶层元数据
- `session(...)` 打开了一个可恢复的执行上下文
- `main(...)` 在该 session 内添加了命令步骤
- `main.idle(...)` 会阻塞到 session 进入空闲
- `notice(...)` 会通过配置好的渠道发送通知

## 下一步

- [Python recipes](../python-recipes.md)
- [Session API](../package-reference/session-api.md)
- [tmux 会话](../concepts/tmux-sessions.md)
