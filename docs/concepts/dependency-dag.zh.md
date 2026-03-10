# 依赖 DAG

每个 Python recipe 最终都会被编译成规范化 DAG。

## 基本单位

每次 helper 调用都会新增一个 step，依赖关系用 `after=...` 表达。

```python
clone = main("git clone ...")
train = main.bg("python train.py", after=clone)
done = main.idle(after=train)
```

## 为什么重要

DAG 模型支撑了这些能力：

- 基于执行器的调度
- 重试和超时
- trigger rule
- 分支与合流
- 运行时元数据持久化

## 顺序执行与并行执行

即使是 `sequential`，也仍然遵循依赖语义。本质上它只是把 worker 数限制为 1 的依赖调度。

## 相关页面

- [执行器与调度](executors.md)
- [分支与控制流指南](../guides/branching-and-control-flow.md)
