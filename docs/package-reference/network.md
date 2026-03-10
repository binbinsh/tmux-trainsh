# HTTP and Network

## What this page covers

HTTP helpers cover direct request aliases, JSON helpers, and polling-style sensors for service health checks.

## Typical use cases

- Gate workflows on a health endpoint or service warm-up check.
- Capture HTTP responses into variables for later steps.

## Entry point

```python
recipe(...)
```

## Common usage

```python
health = http_wait(
    "https://example.com/health",
    status=200,
    timeout="2m",
    every="5s",
)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `http_get` | `http_get(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_post` | `http_post(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_put` | `http_put(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_delete` | `http_delete(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_head` | `http_head(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_request` | `http_request(method: 'str', url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `http_wait` | `http_wait(url: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |

## Detailed reference

### `http_get`

```python
http_get(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_post`

```python
http_post(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_put`

```python
http_put(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_delete`

```python
http_delete(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_head`

```python
http_head(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_request`

```python
http_request(method: 'str', url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `method` | positional_or_keyword | `str` | `required` |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `http_wait`

```python
http_wait(url: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`
