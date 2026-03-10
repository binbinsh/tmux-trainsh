# Notifications and Misc

## What this page covers

Misc helpers cover explicit failure steps, webhook-style notifications, and XCom push/pull operations.

## Typical use cases

- Emit notifications to external systems at key workflow events.
- Fail a branch intentionally or pass a small computed value forward.

## Entry point

```python
recipe(...)
```

## Common usage

```python
push = xcom_push("train_loss", value="0.42")
notice("training finished", after=push)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `notice` | `notice(message, **kwargs)` | Public helper in this page. |
| `slack` | `slack(message, **kwargs)` | Public helper in this page. |
| `telegram` | `telegram(message, **kwargs)` | Public helper in this page. |
| `discord` | `discord(message, **kwargs)` | Public helper in this page. |
| `email_send` | `email_send(message, **kwargs)` | Public helper in this page. |
| `webhook` | `webhook(message, **kwargs)` | Public helper in this page. |
| `fail` | `fail(message='Failed by recipe.', **kwargs)` | Public helper in this page. |

## Detailed reference

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

### `slack`

```python
slack(message, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `telegram`

```python
telegram(message, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `discord`

```python
discord(message, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `email_send`

```python
email_send(message, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `webhook`

```python
webhook(message, **kwargs)
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
