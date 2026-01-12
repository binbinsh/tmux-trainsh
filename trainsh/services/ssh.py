# tmux-trainsh SSH service
# SSH connection management

import subprocess
import os
from typing import Optional, List, Tuple
from dataclasses import dataclass

from ..core.models import Host, AuthMethod


@dataclass
class SSHResult:
    """Result of an SSH command execution."""
    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class SSHClient:
    """
    SSH client wrapper for executing remote commands.

    Uses the system ssh command for maximum compatibility.
    """

    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: Optional[str] = None,
        key_path: Optional[str] = None,
        jump_host: Optional[str] = None,
        connect_timeout: int = 10,
    ):
        """
        Initialize the SSH client.

        Args:
            hostname: Remote host address
            port: SSH port
            username: SSH username
            key_path: Path to SSH private key
            jump_host: Jump/bastion host for ProxyJump
            connect_timeout: Connection timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.username = username
        self.key_path = key_path
        self.jump_host = jump_host
        self.connect_timeout = connect_timeout

    @classmethod
    def from_host(cls, host: Host) -> "SSHClient":
        """Create an SSH client from a Host object."""
        return cls(
            hostname=host.hostname,
            port=host.port,
            username=host.username,
            key_path=host.ssh_key_path,
            jump_host=host.jump_host,
        )

    def _build_ssh_args(self, command: Optional[str] = None) -> List[str]:
        """Build SSH command arguments."""
        args = ["ssh"]

        # Connection options
        args.extend(["-o", "StrictHostKeyChecking=accept-new"])
        args.extend(["-o", "BatchMode=yes"])
        args.extend(["-o", f"ConnectTimeout={self.connect_timeout}"])

        # Port
        if self.port != 22:
            args.extend(["-p", str(self.port)])

        # Key file
        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        # Jump host
        if self.jump_host:
            args.extend(["-J", self.jump_host])

        # User@host
        if self.username:
            args.append(f"{self.username}@{self.hostname}")
        else:
            args.append(self.hostname)

        # Command
        if command:
            args.append(command)

        return args

    def run(
        self,
        command: str,
        timeout: Optional[int] = None,
        capture_output: bool = True,
    ) -> SSHResult:
        """
        Execute a command on the remote host.

        Args:
            command: The command to execute
            timeout: Command timeout in seconds
            capture_output: Whether to capture stdout/stderr

        Returns:
            SSHResult with exit code and output
        """
        args = self._build_ssh_args(command)

        try:
            result = subprocess.run(
                args,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
            return SSHResult(
                exit_code=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except subprocess.TimeoutExpired:
            return SSHResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
            )
        except Exception as e:
            return SSHResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )

    def test_connection(self) -> bool:
        """
        Test if the SSH connection works.

        Returns:
            True if connection successful
        """
        result = self.run("echo 'connected'", timeout=15)
        return result.success and "connected" in result.stdout

    def get_ssh_command(self) -> str:
        """
        Get the SSH command for manual connection.

        Returns:
            SSH command string
        """
        args = self._build_ssh_args()
        return " ".join(args)

    def upload_file(
        self,
        local_path: str,
        remote_path: str,
        recursive: bool = False,
    ) -> SSHResult:
        """
        Upload a file or directory using scp.

        Args:
            local_path: Local file/directory path
            remote_path: Remote destination path
            recursive: Copy directories recursively

        Returns:
            SSHResult with exit code and output
        """
        args = ["scp"]

        if recursive:
            args.append("-r")

        args.extend(["-o", "StrictHostKeyChecking=accept-new"])

        if self.port != 22:
            args.extend(["-P", str(self.port)])

        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        args.append(os.path.expanduser(local_path))

        if self.username:
            args.append(f"{self.username}@{self.hostname}:{remote_path}")
        else:
            args.append(f"{self.hostname}:{remote_path}")

        try:
            result = subprocess.run(args, capture_output=True, text=True)
            return SSHResult(
                exit_code=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except Exception as e:
            return SSHResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )

    def download_file(
        self,
        remote_path: str,
        local_path: str,
        recursive: bool = False,
    ) -> SSHResult:
        """
        Download a file or directory using scp.

        Args:
            remote_path: Remote file/directory path
            local_path: Local destination path
            recursive: Copy directories recursively

        Returns:
            SSHResult with exit code and output
        """
        args = ["scp"]

        if recursive:
            args.append("-r")

        args.extend(["-o", "StrictHostKeyChecking=accept-new"])

        if self.port != 22:
            args.extend(["-P", str(self.port)])

        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        if self.username:
            args.append(f"{self.username}@{self.hostname}:{remote_path}")
        else:
            args.append(f"{self.hostname}:{remote_path}")

        args.append(os.path.expanduser(local_path))

        try:
            result = subprocess.run(args, capture_output=True, text=True)
            return SSHResult(
                exit_code=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except Exception as e:
            return SSHResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )


def get_system_info_script() -> str:
    """
    Get a shell script to collect system information from a remote host.

    Returns:
        Shell script as a string
    """
    return '''
    echo "=== SYSTEM INFO ==="
    echo "OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d'"' -f2 || uname -s)"
    echo "KERNEL: $(uname -r)"
    echo "ARCH: $(uname -m)"
    echo "HOSTNAME: $(hostname)"
    echo "CPU: $(grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d':' -f2 | xargs || sysctl -n machdep.cpu.brand_string 2>/dev/null)"
    echo "CPU_CORES: $(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)"
    echo "MEMORY_GB: $(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo 'N/A')"
    echo "UPTIME: $(uptime -p 2>/dev/null || uptime)"

    if command -v nvidia-smi &> /dev/null; then
        echo "=== GPU INFO ==="
        nvidia-smi --query-gpu=name,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null || echo "N/A"
    fi

    if command -v python3 &> /dev/null; then
        echo "PYTHON: $(python3 --version 2>&1)"
    fi

    if command -v nvcc &> /dev/null; then
        echo "CUDA: $(nvcc --version 2>&1 | grep release | sed 's/.*release //' | cut -d',' -f1)"
    fi

    echo "PUBLIC_IP: $(curl -s ifconfig.me 2>/dev/null || echo 'N/A')"
    '''
