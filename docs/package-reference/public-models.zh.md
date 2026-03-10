# 公共模型与入口

这些对象会出现在面向用户的导入路径和运行时集成中。

## 概览

| 对象 | 签名 | 角色 |
| --- | --- | --- |
| `recipe` | `recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'` | 为单个 `.py` recipe 文件绑定当前活动 recipe 的顶层声明函数。 |
| `load_python_recipe` | `load_python_recipe(path: 'str') -> 'Any'` | 加载一个 `.py` recipe 文件并返回其绑定后的 recipe 对象。 |

## 详情

## `recipe`

为单个 `.py` recipe 文件绑定当前活动 recipe 的顶层声明函数。

```python
recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'
```

## `load_python_recipe`

加载一个 `.py` recipe 文件并返回其绑定后的 recipe 对象。

```python
load_python_recipe(path: 'str') -> 'Any'
```
