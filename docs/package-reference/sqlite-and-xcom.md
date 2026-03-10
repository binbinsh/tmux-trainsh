# SQLite and XCom

## What this page covers

SQLite helpers run local database queries, while XCom-style helpers persist and retrieve small runtime values through sqlite metadata.

## Typical use cases

- Record lightweight workflow metadata during a run.
- Pass small values between tasks without editing files.

## Entry point

```python
recipe(...)
```

## Common usage

```python
setup = sql_script("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, name TEXT);", db="$SQLITE_DB")
rows = sql_query("SELECT * FROM runs", db="$SQLITE_DB", into="RUNS", after=setup)
```

## API summary

| Helper | Signature | Purpose |
| --- | --- | --- |
| `sql_query` | `sql_query(sql: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `sql_exec` | `sql_exec(sql: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `sql_script` | `sql_script(script: 'str', **kwargs: 'Any') -> 'str'` | Public helper in this page. |
| `xcom_push` | `xcom_push(key, value=None, **kwargs)` | Public helper in this page. |
| `xcom_pull` | `xcom_pull(key, **kwargs)` | Public helper in this page. |

## Detailed reference

### `sql_query`

```python
sql_query(sql: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `sql` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `sql_exec`

```python
sql_exec(sql: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `sql` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `sql_script`

```python
sql_script(script: 'str', **kwargs: 'Any') -> 'str'
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `script` | positional_or_keyword | `str` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`str`

### `xcom_push`

```python
xcom_push(key, value=None, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `key` | positional_or_keyword | `Any` | `required` |
| `value` | positional_or_keyword | `Any` | `None` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`

### `xcom_pull`

```python
xcom_pull(key, **kwargs)
```

Public helper exposed by this API page.

**Parameters**

| Parameter | Kind | Type | Default |
| --- | --- | --- | --- |
| `key` | positional_or_keyword | `Any` | `required` |
| `kwargs` | var_keyword | `Any` | `required` |

**Returns**

`Any`
