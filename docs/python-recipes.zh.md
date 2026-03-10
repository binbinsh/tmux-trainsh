# Python recipes

`tmux-trainsh` 的 recipe 以 Python 模块形式编写。

这页是编写指南。若要查精确的方法签名和参数表，请直接查看 [package reference](package-reference/_index.md)。

## 公开 API

用户侧 recipe 仍然使用：

```python
from trainsh.pyrecipe import *
```

`recipe(...)` 会为当前模块绑定活动 recipe，后续用 `var(...)`、`session(...)`、`sql_query(...)` 之类的顶层 helper 继续编写。`load_python_recipe(path)` 用于加载一个 `.py` recipe 文件并返回对应对象。

## 最小示例

```python
from trainsh.pyrecipe import *

recipe(
    "example",
    schedule="@every 30m",
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

var("MODEL", "llama-7b")
host("gpu", "your-server")

ready = latest_only(fail_if_unknown=False, id="latest_only")
main = session("main", on="gpu", after=ready)
clone = main(
    "cd /tmp && git clone https://github.com/example/project.git project",
)
train = main.bg(
    "cd /tmp/project && python train.py --model $MODEL",
    after=clone,
)
main.wait("training finished", timeout="2h", after=train)
main.idle(timeout="2h", after=train)
storage_wait(
    "artifacts",
    "/models/$MODEL/done.txt",
    after=train,
)
notice("Training finished", after=train)
```

## 运行时能力

Python 运行时支持：

- 通过 `after=...` 进行依赖调度
- `sequential`、`thread_pool`、`process_pool`、`local`、`airflow`、`celery`、`dask`、`debug` 等执行器别名
- 面向 tmux/session 的 helper：`session`、`main(...)`、`main.bg(...)`、`main.idle(...)`、`main.wait(...)`、`main.file(...)`、`main.port(...)`
- 类 Airflow 的 step 选项：`retries`、`retry_delay`、`execution_timeout`、`retry_exponential_backoff`、`trigger_rule`、pools、callbacks
- 控制流 helper：`latest_only`、`choose`、`short_circuit`、`skip_if`、`skip_if_not`、`join`
- 存储 helper：`storage_wait`、`storage_upload`、`storage_download`、`storage_copy`、`storage_move`、`storage_sync`、`storage_remove`
- SQLite helper：`sql_query`、`sql_exec`、`sql_script`
- 类 XCom helper：`xcom_push`、`xcom_pull`

## 建议连着阅读的页面

- [编写第一个 recipe](tutorials/first-recipe.md)
- [tmux 会话](concepts/tmux-sessions.md)
- [Recipe authoring reference](package-reference/recipe-builder.md)
- [Session API reference](package-reference/session-api.md)

## 调度

调度元数据通常直接写在 `recipe(...)` 中：

```python
recipe("nightly-train", schedule="@every 15m", owner="ml", tags=["train", "nightly"])
```
