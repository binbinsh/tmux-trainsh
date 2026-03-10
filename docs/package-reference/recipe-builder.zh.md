# Recipe 编写

## 本页说明

顶层 authoring 语法是 recipe 的起点，用来声明工作流元数据、变量、主机别名、存储别名、执行器设置，以及共享默认项。

## 典型使用场景

- 在添加步骤前先配置变量、主机和存储别名。
- 为后续步骤统一设置重试、超时和触发规则默认值。

## 入口

```python
recipe(...)
```

## 常见用法

```python
from trainsh.pyrecipe import *

recipe("demo", executor="thread_pool", callbacks=["console", "sqlite"])
var("MODEL", "llama-7b")
host("gpu", "user@host")
storage("artifacts", "r2:bucket")
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `recipe` | `recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'` | Create and bind the current recipe for the surrounding module. |
| `defaults` | `defaults(**kwargs: 'Any') -> 'Any'` | Set default task options on the current recipe. |
| `var` | `var(name: 'str', value: 'Any') -> 'None'` | 此页公开的 API helper。 |
| `host` | `host(name: 'str', spec: 'Any') -> 'None'` | 此页公开的 API helper。 |
| `storage` | `storage(name: 'str', spec: 'Any') -> 'None'` | 此页公开的 API helper。 |

## 详细参考

### `recipe`

```python
recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'
```

Create and bind the current recipe for the surrounding module.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `schedule` | keyword_only | `Optional[str]` | `None` |
| `owner` | keyword_only | `Optional[str]` | `None` |
| `tags` | keyword_only | `Optional[Iterable[str]]` | `None` |
| `paused` | keyword_only | `Optional[bool]` | `None` |
| `catchup` | keyword_only | `Optional[bool]` | `None` |
| `max_active_runs` | keyword_only | `Optional[int]` | `None` |
| `executor` | keyword_only | `str` | `'sequential'` |
| `executor_kwargs` | keyword_only | `Optional[Dict[str, Any]]` | `None` |
| `workers` | keyword_only | `Optional[int]` | `None` |
| `callbacks` | keyword_only | `Optional[list[str]]` | `None` |
| `extra_executor_kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `defaults`

```python
defaults(**kwargs: 'Any') -> 'Any'
```

Set default task options on the current recipe.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `var`

```python
var(name: 'str', value: 'Any') -> 'None'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `value` | positional_or_keyword | `Any` | `required` |

**返回值**

`None`

### `host`

```python
host(name: 'str', spec: 'Any') -> 'None'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `spec` | positional_or_keyword | `Any` | `required` |

**返回值**

`None`

### `storage`

```python
storage(name: 'str', spec: 'Any') -> 'None'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `spec` | positional_or_keyword | `Any` | `required` |

**返回值**

`None`
