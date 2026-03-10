# Session API

## 本页说明

绑定后的 session 对象会把后续步骤附着到同一个 tmux 会话上，这是表达长时间远端任务的核心 API。

## 典型使用场景

- 用统一的 session 风格表达长时间训练流程。
- 在不离开 tmux 语义的前提下等待空闲、输出文本、文件或端口。

## 入口

```python
main = session("main", on="gpu")
```

## 常见用法

```python
main = session("main", on="gpu")
clone = main("git clone https://github.com/example/project.git /workspace/project")
train = main.bg("cd /workspace/project && python train.py", after=clone)
done = main.idle(timeout="2h", after=train)
main.close(after=done)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `session` | `session(name: 'str', *, on: 'Optional[str]' = None, after: 'Any' = None, id: 'Optional[str]' = None, **kwargs: 'Any') -> 'Session'` | Open or bind a session using the flat authoring syntax. |
| `close` | `close(target: 'Session', **kwargs: 'Any') -> 'str'` | Close a previously declared session. |
| `bg` | `bg(command: 'str', **kwargs: 'Any') -> 'str'` | Compact alias for a background command. |
| `wait` | `wait(pattern: 'Optional[str]' = None, *, file: 'Optional[str]' = None, port: 'Optional[int]' = None, idle: 'bool' = False, timeout: 'Any' = '5m', id: 'Optional[str]' = None, after: 'Any' = None, **kwargs: 'Any') -> 'str'` | Wait on this session using tmux-session semantics. |
| `idle` | `idle(**kwargs: 'Any') -> 'str'` | Compact alias for idle waits. |
| `file` | `file(path: 'str', **kwargs: 'Any') -> 'str'` | Compact alias for file waits. |
| `port` | `port(value: 'int', **kwargs: 'Any') -> 'str'` | Compact alias for port waits. |

## 详细参考

### `session`

```python
session(name: 'str', *, on: 'Optional[str]' = None, after: 'Any' = None, id: 'Optional[str]' = None, **kwargs: 'Any') -> 'Session'
```

Open or bind a session using the flat authoring syntax.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `on` | keyword_only | `Optional[str]` | `None` |
| `after` | keyword_only | `Any` | `None` |
| `id` | keyword_only | `Optional[str]` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Session`

### `close`

```python
close(target: 'Session', **kwargs: 'Any') -> 'str'
```

Close a previously declared session.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Session` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `bg`

```python
bg(command: 'str', **kwargs: 'Any') -> 'str'
```

Compact alias for a background command.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `wait`

```python
wait(pattern: 'Optional[str]' = None, *, file: 'Optional[str]' = None, port: 'Optional[int]' = None, idle: 'bool' = False, timeout: 'Any' = '5m', id: 'Optional[str]' = None, after: 'Any' = None, **kwargs: 'Any') -> 'str'
```

Wait on this session using tmux-session semantics.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `pattern` | positional_or_keyword | `Optional[str]` | `None` |
| `file` | keyword_only | `Optional[str]` | `None` |
| `port` | keyword_only | `Optional[int]` | `None` |
| `idle` | keyword_only | `bool` | `False` |
| `timeout` | keyword_only | `Any` | `'5m'` |
| `id` | keyword_only | `Optional[str]` | `None` |
| `after` | keyword_only | `Any` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `idle`

```python
idle(**kwargs: 'Any') -> 'str'
```

Compact alias for idle waits.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `file`

```python
file(path: 'str', **kwargs: 'Any') -> 'str'
```

Compact alias for file waits.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `path` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `port`

```python
port(value: 'int', **kwargs: 'Any') -> 'str'
```

Compact alias for port waits.

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `value` | positional_or_keyword | `int` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`
