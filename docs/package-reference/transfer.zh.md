# 传输

## 本页说明

传输 helper 用于在本地路径、远端主机和存储端点之间移动文件或目录。

## 典型使用场景

- 把模型输出从 GPU 主机拉回本地。
- 在本地和云存储之间同步 checkpoint。

## 入口

```python
recipe(...)
```

## 常见用法

```python
copy = transfer("@gpu:/workspace/output", "./output")
mirror = transfer("./checkpoints", "artifacts:/checkpoints", operation="sync")
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `transfer` | `transfer(source, destination, **kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `transfer`

```python
transfer(source, destination, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `source` | positional_or_keyword | `Any` | `required` |
| `destination` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`
