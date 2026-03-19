# tmux-trainsh constants and defaults

import os
from pathlib import Path

# Application name
APP_NAME = "tmux-trainsh"

# XDG directories
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")))

# Config directory
CONFIG_DIR = CONFIG_HOME / "tmux-trainsh"
DATA_DIR = DATA_HOME / "tmux-trainsh"
STATE_DIR = STATE_HOME / "tmux-trainsh"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
HOSTS_FILE = CONFIG_DIR / "hosts.yaml"
STORAGES_FILE = CONFIG_DIR / "storages.yaml"
RECIPES_DIR = DATA_DIR / "recipes"
LOGS_DIR = DATA_DIR / "logs"
RUNTIME_STATE_DIR = STATE_DIR / "runtime"
RECIPE_FILE_EXTENSION = ".pyrecipe"
RECIPE_FILE_EXTENSIONS = (RECIPE_FILE_EXTENSION,)

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
    AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY = "AWS_SECRET_ACCESS_KEY"
    # Cloud storage keys
    R2_CREDENTIALS = "R2_CREDENTIALS"
    R2_ACCOUNT_ID = "R2_ACCOUNT_ID"
    R2_ACCESS_KEY_ID = "R2_ACCESS_KEY_ID"
    R2_SECRET_ACCESS_KEY = "R2_SECRET_ACCESS_KEY"
    B2_CREDENTIALS = "B2_CREDENTIALS"
    B2_APPLICATION_KEY_ID = "B2_APPLICATION_KEY_ID"
    B2_APPLICATION_KEY = "B2_APPLICATION_KEY"
