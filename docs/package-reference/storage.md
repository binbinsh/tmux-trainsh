# Storage

## What this page covers

Storage helpers upload, download, copy, move, sync, inspect, and wait on storage-backed paths.

## Typical use cases

- Publish artifacts to object storage.
- Poll for an object or key produced by another system.

## Entry point

```python
recipe(...)
```

## Common usage

```python
upload = storage_upload("./artifacts", "artifacts:/runs/$RUN_NAME")
wait = storage_wait("artifacts", "/runs/$RUN_NAME/done.txt", after=upload)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `storage_upload` | `storage_upload(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_download` | `storage_download(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_wait` | `storage_wait(storage_ref: 'str', path: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_copy` | `storage_copy(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_move` | `storage_move(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_sync` | `storage_sync(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `storage_remove` | `storage_remove(target: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |

## Detailed reference

### `storage_upload`

```python
storage_upload(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_download`

```python
storage_download(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_wait`

```python
storage_wait(storage_ref: 'str', path: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `storage_ref` | positional_or_keyword | `str` | `required` |
| `path` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_copy`

```python
storage_copy(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_move`

```python
storage_move(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_sync`

```python
storage_sync(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `storage_remove`

```python
storage_remove(target: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`
