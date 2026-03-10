# HTTP 与网络

## 本页说明

HTTP helper 覆盖直接请求别名、JSON helper，以及用于健康检查的轮询式 sensor。

## 典型使用场景

- 通过健康检查端点或服务预热检查来控制工作流启动。
- 把 HTTP 响应捕获到变量中供后续步骤使用。

## 入口

```python
recipe(...)
```

## 常见用法

```python
health = http_wait(
    "https://example.com/health",
    status=200,
    timeout="2m",
    every="5s",
)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `http_get` | `http_get(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_post` | `http_post(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_put` | `http_put(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_delete` | `http_delete(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_head` | `http_head(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_request` | `http_request(method: 'str', url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `http_wait` | `http_wait(url: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |

## 详细参考

### `http_get`

```python
http_get(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_post`

```python
http_post(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_put`

```python
http_put(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_delete`

```python
http_delete(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_head`

```python
http_head(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_request`

```python
http_request(method: 'str', url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `method` | positional_or_keyword | `str` | `required` |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `http_wait`

```python
http_wait(url: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `url` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`
