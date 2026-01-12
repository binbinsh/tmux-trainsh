# tmux-trainsh SFTP browser service
# Remote file browsing via SSH

import shlex
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

from .ssh import SSHClient


@dataclass
class FileEntry:
    """Represents a file or directory entry."""
    name: str
    path: str
    is_dir: bool
    size: int = 0
    modified: Optional[datetime] = None
    permissions: str = ""
    owner: str = ""
    group: str = ""

    @property
    def display_size(self) -> str:
        """Get human-readable file size."""
        if self.is_dir:
            return "<DIR>"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if self.size < 1024:
                return f"{self.size:.1f} {unit}"
            self.size /= 1024
        return f"{self.size:.1f} PB"

    @property
    def icon(self) -> str:
        """Get icon for file type."""
        if self.is_dir:
            return "📁"
        ext = self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""
        icons = {
            "py": "🐍",
            "js": "📜",
            "ts": "📜",
            "json": "📋",
            "yaml": "📋",
            "yml": "📋",
            "toml": "📋",
            "md": "📝",
            "txt": "📝",
            "sh": "🔧",
            "bash": "🔧",
            "zsh": "🔧",
            "zip": "📦",
            "tar": "📦",
            "gz": "📦",
            "jpg": "🖼️",
            "jpeg": "🖼️",
            "png": "🖼️",
            "gif": "🖼️",
            "pdf": "📕",
            "mp4": "🎬",
            "mp3": "🎵",
            "wav": "🎵",
        }
        return icons.get(ext, "📄")


class RemoteFileBrowser:
    """
    Remote file browser using SSH.

    Provides directory listing and navigation for remote hosts.
    """

    def __init__(self, ssh_client: SSHClient):
        """
        Initialize the remote file browser.

        Args:
            ssh_client: SSH client for remote operations
        """
        self.ssh = ssh_client
        self.cache: dict[str, List[FileEntry]] = {}
        self.current_path: str = "~"

    def list_directory(self, path: str = "~") -> List[FileEntry]:
        """
        List files in a remote directory.

        Args:
            path: Remote path to list

        Returns:
            List of FileEntry objects
        """
        # Expand ~ to actual home directory
        if path == "~":
            result = self.ssh.run("echo $HOME")
            if result.success:
                path = result.stdout.strip()

        # Use ls -la with specific format for parsing
        # Format: permissions links owner group size month day time name
        cmd = f"ls -la --time-style=long-iso {shlex.quote(path)} 2>/dev/null"
        result = self.ssh.run(cmd)

        if not result.success:
            return []

        return self._parse_ls_output(result.stdout, path)

    def _parse_ls_output(self, output: str, base_path: str) -> List[FileEntry]:
        """Parse ls -la output into FileEntry objects."""
        entries: List[FileEntry] = []
        lines = output.strip().split("\n")

        for line in lines:
            # Skip total line and empty lines
            if not line or line.startswith("total"):
                continue

            parts = line.split(None, 7)
            if len(parts) < 8:
                continue

            permissions = parts[0]
            owner = parts[2]
            group = parts[3]
            size_str = parts[4]
            date_str = parts[5]
            time_str = parts[6]
            name = parts[7]

            # Skip . and .. entries
            if name in (".", ".."):
                continue

            # Parse size
            try:
                size = int(size_str)
            except ValueError:
                size = 0

            # Parse date/time
            modified = None
            try:
                modified = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                pass

            # Determine if directory
            is_dir = permissions.startswith("d")

            # Build full path
            full_path = f"{base_path}/{name}" if not base_path.endswith("/") else f"{base_path}{name}"

            entries.append(FileEntry(
                name=name,
                path=full_path,
                is_dir=is_dir,
                size=size,
                modified=modified,
                permissions=permissions,
                owner=owner,
                group=group,
            ))

        # Sort: directories first, then alphabetically
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

        return entries

    def navigate(self, path: str) -> List[FileEntry]:
        """
        Navigate to a directory and list its contents.

        Args:
            path: Path to navigate to

        Returns:
            List of FileEntry objects in the directory
        """
        entries = self.list_directory(path)
        self.current_path = path
        self.cache[path] = entries
        return entries

    def go_up(self) -> List[FileEntry]:
        """
        Navigate to parent directory.

        Returns:
            List of FileEntry objects in parent directory
        """
        if self.current_path in ("/", "~"):
            return self.cache.get(self.current_path, [])

        # Get parent path
        parent = "/".join(self.current_path.rstrip("/").split("/")[:-1])
        if not parent:
            parent = "/"

        return self.navigate(parent)

    def get_file_info(self, path: str) -> Optional[FileEntry]:
        """
        Get detailed information about a single file.

        Args:
            path: Path to file

        Returns:
            FileEntry or None if not found
        """
        cmd = f"stat --format='%F|%s|%Y|%U|%G|%A' {shlex.quote(path)} 2>/dev/null"
        result = self.ssh.run(cmd)

        if not result.success:
            return None

        parts = result.stdout.strip().split("|")
        if len(parts) < 6:
            return None

        file_type, size_str, mtime_str, owner, group, permissions = parts

        is_dir = "directory" in file_type.lower()

        try:
            size = int(size_str)
        except ValueError:
            size = 0

        modified = None
        try:
            modified = datetime.fromtimestamp(int(mtime_str))
        except (ValueError, OSError):
            pass

        name = path.rsplit("/", 1)[-1]

        return FileEntry(
            name=name,
            path=path,
            is_dir=is_dir,
            size=size,
            modified=modified,
            permissions=permissions,
            owner=owner,
            group=group,
        )

    def read_file_head(self, path: str, lines: int = 50) -> str:
        """
        Read first N lines of a file.

        Args:
            path: Path to file
            lines: Number of lines to read

        Returns:
            File content
        """
        cmd = f"head -n {lines} {shlex.quote(path)} 2>/dev/null"
        result = self.ssh.run(cmd)
        return result.stdout if result.success else ""

    def get_home_directory(self) -> str:
        """Get the home directory path."""
        result = self.ssh.run("echo $HOME")
        if result.success:
            return result.stdout.strip()
        return "~"

    def path_exists(self, path: str) -> bool:
        """Check if a path exists."""
        result = self.ssh.run(f"test -e {shlex.quote(path)} && echo yes || echo no")
        return result.success and "yes" in result.stdout

    def get_disk_usage(self, path: str = ".") -> Optional[dict]:
        """
        Get disk usage information for a path.

        Args:
            path: Path to check

        Returns:
            Dictionary with total, used, available in bytes
        """
        cmd = f"df -B1 {shlex.quote(path)} 2>/dev/null | tail -1"
        result = self.ssh.run(cmd)

        if not result.success:
            return None

        parts = result.stdout.strip().split()
        if len(parts) < 4:
            return None

        try:
            return {
                "total": int(parts[1]),
                "used": int(parts[2]),
                "available": int(parts[3]),
            }
        except (ValueError, IndexError):
            return None
