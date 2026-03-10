# Basic Providers

## What this page covers

These helpers cover shell commands, Python snippets, notifications, and a few direct task primitives.

## Typical use cases

- Run simple shell or Python work without dropping to low-level provider specs.
- Emit notifications directly from the top-level DSL.

## Entry point

```python
recipe(...)
```

## Common usage

```python
probe = shell("echo ready", id="probe")
notice("workflow started", after=probe)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `shell` | `shell(command, **kwargs)` | Public helper in this page. |
| `bash` | `bash(command, **kwargs)` | Public helper in this page. |
| `python` | `python(code_or_command, **kwargs)` | Public helper in this page. |
| `notice` | `notice(message, **kwargs)` | Public helper in this page. |
| `fail` | `fail(message='Failed by recipe.', **kwargs)` | Public helper in this page. |

## Detailed reference

### `shell`

```python
shell(command, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `bash`

```python
bash(command, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `python`

```python
python(code_or_command, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `code_or_command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `notice`

```python
notice(message, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `fail`

```python
fail(message='Failed by recipe.', **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `'Failed by recipe.'` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`
