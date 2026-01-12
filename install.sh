#!/bin/bash
# Install kitten-trainsh to kitty config directory

set -e

usage() {
    echo "Usage: bash install.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --github      Install from GitHub (clone to ~/.config/kitty/)"
    echo "  --force       Force overwrite existing files"
    echo "  --no-deps     Skip installing Python dependencies"
    echo "  --help        Show this help message"
    echo ""
    echo "Default: Create symlinks from current directory"
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

KITTY_CONFIG="$HOME/.config/kitty"
DST_PKG="$KITTY_CONFIG/trainsh"
DST_PY="$KITTY_CONFIG/trainsh.py"

# Create kitty config directory if it doesn't exist
mkdir -p "$KITTY_CONFIG"

# Remove existing symlinks
[ -L "$DST_PKG" ] && rm "$DST_PKG"
[ -L "$DST_PY" ] && rm "$DST_PY"

# Check for conflicts
if [ -e "$DST_PKG" ] && [ ! -L "$DST_PKG" ]; then
    if [ "$FORCE" = true ]; then
        echo "Removing existing $DST_PKG"
        rm -rf "$DST_PKG"
    else
        echo "Error: $DST_PKG exists and is not a symlink"
        echo "Use --force to replace it"
        exit 1
    fi
fi

if [ -e "$DST_PY" ] && [ ! -L "$DST_PY" ]; then
    if [ "$FORCE" = true ]; then
        echo "Removing existing $DST_PY"
        rm -f "$DST_PY"
    else
        echo "Error: $DST_PY exists and is not a symlink"
        echo "Use --force to replace it"
        exit 1
    fi
fi

# Install Python dependencies
install_deps() {
    echo ""
    echo "Installing dependencies..."

    # Install uv if not found
    if ! command -v uv &> /dev/null; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Add to PATH for current session
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # Install keyring CLI tool
    echo "Installing keyring..."
    uv tool install keyring 2>/dev/null || echo "keyring already installed"

    # Check for rsync and rclone
    echo ""
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
}

if [ "$FROM_GITHUB" = true ]; then
    # GitHub mode: download from GitHub
    REPO="binbinsh/kitten-trainsh"
    BRANCH="main"
    INSTALL_DIR="$KITTY_CONFIG/kitten-trainsh"

    echo "Installing kitten-trainsh from GitHub..."
    echo "  Repository: https://github.com/$REPO"
    echo "  Destination: $INSTALL_DIR"

    # Update or clone
    if [ -d "$INSTALL_DIR" ]; then
        if [ "$FORCE" = true ]; then
            echo "Removing existing installation..."
            rm -rf "$INSTALL_DIR"
            git clone --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR"
        else
            echo "Updating existing installation..."
            cd "$INSTALL_DIR"
            git pull origin "$BRANCH" || true
            cd - > /dev/null
        fi
    else
        git clone --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$INSTALL_DIR"
    fi

    # Create symlinks
    ln -s "$INSTALL_DIR/trainsh" "$DST_PKG"
    ln -s "$INSTALL_DIR/trainsh.py" "$DST_PY"

    echo ""
    echo "Created symlinks:"
    echo "  $DST_PKG -> $INSTALL_DIR/trainsh"
    echo "  $DST_PY -> $INSTALL_DIR/trainsh.py"
else
    # Default: symlink from current directory
    PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
    TRAINSH_PKG="$PROJECT_DIR/trainsh"
    TRAINSH_PY="$PROJECT_DIR/trainsh.py"

    if [ ! -d "$TRAINSH_PKG" ]; then
        echo "Error: trainsh/ directory not found in $PROJECT_DIR"
        echo "Use --github to install from GitHub instead."
        exit 1
    fi

    if [ ! -f "$TRAINSH_PY" ]; then
        echo "Error: trainsh.py not found in $PROJECT_DIR"
        echo "Use --github to install from GitHub instead."
        exit 1
    fi

    echo "Installing from local directory..."
    echo "  Source: $PROJECT_DIR"

    ln -s "$TRAINSH_PKG" "$DST_PKG"
    ln -s "$TRAINSH_PY" "$DST_PY"

    echo ""
    echo "Created symlinks:"
    echo "  $DST_PKG -> $TRAINSH_PKG"
    echo "  $DST_PY -> $TRAINSH_PY"
fi

# Install dependencies if requested
if [ "$INSTALL_DEPS" = true ]; then
    install_deps
fi

echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  kitty +kitten trainsh --help"
echo "  kitty +kitten trainsh host list"
echo "  kitty +kitten trainsh vast list"
echo ""
printf "\033[1;31mTip: Add an alias for shorter commands:\033[0m\n"
echo ""
printf "  \033[1;31m# Add this to ~/.zshrc or ~/.bashrc:\033[0m\n"
printf "  \033[1;31malias trainsh='kitty +kitten trainsh'\033[0m\n"
