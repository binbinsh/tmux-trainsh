"""Shared RunPod SSH target resolution helpers."""

from __future__ import annotations

from typing import Any, Optional


def _read_value(pod: Any, name: str, default=None):
    if isinstance(pod, dict):
        return pod.get(name, default)
    return getattr(pod, name, default)


def _coerce_port(raw: Any) -> Optional[int]:
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _append_target(
    targets: list[dict[str, Any]],
    seen: set[tuple[str, int, str]],
    *,
    hostname: Any,
    port: Any,
    source: str,
    username: str = "root",
) -> None:
    host_text = str(hostname or "").strip()
    port_num = _coerce_port(port)
    if not host_text or port_num is None:
        return
    key = (host_text, port_num, username)
    if key in seen:
        return
    targets.append(
        {
            "type": "ssh",
            "hostname": host_text,
            "port": port_num,
            "username": username,
            "source": source,
        }
    )
    seen.add(key)


def runpod_ssh_targets(pod: Any) -> list[dict[str, Any]]:
    """Return ordered SSH targets for one RunPod Pod."""
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    public_ip = _read_value(pod, "public_ip") or _read_value(pod, "publicIp")
    mappings = _read_value(pod, "port_mappings") or _read_value(pod, "portMappings") or {}
    if isinstance(mappings, dict):
        for key in ("22", 22):
            port = mappings.get(key)
            if port is not None:
                _append_target(
                    targets,
                    seen,
                    hostname=public_ip,
                    port=port,
                    source="port_mappings:22",
                )
    return targets


def preferred_runpod_ssh_target(pod: Any) -> Optional[dict[str, Any]]:
    """Return the first preferred SSH target for a RunPod Pod."""
    targets = runpod_ssh_targets(pod)
    if not targets:
        return None
    return targets[0]


def ssh_target_to_spec(target: dict[str, Any]) -> str:
    """Convert an SSH target dict into trainsh's SSH spec form."""
    username = str(target.get("username") or "root")
    hostname = str(target.get("hostname") or "")
    port = int(target.get("port", 22) or 22)
    return f"{username}@{hostname} -p {port}"


def ssh_target_to_command(target: dict[str, Any]) -> str:
    """Convert an SSH target dict into a shell ssh command."""
    username = str(target.get("username") or "root")
    hostname = str(target.get("hostname") or "")
    port = int(target.get("port", 22) or 22)
    return f"ssh -p {port} {username}@{hostname}"


__all__ = [
    "preferred_runpod_ssh_target",
    "runpod_ssh_targets",
    "ssh_target_to_command",
    "ssh_target_to_spec",
]
