# Control Flow

## What this page covers

Control-flow helpers implement latest-only behavior, branching, short-circuit checks, and condition waits.

## Typical use cases

- Skip stale runs when a newer scheduled run exists.
- Build DAG branches that later merge with explicit trigger rules.

## Entry point

```python
recipe(...)
```

## Common usage

```python
latest = latest_only(fail_if_unknown=False)
branch = choose("PATH_KIND", when='MODE == "prod"', then="prod", else_="dev", after=latest)
join(after=branch)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `latest_only` | `latest_only(**kwargs)` | Public helper in this page. |
| `choose` | `choose(variable: 'str', *, when: 'str', then: 'Any' = 'true', else_: 'Any' = 'false', host: 'Optional[str]' = None, **kwargs: 'Any') -> 'str'` | Write one variable based on a condition. |
| `short_circuit` | `short_circuit(condition, **kwargs)` | Public helper in this page. |
| `skip_if` | `skip_if(condition, **kwargs)` | Public helper in this page. |
| `skip_if_not` | `skip_if_not(condition, **kwargs)` | Public helper in this page. |
| `join` | `join(**kwargs)` | Public helper in this page. |
| `on_all_done` | `on_all_done(**kwargs)` | Public helper in this page. |
| `on_all_success` | `on_all_success(**kwargs)` | Public helper in this page. |
| `on_none_failed` | `on_none_failed(**kwargs)` | Public helper in this page. |

## Detailed reference

### `latest_only`

```python
latest_only(**kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `choose`

```python
choose(variable: 'str', *, when: 'str', then: 'Any' = 'true', else_: 'Any' = 'false', host: 'Optional[str]' = None, **kwargs: 'Any') -> 'str'
```

Write one variable based on a condition.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `variable` | positional_or_keyword | `str` | `required` |
| `when` | keyword_only | `str` | `required` |
| `then` | keyword_only | `Any` | `'true'` |
| `else_` | keyword_only | `Any` | `'false'` |
| `host` | keyword_only | `Optional[str]` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `short_circuit`

```python
short_circuit(condition, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `skip_if`

```python
skip_if(condition, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `skip_if_not`

```python
skip_if_not(condition, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `condition` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `join`

```python
join(**kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
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

### `on_all_success`

```python
on_all_success(**kwargs)
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
