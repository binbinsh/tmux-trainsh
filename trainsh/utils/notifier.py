"""Notification utilities for recipe and DSL execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import subprocess
import sys
import urllib.request
from typing import Callable, Optional, Tuple


VALID_LEVELS = {"info", "success", "warning", "error"}
VALID_CHANNELS = {"log", "system", "webhook", "command"}


@dataclass
class NotificationPayload:
    """Structured notification payload."""

    app: str
    title: str
    message: str
    level: str
    timestamp: str


def parse_bool(value: object) -> bool:
    """Parse a bool-like value from config/DSL options."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def normalize_level(level: str) -> str:
    """Normalize notification level and validate."""
    normalized = (level or "info").strip().lower()
    if normalized == "warn":
        normalized = "warning"
    if normalized not in VALID_LEVELS:
        raise ValueError(f"Invalid notification level: {level!r}")
    return normalized


def normalize_channels(value: object, default_channels: list[str]) -> list[str]:
    """Parse and validate channel list."""
    if value is None:
        channels = list(default_channels)
    elif isinstance(value, str):
        channels = [item.strip().lower() for item in value.split(",") if item.strip()]
    elif isinstance(value, list):
        channels = [str(item).strip().lower() for item in value if str(item).strip()]
    else:
        raise ValueError("channels must be a string or list")

    deduped: list[str] = []
    for channel in channels:
        if channel not in VALID_CHANNELS:
            raise ValueError(f"Invalid notification channel: {channel!r}")
        if channel not in deduped:
            deduped.append(channel)
    return deduped


class Notifier:
    """Send notifications across multiple channels."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        app_name: str = "train",
    ):
        self.log_callback = log_callback
        self.app_name = app_name

    def notify(
        self,
        *,
        title: str,
        message: str,
        level: str,
        channels: list[str],
        webhook_url: Optional[str] = None,
        command: Optional[str] = None,
        timeout_secs: int = 5,
        fail_on_error: bool = False,
    ) -> Tuple[bool, str]:
        """Send a notification through selected channels."""
        payload = NotificationPayload(
            app=self.app_name,
            title=title or self.app_name,
            message=message or "",
            level=normalize_level(level),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if timeout_secs <= 0:
            timeout_secs = 5
        if not channels:
            return False, "No notification channels configured"

        delivered: list[str] = []
        failed: list[str] = []

        for channel in channels:
            if channel == "log":
                ok, detail = self._send_log(payload)
            elif channel == "system":
                ok, detail = self._send_system(payload, timeout_secs)
            elif channel == "webhook":
                ok, detail = self._send_webhook(payload, webhook_url, timeout_secs)
            elif channel == "command":
                ok, detail = self._send_command(payload, command, timeout_secs)
            else:
                ok, detail = False, f"unsupported channel: {channel}"

            if ok:
                delivered.append(channel)
            else:
                failed.append(f"{channel} ({detail})")

        parts = []
        if delivered:
            parts.append(f"via {', '.join(delivered)}")
        if failed:
            parts.append(f"failed: {'; '.join(failed)}")

        summary = f"Notification {'; '.join(parts)}".strip()
        success = bool(delivered) and (not fail_on_error or not failed)
        if failed and not fail_on_error:
            self.log_callback(f"⚠️ Notification fallback disabled; ignored failures: {'; '.join(failed)}")
        return success, summary

    def _send_log(self, payload: NotificationPayload) -> Tuple[bool, str]:
        icon_map = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
        }
        level_icon = icon_map.get(payload.level, "📢")
        if payload.message:
            text = f"[{payload.level.upper()}] {payload.title}: {payload.message}"
        else:
            text = f"[{payload.level.upper()}] {payload.title}"
        self.log_callback(f"{level_icon} {text}")
        return True, "ok"

    def _send_system(
        self,
        payload: NotificationPayload,
        timeout_secs: int,
    ) -> Tuple[bool, str]:
        if sys.platform != "darwin":
            return False, f"Unsupported system notification platform: {sys.platform}"

        title = self._escape_osascript(payload.title)
        message = self._escape_osascript(payload.message or payload.title)
        script = f'display notification "{message}" with title "{title}"'
        return self._run_cmd(["osascript", "-e", script], timeout_secs)

    def _send_webhook(
        self,
        payload: NotificationPayload,
        webhook_url: Optional[str],
        timeout_secs: int,
    ) -> Tuple[bool, str]:
        if not webhook_url:
            return False, "webhook URL missing"

        data = json.dumps(
            {
                "app": payload.app,
                "title": payload.title,
                "message": payload.message,
                "level": payload.level,
                "timestamp": payload.timestamp,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_secs) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 300:
                    return True, f"HTTP {status}"
                return False, f"HTTP {status}"
        except Exception as exc:
            return False, str(exc)

    def _send_command(
        self,
        payload: NotificationPayload,
        command: Optional[str],
        timeout_secs: int,
    ) -> Tuple[bool, str]:
        if not command:
            return False, "command missing"

        env = os.environ.copy()
        env.update(
            {
                "TRAINSH_NOTIFY_APP": payload.app,
                "TRAINSH_NOTIFY_TITLE": payload.title,
                "TRAINSH_NOTIFY_MESSAGE": payload.message,
                "TRAINSH_NOTIFY_LEVEL": payload.level,
                "TRAINSH_NOTIFY_TIMESTAMP": payload.timestamp,
            }
        )

        try:
            result = subprocess.run(
                command,
                shell=True,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_secs,
            )
            if result.returncode == 0:
                return True, "ok"
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or f"exit {result.returncode}"
            return False, detail
        except Exception as exc:
            return False, str(exc)

    def _run_cmd(self, args: list[str], timeout_secs: int) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_secs,
            )
            if result.returncode == 0:
                return True, "ok"
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or f"exit {result.returncode}"
            return False, detail
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _escape_osascript(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
