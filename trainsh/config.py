# tmux-trainsh configuration loading

import os
from typing import Any, Dict
import yaml

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

    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f) or {}

    # Merge with defaults
    defaults = get_default_config()
    return merge_dicts(defaults, config)


def save_config(config: Dict[str, Any]) -> None:
    """
    Save the configuration file.

    Args:
        config: Configuration dictionary
    """
    ensure_config_dir()

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def get_default_config() -> Dict[str, Any]:
    """Get the default configuration."""
    return {
        "vast": {
            "auto_attach_ssh_key": True,
        },
        "ui": {
            "currency": "",
        },
        "tmux": {
            # Auto-create local tmux splits that attach to recipe windows
            "auto_bridge": True,
            # If train is started outside tmux, create a detached local bridge session
            "bridge_outside_tmux": True,
            # If recipe run/resume starts outside tmux, auto-enter a tmux session first
            "auto_enter_tmux": True,
            # Prefer sending execute commands through local bridge pane when available
            "prefer_bridge_exec": True,
            # Remote bridge status bar behavior: keep | off | bottom
            "bridge_remote_status": "off",
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
        "notifications": {
            # Enable/disable notifications globally.
            "enabled": True,
            # App name/title fallback for notifications.
            "app_name": "train",
            # Default channels: log | system | webhook | command
            "channels": ["log", "system"],
            # Optional default webhook URL used by channel=webhook.
            "webhook_url": "",
            # Optional default shell command used by channel=command.
            "command": "",
            # Timeout for each notification channel.
            "timeout_secs": 5,
            # If true, any channel failure fails the notify step.
            "fail_on_error": False,
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
