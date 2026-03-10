# 运行远端 GPU 训练

这个教程展示最常见的远端模式：准备主机、打开 tmux 会话、运行长时间训练命令，并把输出同步回来。

## 1. 添加主机

```bash
train host add
train host test gpu
```

## 2. 编写 recipe

```python
from trainsh.pyrecipe import *

recipe("remote-train", executor="thread_pool", callbacks=["console", "sqlite"])
host("gpu", "your-host")
var("WORKDIR", "/workspace/project")
var("LOCAL_OUT", "./artifacts")

ready = host_test("gpu")
main = session("main", on="gpu", after=ready)
clone = main("git clone https://github.com/example/project.git $WORKDIR || (cd $WORKDIR && git pull)")
train = main.bg("cd $WORKDIR && python train.py 2>&1 | tee train.log", after=clone)
done = main.wait("training finished", timeout="8h", after=train)
pull = transfer("@gpu:$WORKDIR", "$LOCAL_OUT", after=done)
main.close(after=pull)
```

## 3. 运行并查看

```bash
train run remote-train
train status
train logs
```

## 4. 常见升级方式

- 用 `vast_pick(...)` 和 `vast_wait(...)` 替代固定主机
- 用 `storage_upload(...)` 上传 checkpoint
- 用 `http_wait(...)` 把健康检查作为启动前置条件

## 相关页面

- [主机与存储](../guides/hosts-and-storage.md)
- [Transfer](../package-reference/transfer.md)
- [Storage](../package-reference/storage.md)
