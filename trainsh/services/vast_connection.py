"""Shared Vast.ai SSH target resolution helpers."""

from __future__ import annotations

from typing import Any, Optional


def _read_value(instance: Any, name: str, default=None):
    if isinstance(instance, dict):
        return instance.get(name, default)
    return getattr(instance, name, default)


def _coerce_port(raw: Any) -> Optional[int]:
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _port_bindings(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


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


def vast_ssh_targets(instance: Any) -> list[dict[str, Any]]:
    """Return ordered SSH targets for one Vast instance.

    Ordering follows Vast's own connection model first:
    1. explicit 22/tcp port mappings on the public IP
    2. legacy direct SSH fields
    3. proxy SSH fields, including the jupyter runtype offset fallback
    """

    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    public_ipaddr = _read_value(instance, "public_ipaddr")
    ports = _read_value(instance, "ports") or {}
    if isinstance(ports, dict) and public_ipaddr:
        for key in ("22/tcp", "22"):
            for binding in _port_bindings(ports.get(key)):
                host_port = (
                    binding.get("HostPort")
                    or binding.get("host_port")
                    or binding.get("public_port")
                    or binding.get("port")
                )
                _append_target(
                    targets,
                    seen,
                    hostname=public_ipaddr,
                    port=host_port,
                    source=f"ports:{key}",
                )

    _append_target(
        targets,
        seen,
        hostname=public_ipaddr,
        port=_read_value(instance, "direct_port_start"),
        source="direct_port_start",
    )

    ssh_host = _read_value(instance, "ssh_host")
    ssh_port = _coerce_port(_read_value(instance, "ssh_port"))
    image_runtype = str(_read_value(instance, "image_runtype", "") or "").lower()
    if ssh_host and ssh_port is not None and "jupyter" in image_runtype:
        _append_target(
            targets,
            seen,
            hostname=ssh_host,
            port=ssh_port + 1,
            source="ssh_proxy_jupyter_offset",
        )

    _append_target(
        targets,
        seen,
        hostname=ssh_host,
        port=ssh_port,
        source="ssh_proxy",
    )

    return targets


def preferred_vast_ssh_target(instance: Any) -> Optional[dict[str, Any]]:
    """Return the first preferred SSH target for a Vast instance."""
    targets = vast_ssh_targets(instance)
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
    "preferred_vast_ssh_target",
    "ssh_target_to_command",
    "ssh_target_to_spec",
    "vast_ssh_targets",
]
