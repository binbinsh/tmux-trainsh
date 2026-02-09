# tmux-trainsh SSH service
# SSH connection management

import subprocess
import os
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass
from urllib.parse import urlparse

from ..core.models import Host


@dataclass
class SSHResult:
    """Result of an SSH command execution."""
    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class SSHConnectionTarget:
    """One concrete SSH connection target/candidate."""
    hostname: str
    port: int = 22
    proxy_command: Optional[str] = None
    jump_host: Optional[str] = None
    source: str = "primary"


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
        proxy_command: Optional[str] = None,
        connection_targets: Optional[List[SSHConnectionTarget]] = None,
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
            proxy_command: OpenSSH ProxyCommand value
            connection_targets: Ordered connection candidates
            connect_timeout: Connection timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.username = username
        self.key_path = key_path
        self.jump_host = jump_host
        self.proxy_command = proxy_command
        self.connect_timeout = connect_timeout
        self.connection_targets = connection_targets or [
            SSHConnectionTarget(
                hostname=hostname,
                port=port,
                proxy_command=proxy_command,
                jump_host=jump_host,
                source="primary",
            )
        ]

    @classmethod
    def from_host(cls, host: Host) -> "SSHClient":
        """Create an SSH client from a Host object."""
        env_vars = host.env_vars or {}
        primary = SSHConnectionTarget(
            hostname=host.hostname,
            port=host.port,
            proxy_command=cls._resolve_proxy_command(host, env_vars),
            jump_host=host.jump_host,
            source="primary",
        )
        targets = [primary]
        targets.extend(cls._parse_connection_candidates(host, env_vars))
        return cls(
            hostname=host.hostname,
            port=host.port,
            username=host.username,
            key_path=host.ssh_key_path,
            jump_host=host.jump_host,
            proxy_command=primary.proxy_command,
            connection_targets=targets,
        )

    @staticmethod
    def _build_cloudflared_proxy_command(
        env_vars: dict,
        default_hostname: str,
    ) -> Optional[str]:
        """Build ProxyCommand from cloudflared host settings."""
        tunnel_type = str(env_vars.get("tunnel_type", "")).strip().lower()
        if tunnel_type != "cloudflared":
            return None

        cloudflared_hostname = str(env_vars.get("cloudflared_hostname", default_hostname)).strip()
        if not cloudflared_hostname:
            return None

        cloudflared_bin = str(env_vars.get("cloudflared_bin", "cloudflared")).strip() or "cloudflared"
        return f"{cloudflared_bin} access ssh --hostname {cloudflared_hostname}"

    @classmethod
    def _resolve_proxy_command(cls, host: Host, env_vars: dict) -> Optional[str]:
        manual_proxy = str(env_vars.get("proxy_command", "")).strip()
        if manual_proxy:
            return manual_proxy
        return cls._build_cloudflared_proxy_command(env_vars, host.hostname)

    @classmethod
    def _parse_connection_candidates(cls, host: Host, env_vars: dict) -> List[SSHConnectionTarget]:
        """Parse extra candidates from env var connection_candidates."""
        raw = env_vars.get("connection_candidates", "")
        candidates: List[SSHConnectionTarget] = []
        entries: List[Any]
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = [raw]
        else:
            entries = [part.strip() for part in str(raw).split(",") if part.strip()]

        for entry in entries:
            parsed = cls._parse_connection_candidate_entry(
                entry=entry,
                host=host,
                env_vars=env_vars,
            )
            if parsed is not None:
                candidates.append(parsed)

        # Dedupe while preserving order.
        seen = set()
        deduped: List[SSHConnectionTarget] = []
        for candidate in candidates:
            key = (candidate.hostname, candidate.port, candidate.proxy_command, candidate.jump_host)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    @classmethod
    def _parse_connection_candidate_entry(
        cls,
        entry: Any,
        host: Host,
        env_vars: dict,
    ) -> Optional[SSHConnectionTarget]:
        """Parse one candidate entry (string token or object)."""
        if isinstance(entry, dict):
            return cls._parse_connection_candidate_dict(entry, host, env_vars)

        token = str(entry).strip()
        if not token:
            return None
        return cls._parse_connection_candidate_token(
            token=token,
            host=host,
            env_vars=env_vars,
        )

    @classmethod
    def _parse_connection_candidate_dict(
        cls,
        entry: dict,
        host: Host,
        env_vars: dict,
    ) -> Optional[SSHConnectionTarget]:
        """Parse structured candidate config."""
        candidate_type = str(entry.get("type", "ssh")).strip().lower()

        if candidate_type == "cloudflared":
            cloudflared_hostname = (
                str(entry.get("hostname", "")).strip()
                or str(entry.get("cloudflared_hostname", "")).strip()
            )
            if not cloudflared_hostname:
                return None

            cloudflared_env = dict(env_vars)
            cloudflared_env["tunnel_type"] = "cloudflared"
            cloudflared_env["cloudflared_hostname"] = cloudflared_hostname
            cloudflared_bin = str(entry.get("cloudflared_bin", "")).strip()
            if cloudflared_bin:
                cloudflared_env["cloudflared_bin"] = cloudflared_bin

            target_hostname = str(entry.get("target_hostname", host.hostname)).strip() or host.hostname

            port_raw = entry.get("target_port", entry.get("port", host.port))
            try:
                target_port = int(port_raw)
            except (TypeError, ValueError):
                target_port = host.port

            return SSHConnectionTarget(
                hostname=target_hostname,
                port=target_port,
                proxy_command=cls._build_cloudflared_proxy_command(cloudflared_env, target_hostname),
                source="candidate:dict:cloudflared",
            )

        candidate_hostname = str(entry.get("hostname", "")).strip()
        if not candidate_hostname:
            return None

        port_raw = entry.get("port", 22)
        try:
            candidate_port = int(port_raw)
        except (TypeError, ValueError):
            candidate_port = 22

        proxy_command = str(entry.get("proxy_command", "")).strip() or None
        jump_host = str(entry.get("jump_host", "")).strip() or None
        return SSHConnectionTarget(
            hostname=candidate_hostname,
            port=candidate_port,
            proxy_command=proxy_command,
            jump_host=jump_host,
            source="candidate:dict:ssh",
        )

    @classmethod
    def _parse_connection_candidate_token(
        cls,
        token: str,
        host: Host,
        env_vars: dict,
    ) -> Optional[SSHConnectionTarget]:
        """Parse one connection candidate token."""
        token = token.strip()
        if not token:
            return None

        if token.startswith("ssh://"):
            parsed = urlparse(token)
            candidate_host = (parsed.hostname or "").strip()
            if not candidate_host:
                return None
            return SSHConnectionTarget(
                hostname=candidate_host,
                port=parsed.port or 22,
                source=f"candidate:{token}",
            )

        if token.startswith("cloudflared://"):
            parsed = urlparse(token)
            cloudflared_hostname = (parsed.hostname or "").strip() or parsed.path.strip("/")
            if not cloudflared_hostname:
                return None
            cloudflared_env = dict(env_vars)
            cloudflared_env["tunnel_type"] = "cloudflared"
            cloudflared_env["cloudflared_hostname"] = cloudflared_hostname
            return SSHConnectionTarget(
                hostname=host.hostname,
                port=host.port,
                proxy_command=cls._build_cloudflared_proxy_command(cloudflared_env, host.hostname),
                source=f"candidate:{token}",
            )

        return None

    def _get_connection_target(self, target: Optional[SSHConnectionTarget] = None) -> Tuple[str, int]:
        """Resolve final host/port."""
        chosen = target or self.connection_targets[0]
        return chosen.hostname, chosen.port

    def _get_jump_host_spec(self, target: Optional[SSHConnectionTarget] = None) -> Optional[str]:
        """Resolve jump host spec."""
        jump = target.jump_host if target else self.jump_host
        if not jump:
            return None
        return jump.strip()

    def _append_proxy_or_jump(self, args: List[str], target: Optional[SSHConnectionTarget] = None) -> None:
        """Append proxy/jump related SSH options."""
        proxy = target.proxy_command if target else self.proxy_command
        if proxy:
            args.extend(["-o", f"ProxyCommand={proxy}"])
            return

        jump_host_spec = self._get_jump_host_spec(target)
        if jump_host_spec:
            args.extend(["-J", jump_host_spec])

    def _build_ssh_args(
        self,
        command: Optional[str] = None,
        target: Optional[SSHConnectionTarget] = None,
    ) -> List[str]:
        """Build SSH command arguments."""
        args = ["ssh"]
        chosen = target or self.connection_targets[0]
        target_host, target_port = self._get_connection_target(chosen)

        # Connection options
        args.extend(["-o", "StrictHostKeyChecking=accept-new"])
        args.extend(["-o", "BatchMode=yes"])
        args.extend(["-o", f"ConnectTimeout={self.connect_timeout}"])

        # Port
        if target_port != 22:
            args.extend(["-p", str(target_port)])

        # Key file
        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        # Explicit ProxyCommand takes precedence over ProxyJump.
        self._append_proxy_or_jump(args, chosen)

        # User@host
        if self.username:
            args.append(f"{self.username}@{target_host}")
        else:
            args.append(target_host)

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
        last_result: Optional[SSHResult] = None
        for index, target in enumerate(self.connection_targets):
            args = self._build_ssh_args(command, target=target)

            try:
                result = subprocess.run(
                    args,
                    capture_output=capture_output,
                    text=True,
                    timeout=timeout,
                )
                ssh_result = SSHResult(
                    exit_code=result.returncode,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                )
            except subprocess.TimeoutExpired:
                ssh_result = SSHResult(
                    exit_code=-1,
                    stdout="",
                    stderr="Command timed out",
                )
            except Exception as e:
                ssh_result = SSHResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                )

            # OpenSSH returns 255 on connection/auth/proxy failures.
            # Retry next candidate only for that class of failures.
            if ssh_result.exit_code == 255 and index < len(self.connection_targets) - 1:
                last_result = ssh_result
                continue
            return ssh_result

        return last_result or SSHResult(exit_code=-1, stdout="", stderr="No connection candidates available")

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
        args = self._build_ssh_args(target=self.connection_targets[0])
        return " ".join(args)

    def connect_interactive(self) -> int:
        """
        Open an interactive SSH session using candidate fallback.

        Returns:
            Process exit code
        """
        last_code = 255
        for index, target in enumerate(self.connection_targets):
            args = self._build_ssh_args(target=target)
            result = subprocess.run(args)
            last_code = result.returncode
            if result.returncode == 255 and index < len(self.connection_targets) - 1:
                continue
            return result.returncode
        return last_code

    def _build_scp_upload_args(
        self,
        local_path: str,
        remote_path: str,
        recursive: bool,
        target: SSHConnectionTarget,
    ) -> List[str]:
        target_host, target_port = self._get_connection_target(target)
        args = ["scp"]

        if recursive:
            args.append("-r")

        args.extend(["-o", "StrictHostKeyChecking=accept-new"])

        if target_port != 22:
            args.extend(["-P", str(target_port)])

        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        self._append_proxy_or_jump(args, target)
        args.append(os.path.expanduser(local_path))
        if self.username:
            args.append(f"{self.username}@{target_host}:{remote_path}")
        else:
            args.append(f"{target_host}:{remote_path}")
        return args

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
        last_result: Optional[SSHResult] = None
        for index, target in enumerate(self.connection_targets):
            args = self._build_scp_upload_args(local_path, remote_path, recursive, target)
            try:
                result = subprocess.run(args, capture_output=True, text=True)
                ssh_result = SSHResult(
                    exit_code=result.returncode,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                )
            except Exception as e:
                ssh_result = SSHResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                )

            if ssh_result.exit_code == 255 and index < len(self.connection_targets) - 1:
                last_result = ssh_result
                continue
            return ssh_result

        return last_result or SSHResult(exit_code=-1, stdout="", stderr="No connection candidates available")

    def _build_scp_download_args(
        self,
        remote_path: str,
        local_path: str,
        recursive: bool,
        target: SSHConnectionTarget,
    ) -> List[str]:
        target_host, target_port = self._get_connection_target(target)
        args = ["scp"]

        if recursive:
            args.append("-r")

        args.extend(["-o", "StrictHostKeyChecking=accept-new"])

        if target_port != 22:
            args.extend(["-P", str(target_port)])

        if self.key_path:
            key_path = os.path.expanduser(self.key_path)
            if os.path.exists(key_path):
                args.extend(["-i", key_path])

        self._append_proxy_or_jump(args, target)
        if self.username:
            args.append(f"{self.username}@{target_host}:{remote_path}")
        else:
            args.append(f"{target_host}:{remote_path}")
        args.append(os.path.expanduser(local_path))
        return args

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
        last_result: Optional[SSHResult] = None
        for index, target in enumerate(self.connection_targets):
            args = self._build_scp_download_args(remote_path, local_path, recursive, target)
            try:
                result = subprocess.run(args, capture_output=True, text=True)
                ssh_result = SSHResult(
                    exit_code=result.returncode,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                )
            except Exception as e:
                ssh_result = SSHResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                )

            if ssh_result.exit_code == 255 and index < len(self.connection_targets) - 1:
                last_result = ssh_result
                continue
            return ssh_result

        return last_result or SSHResult(exit_code=-1, stdout="", stderr="No connection candidates available")


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
