# Transfer

## What this page covers

Transfer helpers move files or directories between local paths, remote hosts, and storage endpoints.

## Typical use cases

- Pull model outputs from a GPU host.
- Sync checkpoints between local and cloud storage.

## Entry point

```python
recipe(...)
```

## Common usage

```python
copy = transfer("@gpu:/workspace/output", "./output")
mirror = transfer("./checkpoints", "artifacts:/checkpoints", operation="sync")
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `transfer` | `transfer(source, destination, **kwargs)` | Public helper in this page. |

## Detailed reference

### `transfer`

```python
transfer(source, destination, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `Any` | `required` |
| `destination` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`
