"""Misc provider helpers for Python recipes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class RecipeProviderMiscMixin:
    """Small utility provider helpers."""

    def set_var(
        self,
        name: str,
        value: Any,
        *,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Set one runtime variable."""
        return self.provider(
            "util",
            "set_var",
            params={
                "name": str(name),
                "value": value,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def fail(
        self,
        message: str = "Failed by recipe.",
        *,
        exit_code: int = 1,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Explicitly fail the recipe step."""
        return self.provider(
            "util",
            "fail",
            params={
                "message": message,
                "exit_code": int(exit_code),
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def xcom_push(
        self,
        key: str,
        value: Any = None,
        *,
        from_var: Optional[str] = None,
        output_var: Optional[str] = None,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        dag_id: Optional[str] = None,
        map_index: int = 0,
        database: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Push one value to runtime XCom storage."""
        params: Dict[str, Any] = {
            "key": str(key),
            "value": value,
            "map_index": int(map_index),
        }
        if from_var is not None:
            params["from_var"] = str(from_var)
        if output_var is not None:
            params["output_var"] = str(output_var)
        if task_id is not None:
            params["task_id"] = str(task_id)
        if run_id is not None:
            params["run_id"] = str(run_id)
        if dag_id is not None:
            params["dag_id"] = str(dag_id)
        if database is not None:
            params["database"] = str(database)
        return self.provider(
            "util",
            "xcom_push",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def xcom_pull(
        self,
        key: str,
        *,
        task_ids: Optional[Iterable[str] | str] = None,
        run_id: Optional[str] = None,
        dag_id: Optional[str] = None,
        map_index: Optional[int] = None,
        include_prior_dates: bool = False,
        default: Any = None,
        output_var: Optional[str] = None,
        decode_json: bool = False,
        database: Optional[str] = None,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Pull one value from runtime XCom storage."""
        params: Dict[str, Any] = {
            "key": str(key),
            "include_prior_dates": bool(include_prior_dates),
            "decode_json": bool(decode_json),
        }
        if task_ids is not None:
            if isinstance(task_ids, str):
                params["task_ids"] = [item.strip() for item in task_ids.split(",") if item.strip()]
            else:
                params["task_ids"] = [str(item).strip() for item in task_ids if str(item).strip()]
        if run_id is not None:
            params["run_id"] = str(run_id)
        if dag_id is not None:
            params["dag_id"] = str(dag_id)
        if map_index is not None:
            params["map_index"] = int(map_index)
        if default is not None:
            params["default"] = default
        if output_var is not None:
            params["output_var"] = str(output_var)
        if database is not None:
            params["database"] = str(database)
        return self.provider(
            "util",
            "xcom_pull",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def notice(
        self,
        message: str,
        *,
        title: Optional[str] = None,
        channels: Optional[Iterable[str]] = None,
        level: str = "info",
        webhook: Optional[str] = None,
        command: Optional[str] = None,
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a user notification."""
        params: Dict[str, Any] = {
            "message": message,
            "title": title,
            "channels": list(channels) if channels is not None else None,
            "level": level,
            "webhook": webhook,
            "command": command,
            "timeout": timeout,
            "fail_on_error": fail_on_error,
        }
        if params["channels"] is None:
            del params["channels"]
        if title is None:
            del params["title"]
        if webhook is None:
            del params["webhook"]
        if command is None:
            del params["command"]
        return self.provider(
            "util",
            "notice",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def webhook(
        self,
        message: str,
        *,
        webhook: str,
        title: Optional[str] = None,
        channels: Optional[Iterable[str]] = None,
        level: str = "info",
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a message through a webhook provider."""
        return self.provider(
            "webhook",
            "send",
            params={
                "message": message,
                "title": title,
                "channels": list(channels) if channels is not None else ["webhook"],
                "level": level,
                "webhook": webhook,
                "timeout": timeout,
                "fail_on_error": fail_on_error,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def slack(
        self,
        message: str,
        webhook: str,
        *,
        title: Optional[str] = None,
        channel: Optional[str] = None,
        username: Optional[str] = None,
        level: str = "info",
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a Slack-style message.

        We keep this as an alias over webhook-backed execution for now.
        """
        payload: Dict[str, Any] = {
            "message": message,
            "title": title,
            "channel": channel,
            "username": username,
            "level": level,
            "webhook": webhook,
            "channels": ["webhook"],
            "timeout": timeout,
            "fail_on_error": fail_on_error,
        }
        return self.provider(
            "slack",
            "send",
            params=payload,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def telegram(
        self,
        message: str,
        webhook: str,
        *,
        title: Optional[str] = None,
        level: str = "info",
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a Telegram-style message via webhook."""
        return self.provider(
            "telegram",
            "send",
            params={
                "message": message,
                "title": title,
                "level": level,
                "webhook": webhook,
                "channels": ["webhook"],
                "timeout": timeout,
                "fail_on_error": fail_on_error,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def discord(
        self,
        message: str,
        webhook: str,
        *,
        title: Optional[str] = None,
        level: str = "info",
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a Discord-style message via webhook."""
        return self.provider(
            "discord",
            "send",
            params={
                "message": message,
                "title": title,
                "level": level,
                "webhook": webhook,
                "channels": ["webhook"],
                "timeout": timeout,
                "fail_on_error": fail_on_error,
            },
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )

    def email_send(
        self,
        message: str,
        *,
        to: Optional[Iterable[str]] = None,
        subject: Optional[str] = None,
        from_addr: Optional[str] = None,
        level: str = "info",
        timeout: Any = "30s",
        fail_on_error: bool = False,
        id: Optional[str] = None,
        depends_on: Optional[Iterable[str]] = None,
        step_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Email-style alias for notification.

        If SMTP/webhook transport is configured, this sends through notify backend.
        """
        params: Dict[str, Any] = {
            "message": message,
            "subject": subject,
            "to": list(to) if to is not None else None,
            "from": from_addr,
            "level": level,
            "timeout": timeout,
            "fail_on_error": fail_on_error,
        }
        return self.provider(
            "email",
            "send",
            params=params,
            id=id,
            depends_on=depends_on,
            step_options=step_options,
        )
