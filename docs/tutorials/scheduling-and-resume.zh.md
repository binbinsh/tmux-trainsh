# 调度与恢复运行

这个教程覆盖两个不同问题：

- 如何按计划运行 recipe
- 如何在中断后用 `resume` 继续执行

## 添加调度元数据

直接在 `recipe(...)` 中声明元数据：

```python
recipe("nightly-train", schedule="@every 30m", owner="ml", tags=["nightly", "train"])
```

## 查看调度

```bash
train schedule list
train schedule status
```

## 运行调度器

```bash
train schedule run --once
train schedule run --forever
```

## 恢复运行

```bash
train resume my-recipe
train resume my-recipe --var MODEL=llama-70b
```

`resume` 会恢复已保存的运行时状态、主机解析和 tmux session 映射；它有意不支持 host override。

## 何时使用 `latest_only`

定时 recipe 通常建议加上：

```python
latest_only(fail_if_unknown=False)
```

这样当新的调度运行已经存在时，旧运行就不会重复做无效工作。

## 相关页面

- [执行器与调度](../concepts/executors.md)
- [运行时元数据](../concepts/runtime-metadata.md)
- [Control flow](../package-reference/control-flow.md)
