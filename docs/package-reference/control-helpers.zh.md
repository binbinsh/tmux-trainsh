# 控制 Helper

## 本页说明

控制 helper 用于直接管理 tmux 会话、添加 sleep，以及定义显式 trigger-rule 合流点。

## 典型使用场景

- 在绑定 session API 之外显式打开或关闭 tmux 会话。
- 在分支扇出后创建显式合流点。

## 入口

```python
recipe(...)
```

## 常见用法

```python
open_main = tmux_open("gpu", as_="main")
pause = sleep("30s", after=open_main)
join = on_all_done(after=pause)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `tmux_open` | `tmux_open(target, **kwargs)` | 此页公开的 API helper。 |
| `tmux_close` | `tmux_close(target, **kwargs)` | 此页公开的 API helper。 |
| `tmux_config` | `tmux_config(target, **kwargs)` | 此页公开的 API helper。 |
| `sleep` | `sleep(duration, **kwargs)` | 此页公开的 API helper。 |
| `on_all_done` | `on_all_done(**kwargs)` | 此页公开的 API helper。 |
| `on_all_failed` | `on_all_failed(**kwargs)` | 此页公开的 API helper。 |
| `on_none_failed` | `on_none_failed(**kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `tmux_open`

```python
tmux_open(target, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `tmux_close`

```python
tmux_close(target, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `tmux_config`

```python
tmux_config(target, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `sleep`

```python
sleep(duration, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `duration` | positional_or_keyword | `Any` | `required` |
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

### `on_all_failed`

```python
on_all_failed(**kwargs)
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
