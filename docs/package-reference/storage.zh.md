# 存储

## 本页说明

存储 helper 提供上传、下载、复制、移动、同步、查看元数据，以及等待存储路径等能力。

## 典型使用场景

- 把产物发布到对象存储。
- 轮询另一个系统产出的对象或键。

## 入口

```python
recipe(...)
```

## 常见用法

```python
upload = storage_upload("./artifacts", "artifacts:/runs/$RUN_NAME")
wait = storage_wait("artifacts", "/runs/$RUN_NAME/done.txt", after=upload)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `storage_upload` | `storage_upload(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_download` | `storage_download(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_wait` | `storage_wait(storage_ref: 'str', path: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_copy` | `storage_copy(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_move` | `storage_move(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_sync` | `storage_sync(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `storage_remove` | `storage_remove(target: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |

## 详细参考

### `storage_upload`

```python
storage_upload(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_download`

```python
storage_download(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_wait`

```python
storage_wait(storage_ref: 'str', path: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `storage_ref` | positional_or_keyword | `str` | `required` |
| `path` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_copy`

```python
storage_copy(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_move`

```python
storage_move(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_sync`

```python
storage_sync(source: 'str', destination: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `str` | `required` |
| `destination` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `storage_remove`

```python
storage_remove(target: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `target` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`
