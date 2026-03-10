"""Flat top-level authoring helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from .authoring_support import (
    bind_recipe,
    current_recipe,
    invoke_recipe_method,
    normalize_after,
    normalize_condition,
)
from .base import RecipeSpec
from .session_steps import RecipeSessionRef


def recipe(
    name: str,
    *,
    schedule: Optional[str] = None,
    owner: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    paused: Optional[bool] = None,
    catchup: Optional[bool] = None,
    max_active_runs: Optional[int] = None,
    executor: str = "sequential",
    executor_kwargs: Optional[Dict[str, Any]] = None,
    workers: Optional[int] = None,
    callbacks: Optional[list[str]] = None,
    **extra_executor_kwargs: Any,
) -> RecipeSpec:
    """Create and bind the current recipe for the surrounding module."""
    merged_kwargs = dict(executor_kwargs or {})
    if workers is not None and "max_workers" not in merged_kwargs:
        merged_kwargs["max_workers"] = workers
    merged_kwargs.update(extra_executor_kwargs)

    spec = RecipeSpec(
        name,
        executor=executor,
        executor_kwargs=merged_kwargs,
        callbacks=callbacks,
    )
    spec.schedule = schedule
    spec.owner = owner or "trainsh"
    spec.tags = list(tags or [])
    spec.is_paused = bool(paused) if paused is not None else False
    spec.catchup = bool(catchup) if catchup is not None else False
    spec.max_active_runs = max_active_runs
    return bind_recipe(spec)


def defaults(**kwargs: Any) -> RecipeSpec:
    """Set default task options on the current recipe."""
    params = dict(kwargs)
    if "retry" in params and "retries" not in params:
        params["retries"] = params.pop("retry")
    if "trigger" in params and "trigger_rule" not in params:
        params["trigger_rule"] = params.pop("trigger")
    if "backoff" in params and "retry_exponential_backoff" not in params:
        params["retry_exponential_backoff"] = params.pop("backoff")
    if "timeout" in params and "execution_timeout" not in params:
        params["execution_timeout"] = params.pop("timeout")
    current_recipe().defaults(**params)
    return current_recipe()


def var(name: str, value: Any) -> None:
    current_recipe().var(name, value)


def host(name: str, spec: Any) -> None:
    current_recipe().host(name, spec)


def storage(name: str, spec: Any) -> None:
    current_recipe().storage(name, spec)


def session(
    name: str,
    *,
    on: Optional[str] = None,
    after: Any = None,
    id: Optional[str] = None,
    **kwargs: Any,
) -> RecipeSessionRef:
    """Open or bind a session using the flat authoring syntax."""
    recipe_spec = current_recipe()
    if on is None:
        depends_on = normalize_after(kwargs.pop("depends_on", after))
        return recipe_spec.session(name, open_step_id=id, depends_on=depends_on)
    return invoke_recipe_method(
        recipe_spec,
        "tmux_session",
        on,
        as_=name,
        after=after,
        id=id,
        **kwargs,
    )


def close(target: RecipeSessionRef, **kwargs: Any) -> str:
    """Close a previously declared session."""
    return target.close(**kwargs)


def choose(
    variable: str,
    *,
    when: str,
    then: Any = "true",
    else_: Any = "false",
    host: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Write one variable based on a condition."""
    return invoke_recipe_method(
        current_recipe(),
        "branch",
        normalize_condition(when),
        variable=variable,
        true_value=then,
        false_value=else_,
        host=host,
        **kwargs,
    )


def sql_query(sql: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "db" in payload and "database" not in payload:
        payload["database"] = payload.pop("db")
    if "into" in payload and "output_var" not in payload:
        payload["output_var"] = payload.pop("into")
    return invoke_recipe_method(current_recipe(), "sqlite_query", sql, **payload)


def sql_exec(sql: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "db" in payload and "database" not in payload:
        payload["database"] = payload.pop("db")
    if "into" in payload and "output_var" not in payload:
        payload["output_var"] = payload.pop("into")
    return invoke_recipe_method(current_recipe(), "sqlite_exec", sql, **payload)


def sql_script(script: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "db" in payload and "database" not in payload:
        payload["database"] = payload.pop("db")
    if "into" in payload and "output_var" not in payload:
        payload["output_var"] = payload.pop("into")
    return invoke_recipe_method(current_recipe(), "sqlite_script", script, **payload)


def http_wait(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "status" in payload and "expected_status" not in payload:
        payload["expected_status"] = payload.pop("status")
    if "every" in payload and "poll_interval" not in payload:
        payload["poll_interval"] = payload.pop("every")
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    if "json" in payload and "json_body" not in payload:
        payload["json_body"] = payload.pop("json")
    return invoke_recipe_method(current_recipe(), "http_wait_for_status", url, **payload)


def http_get(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    return invoke_recipe_method(current_recipe(), "http_get", url, **payload)


def http_post(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    if "json" in payload and "json_body" not in payload:
        payload["json_body"] = payload.pop("json")
    return invoke_recipe_method(current_recipe(), "http_post", url, **payload)


def http_put(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    if "json" in payload and "json_body" not in payload:
        payload["json_body"] = payload.pop("json")
    return invoke_recipe_method(current_recipe(), "http_put", url, **payload)


def http_delete(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    return invoke_recipe_method(current_recipe(), "http_delete", url, **payload)


def http_head(url: str, **kwargs: Any) -> str:
    payload = dict(kwargs)
    if "capture" in payload and "capture_var" not in payload:
        payload["capture_var"] = payload.pop("capture")
    return invoke_recipe_method(current_recipe(), "http_head", url, **payload)


def storage_wait(storage_ref: str, path: str, **kwargs: Any) -> str:
    return invoke_recipe_method(current_recipe(), "storage_wait", storage_ref, path=path, **kwargs)


def sh(command: str, **kwargs: Any) -> str:
    return bash(command, **kwargs)


def http_request(method: str, url: str, **kwargs: Any) -> str:
    return _direct("http_request", method, url, **kwargs)


def _parse_storage_spec(spec: str) -> tuple[str, str]:
    text = str(spec).strip()
    if ":" not in text:
        raise ValueError(f"invalid storage spec: {spec!r}")
    storage_name, path = text.split(":", 1)
    storage_name = storage_name.strip().lstrip("@")
    if not storage_name:
        raise ValueError(f"invalid storage spec: {spec!r}")
    return storage_name, path or "/"


def storage_upload(source: str, destination: str, **kwargs: Any) -> str:
    storage_name, path = _parse_storage_spec(destination)
    return _direct("storage_upload", storage_name, source=source, destination=path, **kwargs)


def storage_download(source: str, destination: str, **kwargs: Any) -> str:
    storage_name, path = _parse_storage_spec(source)
    return _direct("storage_download", storage_name, source=path, destination=destination, **kwargs)


def storage_copy(source: str, destination: str, **kwargs: Any) -> str:
    source_storage, source_path = _parse_storage_spec(source)
    destination_storage, destination_path = _parse_storage_spec(destination)
    if source_storage != destination_storage:
        raise ValueError("storage_copy requires source and destination on the same storage alias")
    return _direct("storage_copy", source_storage, source=source_path, destination=destination_path, **kwargs)


def storage_move(source: str, destination: str, **kwargs: Any) -> str:
    source_storage, source_path = _parse_storage_spec(source)
    destination_storage, destination_path = _parse_storage_spec(destination)
    if source_storage != destination_storage:
        raise ValueError("storage_move requires source and destination on the same storage alias")
    return _direct("storage_move", source_storage, source=source_path, destination=destination_path, **kwargs)


def storage_sync(source: str, destination: str, **kwargs: Any) -> str:
    source_storage, source_path = _parse_storage_spec(source)
    destination_storage, destination_path = _parse_storage_spec(destination)
    if source_storage != destination_storage:
        raise ValueError("storage_sync requires source and destination on the same storage alias")
    return _direct("storage_sync", source_storage, source=source_path, destination=destination_path, **kwargs)


def storage_remove(target: str, **kwargs: Any) -> str:
    storage_name, path = _parse_storage_spec(target)
    return _direct("storage_remove", storage_name, path=path, **kwargs)


def _direct(method_name: str, *args: Any, **kwargs: Any) -> Any:
    return invoke_recipe_method(current_recipe(), method_name, *args, **kwargs)


var.__name__ = "var"
host.__name__ = "host"
storage.__name__ = "storage"


empty = lambda **kwargs: _direct("empty", **kwargs)
noop = lambda **kwargs: _direct("noop", **kwargs)
shell = lambda command, **kwargs: _direct("shell", command, **kwargs)
bash = lambda command, **kwargs: _direct("bash", command, **kwargs)
python = lambda code_or_command, **kwargs: _direct("python", code_or_command, **kwargs)
notice = lambda message, **kwargs: _direct("notice", message, **kwargs)
email_send = lambda message, **kwargs: _direct("email_send", message, **kwargs)
webhook = lambda message, **kwargs: _direct("webhook", message, **kwargs)
slack = lambda message, **kwargs: _direct("slack", message, **kwargs)
telegram = lambda message, **kwargs: _direct("telegram", message, **kwargs)
discord = lambda message, **kwargs: _direct("discord", message, **kwargs)
latest_only = lambda **kwargs: _direct("latest_only", **kwargs)
short_circuit = lambda condition, **kwargs: _direct("short_circuit", normalize_condition(condition), **kwargs)
skip_if = lambda condition, **kwargs: _direct("skip_if", normalize_condition(condition), **kwargs)
skip_if_not = lambda condition, **kwargs: _direct("skip_if_not", normalize_condition(condition), **kwargs)
join = lambda **kwargs: _direct("join", **kwargs)
on_all_done = lambda **kwargs: _direct("on_all_done", **kwargs)
on_all_success = lambda **kwargs: _direct("on_all_success", **kwargs)
on_all_failed = lambda **kwargs: _direct("on_all_failed", **kwargs)
on_one_success = lambda **kwargs: _direct("on_one_success", **kwargs)
on_one_failed = lambda **kwargs: _direct("on_one_failed", **kwargs)
on_none_failed = lambda **kwargs: _direct("on_none_failed", **kwargs)
on_none_failed_or_skipped = lambda **kwargs: _direct("on_none_failed_or_skipped", **kwargs)
wait_condition = lambda condition, **kwargs: _direct("wait_condition", normalize_condition(condition), **kwargs)
host_test = lambda target, **kwargs: _direct("host_test", target, **kwargs)
git_clone = lambda repo_url, destination=None, **kwargs: _direct("git_clone", repo_url, destination, **kwargs)
git_pull = lambda directory=".", **kwargs: _direct("git_pull", directory, **kwargs)
transfer = lambda source, destination, **kwargs: _direct("transfer", source, destination, **kwargs)
vast_pick = lambda **kwargs: _direct("vast_pick", **kwargs)
vast_wait = lambda **kwargs: _direct("vast_wait", **kwargs)
vast_start = lambda *args, **kwargs: _direct("vast_start", *args, **kwargs)
vast_stop = lambda *args, **kwargs: _direct("vast_stop", *args, **kwargs)
vast_cost = lambda *args, **kwargs: _direct("vast_cost", *args, **kwargs)
xcom_push = lambda key, value=None, **kwargs: _direct("xcom_push", key, value, **kwargs)
xcom_pull = lambda key, **kwargs: _direct("xcom_pull", key, **kwargs)
fail = lambda message="Failed by recipe.", **kwargs: _direct("fail", message, **kwargs)
tmux_config = lambda target, **kwargs: _direct("tmux_config", target, **kwargs)
set_env = lambda name, value, **kwargs: _direct("set_env", name, value, **kwargs)
assert_ = lambda condition, **kwargs: _direct("assert_", normalize_condition(condition), **kwargs)
wait_file = lambda path, **kwargs: _direct("wait_file", path, **kwargs)
wait_for_port = lambda port, **kwargs: _direct("wait_for_port", port, **kwargs)
sleep = lambda duration, **kwargs: _direct("sleep", duration, **kwargs)
tmux_open = lambda target, **kwargs: _direct("tmux_open", target, **kwargs)
tmux_close = lambda target, **kwargs: _direct("tmux_close", target, **kwargs)


__all__ = [
    "assert_",
    "bash",
    "choose",
    "close",
    "defaults",
    "discord",
    "empty",
    "email_send",
    "fail",
    "git_clone",
    "git_pull",
    "host",
    "host_test",
    "http_delete",
    "http_get",
    "http_head",
    "http_request",
    "http_post",
    "http_put",
    "http_wait",
    "join",
    "latest_only",
    "load_python_recipe",
    "noop",
    "notice",
    "on_all_done",
    "on_all_failed",
    "on_all_success",
    "on_none_failed",
    "on_none_failed_or_skipped",
    "on_one_failed",
    "on_one_success",
    "python",
    "recipe",
    "session",
    "set_env",
    "sh",
    "shell",
    "sleep",
    "short_circuit",
    "skip_if",
    "skip_if_not",
    "sql_exec",
    "sql_query",
    "sql_script",
    "storage",
    "storage_copy",
    "storage_download",
    "storage_move",
    "storage_remove",
    "storage_sync",
    "storage_upload",
    "storage_wait",
    "slack",
    "telegram",
    "tmux_close",
    "tmux_config",
    "tmux_open",
    "transfer",
    "var",
    "vast_cost",
    "vast_pick",
    "vast_start",
    "vast_stop",
    "vast_wait",
    "wait_condition",
    "wait_file",
    "wait_for_port",
    "webhook",
    "xcom_pull",
    "xcom_push",
]


from .loader import load_python_recipe  # noqa: E402  pylint: disable=wrong-import-position
