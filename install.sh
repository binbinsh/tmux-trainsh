#!/bin/bash
# Install tmux-trainsh CLI tool via uv

set -e

usage() {
    echo "Usage: curl -LsSf https://raw.githubusercontent.com/binbinsh/tmux-trainsh/main/install.sh | bash"
    echo "   or: bash install.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --github      Install from GitHub (latest commit)"
    echo "  --force       Force reinstall"
    echo "  --no-deps     Skip installing system dependencies"
    echo "  --help        Show this help message"
    echo ""
    echo "Default: Install from PyPI"
}

# Parse arguments
FROM_GITHUB=false
FORCE=false
INSTALL_DEPS=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --github|-g)
            FROM_GITHUB=true
            shift
            ;;
        --force|-f)
            FORCE=true
            shift
            ;;
        --no-deps)
            INSTALL_DEPS=false
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Ensure uv is installed
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install system dependencies
install_deps() {
    echo ""
    echo "Checking system dependencies..."

    # Install keyring CLI tool
    echo "Installing keyring..."
    uv tool install keyring 2>/dev/null || echo "keyring already installed"

    # Check for rsync
    if ! command -v rsync &> /dev/null; then
        echo "Installing rsync..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install rsync 2>/dev/null || echo "Please install rsync: brew install rsync"
        else
            sudo apt-get install -y rsync 2>/dev/null || echo "Please install rsync manually"
        fi
    else
        echo "rsync: installed"
    fi

    # Check for pv (for transfer progress display)
    if ! command -v pv &> /dev/null; then
        echo "Installing pv..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install pv 2>/dev/null || echo "Please install pv: brew install pv"
        else
            sudo apt-get install -y pv 2>/dev/null || echo "Please install pv manually"
        fi
    else
        echo "pv: installed"
    fi

    # Check for rclone
    if ! command -v rclone &> /dev/null; then
        echo "Installing rclone..."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install rclone 2>/dev/null || echo "Please install rclone: brew install rclone"
        else
            curl https://rclone.org/install.sh | sudo bash 2>/dev/null || echo "Please install rclone manually"
        fi
    else
        echo "rclone: installed"
    fi

    # Note: tmux is only needed on REMOTE machines (Vast.ai, etc.)
    # Local tmux is NOT required - all tmux commands run via SSH
}

# Uninstall existing version if force
if [ "$FORCE" = true ]; then
    echo "Removing existing installation..."
    uv tool uninstall tmux-trainsh 2>/dev/null || true
fi

# Install via uv tool
if [ "$FROM_GITHUB" = true ]; then
    REPO="git+https://github.com/binbinsh/tmux-trainsh"
    echo "Installing tmux-trainsh from GitHub..."
    echo "  Source: $REPO"
    uv tool install "$REPO" --force
else
    echo "Installing tmux-trainsh from PyPI..."
    uv tool install -U tmux-trainsh
fi

# Install dependencies if requested
if [ "$INSTALL_DEPS" = true ]; then
    install_deps
fi

echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  train help"
echo "  train host list"
echo "  train vast list"
echo "  train run <recipe>"
echo ""

# Check if uv tools bin is in PATH
UV_BIN="$HOME/.local/bin"
if [[ ":$PATH:" != *":$UV_BIN:"* ]]; then
    printf "\033[1;33mNote: Add ~/.local/bin to your PATH:\033[0m\n"
    echo ""
    printf "  \033[1;33m# Add this to ~/.zshrc or ~/.bashrc:\033[0m\n"
    printf "  \033[1;33mexport PATH=\"\$HOME/.local/bin:\$PATH\"\033[0m\n"
fi
