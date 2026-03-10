# Control Helpers

## What this page covers

Control helpers manage tmux sessions directly, add sleeps, and define explicit trigger-rule join points.

## Typical use cases

- Open or close tmux sessions explicitly outside the bound session API.
- Create explicit merge points after branch fan-out.

## Entry point

```python
recipe(...)
```

## Common usage

```python
open_main = tmux_open("gpu", as_="main")
pause = sleep("30s", after=open_main)
join = on_all_done(after=pause)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `tmux_open` | `tmux_open(target, **kwargs)` | Public helper in this page. |
| `tmux_close` | `tmux_close(target, **kwargs)` | Public helper in this page. |
| `tmux_config` | `tmux_config(target, **kwargs)` | Public helper in this page. |
| `sleep` | `sleep(duration, **kwargs)` | Public helper in this page. |
| `on_all_done` | `on_all_done(**kwargs)` | Public helper in this page. |
| `on_all_failed` | `on_all_failed(**kwargs)` | Public helper in this page. |
| `on_none_failed` | `on_none_failed(**kwargs)` | Public helper in this page. |

## Detailed reference

### `tmux_open`

```python
tmux_open(target, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `tmux_close`

```python
tmux_close(target, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `tmux_config`

```python
tmux_config(target, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `sleep`

```python
sleep(duration, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `duration` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `on_all_done`

```python
on_all_done(**kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `on_all_failed`

```python
on_all_failed(**kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `on_none_failed`

```python
on_none_failed(**kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`
