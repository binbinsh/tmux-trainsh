# tmux-trainsh constants and defaults

import os
from pathlib import Path

# Application name
APP_NAME = "tmux-trainsh"

# Config directory
CONFIG_DIR = Path(os.path.expanduser("~/.config/tmux-trainsh"))
CONFIG_FILE = CONFIG_DIR / "config.toml"
HOSTS_FILE = CONFIG_DIR / "hosts.toml"
STORAGES_FILE = CONFIG_DIR / "storages.toml"
RECIPES_DIR = CONFIG_DIR / "recipes"
LOGS_DIR = CONFIG_DIR / "logs"

# Keyring service name
KEYRING_SERVICE = "tmux-trainsh"

# Vast.ai API
VAST_API_BASE = "https://console.vast.ai/api/v0"

# Default settings
DEFAULT_SSH_KEY_PATH = "~/.ssh/id_rsa"
DEFAULT_TRANSFER_METHOD = "rsync"
DEFAULT_VAST_IMAGE = "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime"
DEFAULT_VAST_DISK_GB = 50

# Predefined secret keys
class SecretKeys:
    VAST_API_KEY = "VAST_API_KEY"
    HF_TOKEN = "HF_TOKEN"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
    GITHUB_TOKEN = "GITHUB_TOKEN"
    GOOGLE_DRIVE_CREDENTIALS = "GOOGLE_DRIVE_CREDENTIALS"
    # Cloud storage keys
    R2_ACCESS_KEY = "R2_ACCESS_KEY"
    R2_SECRET_KEY = "R2_SECRET_KEY"
    B2_KEY_ID = "B2_KEY_ID"
    B2_APPLICATION_KEY = "B2_APPLICATION_KEY"
    AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY = "AWS_SECRET_ACCESS_KEY"
