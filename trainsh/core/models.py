# tmux-trainsh data models

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


# ============================================================================
# Host Models
# ============================================================================


class HostType(Enum):
    """Type of host connection."""
    SSH = "ssh"
    VASTAI = "vastai"
    COLAB = "colab"
    LOCAL = "local"


class AuthMethod(Enum):
    """SSH authentication method."""
    PASSWORD = "password"
    KEY = "key"
    AGENT = "agent"


@dataclass
class GPUInfo:
    """GPU information for a host."""
    name: str
    memory_gb: float
    utilization: Optional[float] = None
    temperature: Optional[float] = None


@dataclass
class DiskInfo:
    """Disk information for a host."""
    mount_point: str
    total_gb: float
    used_gb: float
    free_gb: float


@dataclass
class HostSystemInfo:
    """System information for a remote host."""
    os: Optional[str] = None
    kernel: Optional[str] = None
    arch: Optional[str] = None
    hostname: Optional[str] = None
    cpu_model: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[float] = None
    gpu_info: Optional[List[GPUInfo]] = None
    disk_info: Optional[List[DiskInfo]] = None
    disk_total_gb: Optional[float] = None
    disk_used_gb: Optional[float] = None
    disk_avail_gb: Optional[float] = None
    uptime: Optional[str] = None
    cuda_version: Optional[str] = None
    python_version: Optional[str] = None
    public_ip: Optional[str] = None
    last_updated: Optional[datetime] = None


@dataclass
class Host:
    """Represents a remote host (SSH, Vast.ai, Colab, or Local)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    type: HostType = HostType.SSH
    hostname: str = ""
    port: int = 22
    username: str = ""
    auth_method: AuthMethod = AuthMethod.KEY
    ssh_key_path: Optional[str] = None
    jump_host: Optional[str] = None
    env_vars: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_connected_at: Optional[datetime] = None
    is_favorite: bool = False
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    # Vast.ai specific fields
    vast_instance_id: Optional[str] = None
    vast_template_id: Optional[str] = None
    vast_template_name: Optional[str] = None
    vast_status: Optional[str] = None
    gpu_count: Optional[int] = None
    disk_gb: Optional[int] = None
    hourly_rate: Optional[float] = None
    total_cost: Optional[float] = None

    # Cached system info
    system_info: Optional[HostSystemInfo] = None

    @property
    def display_name(self) -> str:
        """Get display name for the host."""
        if self.type == HostType.VASTAI and self.vast_instance_id:
            return f"Vast.ai #{self.vast_instance_id}"
        if self.name:
            return self.name
        return f"{self.username}@{self.hostname}" if self.username else self.hostname

    @property
    def ssh_spec(self) -> str:
        """Get SSH connection spec string."""
        user_part = f"{self.username}@" if self.username else ""
        port_part = f" -p {self.port}" if self.port != 22 else ""
        return f"{user_part}{self.hostname}{port_part}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "auth_method": self.auth_method.value,
            "ssh_key_path": self.ssh_key_path,
            "jump_host": self.jump_host,
            "env_vars": self.env_vars,
            "is_favorite": self.is_favorite,
            "tags": self.tags,
            "notes": self.notes,
            "vast_instance_id": self.vast_instance_id,
            "vast_template_id": self.vast_template_id,
            "vast_template_name": self.vast_template_name,
            "vast_status": self.vast_status,
            "gpu_count": self.gpu_count,
            "disk_gb": self.disk_gb,
            "hourly_rate": self.hourly_rate,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Host":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            type=HostType(data.get("type", "ssh")),
            hostname=data.get("hostname", ""),
            port=data.get("port", 22),
            username=data.get("username", ""),
            auth_method=AuthMethod(data.get("auth_method", "key")),
            ssh_key_path=data.get("ssh_key_path"),
            jump_host=data.get("jump_host"),
            env_vars=data.get("env_vars", {}),
            is_favorite=data.get("is_favorite", False),
            tags=data.get("tags", []),
            notes=data.get("notes", ""),
            vast_instance_id=data.get("vast_instance_id"),
            vast_template_id=data.get("vast_template_id"),
            vast_template_name=data.get("vast_template_name"),
            vast_status=data.get("vast_status"),
            gpu_count=data.get("gpu_count"),
            disk_gb=data.get("disk_gb"),
            hourly_rate=data.get("hourly_rate"),
        )


# ============================================================================
# Storage Models
# ============================================================================


class StorageType(Enum):
    """Type of storage backend."""
    LOCAL = "local"
    SSH = "ssh"
    GOOGLE_DRIVE = "gdrive"
    R2 = "r2"
    B2 = "b2"
    GCS = "gcs"
    S3 = "s3"
    SMB = "smb"

    @property
    def rclone_type(self) -> str:
        """Get rclone remote type."""
        mapping = {
            StorageType.LOCAL: "local",
            StorageType.SSH: "sftp",
            StorageType.GOOGLE_DRIVE: "drive",
            StorageType.R2: "s3",
            StorageType.B2: "b2",
            StorageType.GCS: "google cloud storage",
            StorageType.S3: "s3",
            StorageType.SMB: "smb",
        }
        return mapping.get(self, "local")


@dataclass
class Storage:
    """Represents a storage backend."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    type: StorageType = StorageType.LOCAL
    config: Dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "config": self.config,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Storage":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            type=StorageType(data.get("type", "local")),
            config=data.get("config", {}),
            is_default=data.get("is_default", False),
        )


# ============================================================================
# Recipe Models
# ============================================================================


class OperationType(Enum):
    """Types of recipe operations."""
    # Command execution
    RUN_COMMANDS = "runCommands"
    SIMPLE_COMMANDS = "simpleCommands"

    # File transfer
    TRANSFER = "transfer"

    # Git operations
    GIT_CLONE = "gitClone"
    GIT_PULL = "gitPull"

    # Python environment (uv only)
    UV_RUN = "uvRun"

    # Vast.ai operations
    VAST_START = "vastStart"
    VAST_STOP = "vastStop"
    VAST_RM = "vastRm"
    VAST_SEARCH = "vastSearch"
    VAST_CREATE = "vastCreate"
    VAST_WAIT_READY = "vastWaitReady"

    # SSH/Host operations
    SSH_CONNECT = "sshConnect"
    HOST_TEST = "hostTest"

    # Tmux operations
    TMUX_NEW = "tmuxNew"
    TMUX_SEND = "tmuxSend"
    TMUX_CAPTURE = "tmuxCapture"
    TMUX_KILL = "tmuxKill"

    # Google Drive operations
    GDRIVE_MOUNT = "gdriveMount"
    GDRIVE_UNMOUNT = "gdriveUnmount"

    # HuggingFace operations
    HF_DOWNLOAD = "hfDownload"

    # Pricing operations
    FETCH_EXCHANGE_RATES = "fetchExchangeRates"
    CALCULATE_COST = "calculateCost"

    # Flow control
    SLEEP = "sleep"
    WAIT_CONDITION = "waitCondition"
    ASSERT = "assert"
    WAIT_FOR_FILE = "waitForFile"
    WAIT_FOR_PORT = "waitForPort"

    # Variables
    SET_VAR = "setVar"
    GET_VALUE = "getValue"
    SET_ENV = "setEnv"

    # HTTP
    HTTP_REQUEST = "httpRequest"

    # Notifications
    NOTIFY = "notify"

    # Composite
    GROUP = "group"

    # Utility
    CUSTOM = "custom"


class TmuxMode(Enum):
    """Tmux session mode."""
    NONE = "none"
    NEW = "new"
    EXISTING = "existing"


class TransferDirection(Enum):
    """Direction of file transfer."""
    UPLOAD = "upload"
    DOWNLOAD = "download"
    SYNC = "sync"


class HttpMethod(Enum):
    """HTTP request methods."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class NotifyLevel(Enum):
    """Notification levels."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class GroupMode(Enum):
    """Group execution mode."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class RecipeStep:
    """A single step in a recipe."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    operation: OperationType = OperationType.RUN_COMMANDS
    params: Dict[str, Any] = field(default_factory=dict)
    condition: Optional[Dict[str, Any]] = None
    depends_on: List[str] = field(default_factory=list)
    retry_count: int = 0
    timeout: Optional[float] = None
    interactive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "operation": self.operation.value,
            "params": self.params,
            "condition": self.condition,
            "depends_on": self.depends_on,
            "retry_count": self.retry_count,
            "timeout": self.timeout,
            "interactive": self.interactive,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecipeStep":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            operation=OperationType(data.get("operation", "runCommands")),
            params=data.get("params", {}),
            condition=data.get("condition"),
            depends_on=data.get("depends_on", []),
            retry_count=data.get("retry_count", 0),
            timeout=data.get("timeout"),
            interactive=data.get("interactive", False),
        )


@dataclass
class Recipe:
    """A recipe containing multiple steps to execute."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    steps: List[RecipeStep] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    version: int = 1
    folder_id: Optional[str] = None
    is_favorite: bool = False
    is_archived: bool = False
    is_template: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "variables": self.variables,
            "tags": self.tags,
            "version": self.version,
            "is_template": self.is_template,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipe":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=[RecipeStep.from_dict(s) for s in data.get("steps", [])],
            variables=data.get("variables", {}),
            tags=data.get("tags", []),
            version=data.get("version", 1),
            is_template=data.get("is_template", False),
        )


# ============================================================================
# Execution Models
# ============================================================================


class StepStatus(Enum):
    """Status of a recipe step execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ExecutionStatus(Enum):
    """Status of a recipe execution."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_id: str
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    exit_code: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class Execution:
    """Tracks the execution of a recipe."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recipe_id: str = ""
    host_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    current_step_index: int = 0
    step_results: List[StepResult] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    logs: str = ""

    def append_log(self, message: str) -> None:
        """Append to execution logs."""
        self.logs += message


# ============================================================================
# Transfer Models
# ============================================================================


class TransferStatus(Enum):
    """Status of a file transfer."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransferOperation(Enum):
    """Type of transfer operation."""
    COPY = "copy"
    MOVE = "move"
    SYNC = "sync"
    SYNC_NO_DELETE = "syncNoDelete"


@dataclass
class TransferEndpoint:
    """Represents a source or destination for file transfer."""
    type: str  # "local", "host", "storage"
    path: str
    host_id: Optional[str] = None
    storage_id: Optional[str] = None


@dataclass
class Transfer:
    """Tracks a file transfer operation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: TransferEndpoint = field(default_factory=lambda: TransferEndpoint("local", ""))
    destination: TransferEndpoint = field(default_factory=lambda: TransferEndpoint("local", ""))
    status: TransferStatus = TransferStatus.PENDING
    operation: TransferOperation = TransferOperation.COPY
    progress: float = 0.0
    bytes_transferred: int = 0
    total_bytes: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def formatted_progress(self) -> str:
        """Get formatted progress string."""

        def format_bytes(b: int) -> str:
            for unit in ["B", "KB", "MB", "GB", "TB"]:
                if b < 1024:
                    return f"{b:.1f} {unit}"
                b /= 1024
            return f"{b:.1f} PB"

        return f"{format_bytes(self.bytes_transferred)} / {format_bytes(self.total_bytes)}"


# ============================================================================
# Vast.ai Models
# ============================================================================


@dataclass
class VastInstance:
    """Represents a Vast.ai instance."""
    id: int
    actual_status: Optional[str] = None
    cur_state: Optional[str] = None
    next_state: Optional[str] = None
    intended_status: Optional[str] = None
    gpu_name: Optional[str] = None
    gpu_arch: Optional[str] = None
    gpu_totalram: Optional[float] = None
    gpu_ram: Optional[float] = None
    gpu_util: Optional[float] = None
    gpu_temp: Optional[float] = None
    num_gpus: Optional[int] = None
    dph_total: Optional[float] = None
    dph_base: Optional[float] = None
    storage_cost: Optional[float] = None
    storage_total_cost: Optional[float] = None
    disk_space: Optional[float] = None
    disk_usage: Optional[float] = None
    ssh_idx: Optional[str] = None
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    public_ipaddr: Optional[str] = None
    direct_port_start: Optional[int] = None
    direct_port_end: Optional[int] = None
    label: Optional[str] = None
    template_name: Optional[str] = None
    image_uuid: Optional[str] = None
    cpu_name: Optional[str] = None
    cpu_cores: Optional[int] = None
    cpu_ram: Optional[float] = None
    machine_id: Optional[int] = None
    host_id: Optional[int] = None
    start_date: Optional[float] = None
    end_date: Optional[float] = None
    duration: Optional[float] = None
    geolocation: Optional[str] = None
    reliability2: Optional[float] = None
    country_code: Optional[str] = None

    @property
    def is_running(self) -> bool:
        """Check if instance is running."""
        return (self.actual_status or "").lower() == "running"

    @property
    def display_name(self) -> str:
        """Get display name for the instance."""
        return f"Vast.ai #{self.id}"

    @property
    def ssh_proxy_command(self) -> Optional[str]:
        """Get proxy SSH command."""
        if self.ssh_host and self.ssh_port:
            return f"ssh -p {self.ssh_port} root@{self.ssh_host}"
        return None

    @property
    def ssh_direct_command(self) -> Optional[str]:
        """Get direct SSH command (if available)."""
        if self.public_ipaddr and self.direct_port_start:
            return f"ssh -p {self.direct_port_start} root@{self.public_ipaddr}"
        return None

    @property
    def hourly_rate(self) -> float:
        """Get hourly rate."""
        return self.dph_total or 0.0

    @property
    def gpu_memory_gb(self) -> float:
        """Get GPU memory in GB."""
        if self.gpu_ram:
            return self.gpu_ram / 1024.0
        return 0.0

    @property
    def status_color(self) -> str:
        """Get status color for display."""
        status = (self.actual_status or "").lower()
        if status == "running":
            return "green"
        elif status in ("loading", "starting"):
            return "yellow"
        elif status in ("stopped", "exited"):
            return "gray"
        return "gray"


@dataclass
class VastOffer:
    """Represents a Vast.ai GPU offer."""
    id: int
    gpu_name: Optional[str] = None
    num_gpus: Optional[int] = None
    gpu_ram: Optional[float] = None
    dph_total: Optional[float] = None
    reliability2: Optional[float] = None
    inet_down: Optional[float] = None
    inet_up: Optional[float] = None
    cpu_cores: Optional[int] = None
    cpu_ram: Optional[float] = None

    @property
    def display_gpu_ram(self) -> str:
        """Get formatted GPU RAM."""
        if self.gpu_ram:
            return f"{self.gpu_ram / 1024:.0f} GB"
        return "N/A"

    @property
    def display_price(self) -> str:
        """Get formatted price."""
        if self.dph_total:
            return f"${self.dph_total:.3f}/hr"
        return "N/A"
