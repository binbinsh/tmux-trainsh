# tmux-trainsh configuration loading

import os
from typing import Any, Dict
import tomllib

from .constants import CONFIG_DIR, CONFIG_FILE


def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    """
    Load the main configuration file.

    Returns:
        Configuration dictionary
    """
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        return get_default_config()

    with open(CONFIG_FILE, "rb") as f:
        config = tomllib.load(f)

    # Merge with defaults
    defaults = get_default_config()
    return merge_dicts(defaults, config)


def _format_toml_value(value: Any) -> str:
    """Format a Python value as TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, str):
        return f'"{value}"'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, list):
        items = ", ".join(_format_toml_value(v) for v in value)
        return f"[{items}]"
    else:
        return str(value)


def _dict_to_toml(data: Dict[str, Any], prefix: str = "") -> str:
    """Convert a dictionary to TOML format."""
    lines = []

    # First, handle non-dict values
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_format_toml_value(value)}")

    # Then handle nested dicts as sections
    for key, value in data.items():
        if isinstance(value, dict):
            section_name = f"{prefix}{key}" if prefix else key
            lines.append("")
            lines.append(f"[{section_name}]")
            for k, v in value.items():
                if isinstance(v, dict):
                    # Handle nested sections
                    lines.append("")
                    lines.append(f"[{section_name}.{k}]")
                    for kk, vv in v.items():
                        lines.append(f"{kk} = {_format_toml_value(vv)}")
                else:
                    lines.append(f"{k} = {_format_toml_value(v)}")

    return "\n".join(lines)


def save_config(config: Dict[str, Any]) -> None:
    """
    Save the configuration file.

    Args:
        config: Configuration dictionary
    """
    ensure_config_dir()

    toml_str = _dict_to_toml(config)
    with open(CONFIG_FILE, "w") as f:
        f.write(toml_str)


def get_default_config() -> Dict[str, Any]:
    """Get the default configuration."""
    return {
        "version": 1,
        "defaults": {
            "ssh_key_path": "~/.ssh/id_rsa",
        },
        "vast": {
            "auto_attach_ssh_key": True,
        },
        "ui": {
            "currency": "USD",
        },
        "tmux": {
            # Raw tmux options as "option = value" strings
            # These are written directly to tmux.conf
            "options": [
                "set -g mouse on",
                "set -g history-limit 50000",
                "set -g base-index 1",
                "setw -g pane-base-index 1",
                "set -g renumber-windows on",
                "set -g status-position top",
                "set -g status-interval 1",
                "set -g status-left-length 50",
                'set -g status-left "[#S] "',
                "set -g status-right-length 100",
                'set -g status-right "#H:#{pane_current_path}"',
                'set -g window-status-format " #I:#W "',
                'set -g window-status-current-format " #I:#W "',
                "bind -n MouseDown1Status select-window -t =",
            ],
        },
    }


def merge_dicts(base: Dict, override: Dict) -> Dict:
    """
    Deep merge two dictionaries.

    Args:
        base: Base dictionary
        override: Dictionary with overriding values

    Returns:
        Merged dictionary
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value

    return result


def get_config_value(path: str, default: Any = None) -> Any:
    """
    Get a configuration value by dot-separated path.

    Args:
        path: Dot-separated path (e.g., "vast.default_disk_gb")
        default: Default value if not found

    Returns:
        Configuration value
    """
    config = load_config()
    keys = path.split(".")

    value = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def set_config_value(path: str, value: Any) -> None:
    """
    Set a configuration value by dot-separated path.

    Args:
        path: Dot-separated path (e.g., "vast.default_disk_gb")
        value: Value to set
    """
    config = load_config()
    keys = path.split(".")

    # Navigate to parent
    current = config
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Set value
    current[keys[-1]] = value
    save_config(config)
