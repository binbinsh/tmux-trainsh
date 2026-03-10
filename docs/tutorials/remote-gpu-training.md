# Run remote GPU training

This tutorial shows the typical remote pattern: prepare a host, open a tmux session, run a long training command, and copy outputs back.

## 1. Add a host

```bash
train host add
train host test gpu
```

## 2. Create the recipe

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

## 3. Run and inspect

```bash
train run remote-train
train status
train logs
```

## 4. Common upgrades

- Replace the static host with `vast_pick(...)` and `vast_wait(...)`
- Upload checkpoints with `storage_upload(...)`
- Gate startup on a health check with `http_wait(...)`

## Related pages

- [Hosts and storage](../guides/hosts-and-storage.md)
- [Transfer](../package-reference/transfer.md)
- [Storage](../package-reference/storage.md)
