# 通知与杂项

## 本页说明

杂项 helper 覆盖显式失败步骤、Webhook 风格通知，以及 XCom push/pull 操作。

## 典型使用场景

- 在关键工作流事件上向外部系统发送通知。
- 显式让某个分支失败，或向后续步骤传递小型计算值。

## 入口

```python
recipe(...)
```

## 常见用法

```python
push = xcom_push("train_loss", value="0.42")
notice("training finished", after=push)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `notice` | `notice(message, **kwargs)` | 此页公开的 API helper。 |
| `slack` | `slack(message, **kwargs)` | 此页公开的 API helper。 |
| `telegram` | `telegram(message, **kwargs)` | 此页公开的 API helper。 |
| `discord` | `discord(message, **kwargs)` | 此页公开的 API helper。 |
| `email_send` | `email_send(message, **kwargs)` | 此页公开的 API helper。 |
| `webhook` | `webhook(message, **kwargs)` | 此页公开的 API helper。 |
| `fail` | `fail(message='Failed by recipe.', **kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `notice`

```python
notice(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `slack`

```python
slack(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `telegram`

```python
telegram(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `discord`

```python
discord(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `email_send`

```python
email_send(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `webhook`

```python
webhook(message, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `fail`

```python
fail(message='Failed by recipe.', **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `message` | positional_or_keyword | `Any` | `'Failed by recipe.'` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`
