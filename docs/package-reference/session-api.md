# Session API

## What this page covers

A bound session object keeps follow-up steps attached to one tmux session. This is the main API for long-running remote work.

## Typical use cases

- Express long-lived training flows in a single session-oriented style.
- Wait on pane idleness, output text, files, or ports without leaving tmux semantics.

## Entry point

```python
main = session("main", on="gpu")
```

## Common usage

```python
main = session("main", on="gpu")
clone = main("git clone https://github.com/example/project.git /workspace/project")
train = main.bg("cd /workspace/project && python train.py", after=clone)
done = main.idle(timeout="2h", after=train)
main.close(after=done)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `session` | `session(name: 'str', *, on: 'Optional[str]' = None, after: 'Any' = None, id: 'Optional[str]' = None, **kwargs: 'Any') -> 'Session'` | Open or bind a session using the flat authoring syntax. |
| `close` | `close(target: 'Session', **kwargs: 'Any') -> 'str'` | Close a previously declared session. |
| `bg` | `bg(command: 'str', **kwargs: 'Any') -> 'str'` | Compact alias for a background command. |
| `wait` | `wait(pattern: 'Optional[str]' = None, *, file: 'Optional[str]' = None, port: 'Optional[int]' = None, idle: 'bool' = False, timeout: 'Any' = '5m', id: 'Optional[str]' = None, after: 'Any' = None, **kwargs: 'Any') -> 'str'` | Wait on this session using tmux-session semantics. |
| `idle` | `idle(**kwargs: 'Any') -> 'str'` | Compact alias for idle waits. |
| `file` | `file(path: 'str', **kwargs: 'Any') -> 'str'` | Compact alias for file waits. |
| `port` | `port(value: 'int', **kwargs: 'Any') -> 'str'` | Compact alias for port waits. |

## Detailed reference

### `session`

```python
session(name: 'str', *, on: 'Optional[str]' = None, after: 'Any' = None, id: 'Optional[str]' = None, **kwargs: 'Any') -> 'Session'
```

Open or bind a session using the flat authoring syntax.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `str` | `required` |
| `on` | keyword_only | `Optional[str]` | `None` |
| `after` | keyword_only | `Any` | `None` |
| `id` | keyword_only | `Optional[str]` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Session`

### `close`

```python
close(target: 'Session', **kwargs: 'Any') -> 'str'
```

Close a previously declared session.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Session` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `bg`

```python
bg(command: 'str', **kwargs: 'Any') -> 'str'
```

Compact alias for a background command.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `command` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `wait`

```python
wait(pattern: 'Optional[str]' = None, *, file: 'Optional[str]' = None, port: 'Optional[int]' = None, idle: 'bool' = False, timeout: 'Any' = '5m', id: 'Optional[str]' = None, after: 'Any' = None, **kwargs: 'Any') -> 'str'
```

Wait on this session using tmux-session semantics.

**Parameters**

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

**Returns**

`str`

### `idle`

```python
idle(**kwargs: 'Any') -> 'str'
```

Compact alias for idle waits.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `file`

```python
file(path: 'str', **kwargs: 'Any') -> 'str'
```

Compact alias for file waits.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `path` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `port`

```python
port(value: 'int', **kwargs: 'Any') -> 'str'
```

Compact alias for port waits.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `value` | positional_or_keyword | `int` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`
