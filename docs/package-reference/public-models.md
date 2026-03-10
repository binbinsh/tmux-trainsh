# Public models and entry points

These are the public objects that appear in user-facing imports and runtime integrations.

## Summary

| Object | Signature | Role |
| --- | --- | --- |
| `recipe` | `recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'` | Top-level declaration that binds the active recipe for one `.py` file. |
| `load_python_recipe` | `load_python_recipe(path: 'str') -> 'Any'` | Load one `.py` recipe file and return its bound recipe object. |

## Details

## `recipe`

Top-level declaration that binds the active recipe for one `.py` file.

```python
recipe(name: 'str', *, schedule: 'Optional[str]' = None, owner: 'Optional[str]' = None, tags: 'Optional[Iterable[str]]' = None, paused: 'Optional[bool]' = None, catchup: 'Optional[bool]' = None, max_active_runs: 'Optional[int]' = None, executor: 'str' = 'sequential', executor_kwargs: 'Optional[Dict[str, Any]]' = None, workers: 'Optional[int]' = None, callbacks: 'Optional[list[str]]' = None, **extra_executor_kwargs: 'Any') -> 'Any'
```

## `load_python_recipe`

Load one `.py` recipe file and return its bound recipe object.

```python
load_python_recipe(path: 'str') -> 'Any'
```
