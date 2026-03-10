# SQLite 与 XCom

## 本页说明

SQLite helper 用于本地数据库查询，XCom 风格 helper 用于通过 sqlite 元数据持久化和读取小型运行时值。

## 典型使用场景

- 在运行过程中记录轻量级工作流元数据。
- 在任务之间传递小型值，而不需要写文件。

## 入口

```python
recipe(...)
```

## 常见用法

```python
setup = sql_script("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, name TEXT);", db="$SQLITE_DB")
rows = sql_query("SELECT * FROM runs", db="$SQLITE_DB", into="RUNS", after=setup)
```

## API 概览

| Helper | 签名 | 用途 |
| --- | --- | --- |
| `sql_query` | `sql_query(sql: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `sql_exec` | `sql_exec(sql: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `sql_script` | `sql_script(script: 'str', **kwargs: 'Any') -> 'str'` | 此页公开的 API helper。 |
| `xcom_push` | `xcom_push(key, value=None, **kwargs)` | 此页公开的 API helper。 |
| `xcom_pull` | `xcom_pull(key, **kwargs)` | 此页公开的 API helper。 |

## 详细参考

### `sql_query`

```python
sql_query(sql: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `sql` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `sql_exec`

```python
sql_exec(sql: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `sql` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `sql_script`

```python
sql_script(script: 'str', **kwargs: 'Any') -> 'str'
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `script` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`str`

### `xcom_push`

```python
xcom_push(key, value=None, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `key` | positional_or_keyword | `Any` | `required` |
| `value` | positional_or_keyword | `Any` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`

### `xcom_pull`

```python
xcom_pull(key, **kwargs)
```

此页面公开的 API helper。

**参数**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `key` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**返回值**

`Any`
