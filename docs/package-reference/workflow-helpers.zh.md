# 工作流 Helper

## 本页说明

工作流 helper 覆盖 Git 操作、主机探测、SSH 命令、变量捕获，以及轻量级的 HTTP 或文件等待。

## 典型使用场景

- 在 tmux 会话开始前准备远端工作目录。
- 把文件、端口或 HTTP 端点探测作为编排的一部分。

## 入口

```python
recipe(...)
```

## 常见用法

```python
ready = host_test("gpu")
clone = git_clone("https://github.com/example/project.git", "/workspace/project", after=ready)
port = wait_for_port(8000, host="gpu", after=clone)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `host_test` | `host_test(target, **kwargs)` | 此页公开的 API helper。 |
| `git_clone` | `git_clone(repo_url, destination=None, **kwargs)` | 此页公开的 API helper。 |
| `git_pull` | `git_pull(directory='.', **kwargs)` | 此页公开的 API helper。 |
| `wait_file` | `wait_file(path, **kwargs)` | 此页公开的 API helper。 |
| `wait_for_port` | `wait_for_port(port, **kwargs)` | 此页公开的 API helper。 |
| `set_env` | `set_env(name, value, **kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `host_test`

```python
host_test(target, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `git_clone`

```python
git_clone(repo_url, destination=None, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `repo_url` | positional_or_keyword | `Any` | `required` |
| `destination` | positional_or_keyword | `Any` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `git_pull`

```python
git_pull(directory='.', **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `directory` | positional_or_keyword | `Any` | `'.'` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `wait_file`

```python
wait_file(path, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `path` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `wait_for_port`

```python
wait_for_port(port, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `port` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `set_env`

```python
set_env(name, value, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `name` | positional_or_keyword | `Any` | `required` |
| `value` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`
