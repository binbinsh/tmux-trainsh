# 基础 Provider

## 本页说明

这些 helper 覆盖 shell 命令、Python 片段、通知，以及一些直接的任务原语。

## 典型使用场景

- 无需手写底层 provider 规格就能执行简单的 shell 或 Python 工作。
- 直接从顶层 DSL 调用通知类 helper。

## 入口

```python
recipe(...)
```

## 常见用法

```python
probe = shell("echo ready", id="probe")
notice("workflow started", after=probe)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `shell` | `shell(command, **kwargs)` | 此页公开的 API helper。 |
| `bash` | `bash(command, **kwargs)` | 此页公开的 API helper。 |
| `python` | `python(code_or_command, **kwargs)` | 此页公开的 API helper。 |
| `notice` | `notice(message, **kwargs)` | 此页公开的 API helper。 |
| `fail` | `fail(message='Failed by recipe.', **kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `shell`

```python
shell(command, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `bash`

```python
bash(command, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `python`

```python
python(code_or_command, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `code_or_command` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

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
