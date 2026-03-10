# Recipe Authoring

## What this page covers

The top-level authoring surface is where recipes start. Use these helpers to declare recipe metadata, variables, host aliases, storage aliases, executor settings, and shared defaults.

## Typical use cases

- Set up variables and infrastructure aliases before adding steps.
- Apply retry, timeout, and trigger defaults that affect many later steps.

## Entry point

```python
recipe(...)
```

## Common usage

```python
from trainsh.pyrecipe import *

recipe("demo", executor="thread_pool", callbacks=["console", "sqlite"])
var("MODEL", "llama-7b")
host("gpu", "user@host")
storage("artifacts", "r2:bucket")
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `recipe` | `recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'` | Create and bind the current recipe for the surrounding module. |
| `defaults` | `defaults(**kwargs: 'Any') -> 'Any'` | Set default task options on the current recipe. |
| `var` | `var(name: 'str', value: 'Any') -> 'None'` | Public helper in this page. |
| `host` | `host(name: 'str', spec: 'Any') -> 'None'` | Public helper in this page. |
| `storage` | `storage(name: 'str', spec: 'Any') -> 'None'` | Public helper in this page. |

## Detailed reference

### `recipe`

```python
recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'
```

Create and bind the current recipe for the surrounding module.

**Parameters**

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

**Returns**

`Any`

### `defaults`

```python
defaults(**kwargs: 'Any') -> 'Any'
```

Set default task options on the current recipe.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `var`

```python
var(name: 'str', value: 'Any') -> 'None'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `value` | positional_or_keyword | `Any` | `required` |

**Returns**

`None`

### `host`

```python
host(name: 'str', spec: 'Any') -> 'None'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `spec` | positional_or_keyword | `Any` | `required` |

**Returns**

`None`

### `storage`

```python
storage(name: 'str', spec: 'Any') -> 'None'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `spec` | positional_or_keyword | `Any` | `required` |

**Returns**

`None`
