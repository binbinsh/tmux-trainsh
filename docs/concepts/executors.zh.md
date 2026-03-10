# 执行器与调度

执行器决定 recipe 被加载后，DAG 以什么方式调度运行。

## 支持的执行器名称

Python 运行时支持这些别名：

- `sequential`
- `thread_pool`
- `process_pool`
- `local`
- `airflow`
- `celery`
- `dask`
- `debug`

Kubernetes 被明确标记为不支持。

## 行为方式

- `sequential` 依然遵守 DAG，只是把并发度限制为 1
- 线程池风格执行器支持基于依赖的并行
- pools 可以对特定类别的工作做限流

## 在哪里设置

```python
recipe(
    "demo",
    executor="thread_pool",
    workers=4,
)
```

## 相关页面

- [依赖 DAG](dependency-dag.md)
- [Recipe authoring](../package-reference/recipe-builder.md)
