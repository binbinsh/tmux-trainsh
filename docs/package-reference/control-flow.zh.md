# 控制流

## 本页说明

控制流 helper 实现 latest-only、分支、短路判断和条件等待等能力。

## 典型使用场景

- 在存在更新调度运行时跳过过期运行。
- 构建 DAG 分支，并在后续用显式 trigger rule 合流。

## 入口

```python
recipe(...)
```

## 常见用法

```python
latest = latest_only(fail_if_unknown=False)
branch = choose("PATH_KIND", when='MODE == "prod"', then="prod", else_="dev", after=latest)
join(after=branch)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `latest_only` | `latest_only(**kwargs)` | 此页公开的 API helper。 |
| `choose` | `choose(variable: 'str', *, when: 'str', then: 'Any' = 'true', else_: 'Any' = 'false', host: 'Optional[str]' = None, **kwargs: 'Any') -> 'str'` | Write one variable based on a condition. |
| `short_circuit` | `short_circuit(condition, **kwargs)` | 此页公开的 API helper。 |
| `skip_if` | `skip_if(condition, **kwargs)` | 此页公开的 API helper。 |
| `skip_if_not` | `skip_if_not(condition, **kwargs)` | 此页公开的 API helper。 |
| `join` | `join(**kwargs)` | 此页公开的 API helper。 |
| `on_all_done` | `on_all_done(**kwargs)` | 此页公开的 API helper。 |
| `on_all_success` | `on_all_success(**kwargs)` | 此页公开的 API helper。 |
| `on_none_failed` | `on_none_failed(**kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `latest_only`

```python
latest_only(**kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `choose`

```python
choose(variable: 'str', *, when: 'str', then: 'Any' = 'true', else_: 'Any' = 'false', host: 'Optional[str]' = None, **kwargs: 'Any') -> 'str'
```

Write one variable based on a condition.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `variable` | positional_or_keyword | `str` | `required` |
| `when` | keyword_only | `str` | `required` |
| `then` | keyword_only | `Any` | `'true'` |
| `else_` | keyword_only | `Any` | `'false'` |
| `host` | keyword_only | `Optional[str]` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `short_circuit`

```python
short_circuit(condition, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `skip_if`

```python
skip_if(condition, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `skip_if_not`

```python
skip_if_not(condition, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `join`

```python
join(**kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `on_all_done`

```python
on_all_done(**kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `on_all_success`

```python
on_all_success(**kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `on_none_failed`

```python
on_none_failed(**kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`
