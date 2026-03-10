# Workflow Helpers

## What this page covers

Workflow helpers cover Git actions, host probes, SSH commands, value capture, and lightweight HTTP or file waits.

## Typical use cases

- Prepare remote workspaces before tmux sessions start.
- Probe files, ports, or HTTP endpoints as part of orchestration.

## Entry point

```python
recipe(...)
```

## Common usage

```python
ready = host_test("gpu")
clone = git_clone("https://github.com/example/project.git", "/workspace/project", after=ready)
port = wait_for_port(8000, host="gpu", after=clone)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `host_test` | `host_test(target, **kwargs)` | Public helper in this page. |
| `git_clone` | `git_clone(repo_url, destination=None, **kwargs)` | Public helper in this page. |
| `git_pull` | `git_pull(directory='.', **kwargs)` | Public helper in this page. |
| `wait_file` | `wait_file(path, **kwargs)` | Public helper in this page. |
| `wait_for_port` | `wait_for_port(port, **kwargs)` | Public helper in this page. |
| `set_env` | `set_env(name, value, **kwargs)` | Public helper in this page. |

## Detailed reference

### `host_test`

```python
host_test(target, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `git_clone`

```python
git_clone(repo_url, destination=None, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `repo_url` | positional_or_keyword | `Any` | `required` |
| `destination` | positional_or_keyword | `Any` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `git_pull`

```python
git_pull(directory='.', **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `directory` | positional_or_keyword | `Any` | `'.'` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `wait_file`

```python
wait_file(path, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `path` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `wait_for_port`

```python
wait_for_port(port, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `port` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `set_env`

```python
set_env(name, value, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `Any` | `required` |
| `value` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`
