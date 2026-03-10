# 分支与控制流

`trainsh` recipe 本质上是 DAG。控制流 helper 让你能够显式表达决策点和合流行为。

## 基本分支

```python
branch = choose("RUN_PATH", when='MODE == "production"', then="prod", else_="dev")
```

## 短路

```python
check = short_circuit("READY == true")
```

别名包括：

- `skip_if(...)`
- `skip_if_not(...)`

## latest_only

```python
latest = latest_only(fail_if_unknown=False)
```

这个 helper 对定时任务尤其有用。

## 合流行为

使用 `join(...)` 或显式 trigger-rule helper：

```python
merge = join(after=[left, right])
done = on_all_done(after=merge)
```

## 相关页面

- [依赖 DAG](../concepts/dependency-dag.md)
- [Control flow reference](../package-reference/control-flow.md)
- [Control helpers](../package-reference/control-helpers.md)
