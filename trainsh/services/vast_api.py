# tmux-trainsh Vast.ai API client
# REST API client for Vast.ai GPU marketplace

import json
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import ssl

from ..constants import VAST_API_BASE
from ..core.models import VastInstance, VastOffer


class VastAPIError(Exception):
    """Exception raised for Vast.ai API errors."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Vast.ai API error ({status_code}): {message}")


class VastAPIClient:
    """
    Vast.ai REST API client.

    Provides methods to:
    - List, start, stop, remove instances
    - Search GPU offers
    - Create new instances
    - Manage SSH keys
    """

    def __init__(self, api_key: str):
        """
        Initialize the API client.

        Args:
            api_key: Vast.ai API key
        """
        self.api_key = api_key
        self.base_url = VAST_API_BASE

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the API.

        Args:
            endpoint: API endpoint (without base URL)
            method: HTTP method
            data: Request body data

        Returns:
            Parsed JSON response

        Raises:
            VastAPIError: If the API returns an error
        """
        url = f"{self.base_url}/{endpoint}/"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = None
        if data:
            body = json.dumps(data).encode("utf-8")

        # Create SSL context that allows unverified certificates (for testing)
        ctx = ssl.create_default_context()

        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, context=ctx) as response:
                response_data = response.read().decode("utf-8")
                if response_data:
                    return json.loads(response_data)
                return {}
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise VastAPIError(e.code, error_body)
        except URLError as e:
            raise VastAPIError(0, str(e.reason))

    # =========================================================================
    # Instance Operations
    # =========================================================================

    def list_instances(self) -> List[VastInstance]:
        """
        List all instances for the account.

        Returns:
            List of VastInstance objects
        """
        response = self._request("instances")
        instances = response.get("instances", [])
        return [self._parse_instance(i) for i in instances]

    def get_instance(self, instance_id: int) -> VastInstance:
        """
        Get details for a specific instance.

        Args:
            instance_id: The instance ID

        Returns:
            VastInstance object
        """
        response = self._request(f"instances/{instance_id}")
        return self._parse_instance(response.get("instances", {}))

    def start_instance(self, instance_id: int) -> None:
        """
        Start a stopped instance.

        Args:
            instance_id: The instance ID
        """
        self._request(
            f"instances/{instance_id}",
            method="PUT",
            data={"state": "running"},
        )

    def stop_instance(self, instance_id: int) -> None:
        """
        Stop a running instance.

        Args:
            instance_id: The instance ID
        """
        self._request(
            f"instances/{instance_id}",
            method="PUT",
            data={"state": "stopped"},
        )

    def rm_instance(self, instance_id: int) -> None:
        """
        Remove an instance (terminate lease).

        Args:
            instance_id: The instance ID
        """
        self._request(f"instances/{instance_id}", method="DELETE")

    def reboot_instance(self, instance_id: int) -> None:
        """
        Reboot an instance container (keeps GPU priority).

        Args:
            instance_id: The instance ID
        """
        self._request(f"instances/reboot/{instance_id}", method="PUT")

    def recycle_instance(self, instance_id: int) -> None:
        """
        Recycle an instance (fresh image, keeps GPU priority).

        Args:
            instance_id: The instance ID
        """
        self._request(f"instances/recycle/{instance_id}", method="PUT")

    def label_instance(self, instance_id: int, label: str) -> None:
        """
        Set a label on an instance.

        Args:
            instance_id: The instance ID
            label: The label text
        """
        self._request(
            f"instances/{instance_id}",
            method="PUT",
            data={"label": label},
        )

    def execute_command(self, instance_id: int, command: str) -> Dict[str, Any]:
        """
        Execute a command on an instance.

        Args:
            instance_id: The instance ID
            command: The command to execute

        Returns:
            Command execution response
        """
        return self._request(
            f"instances/{instance_id}/command",
            method="POST",
            data={"command": command},
        )

    # =========================================================================
    # Offer Operations
    # =========================================================================

    def search_offers(
        self,
        gpu_name: Optional[str] = None,
        num_gpus: Optional[int] = None,
        min_gpu_ram: Optional[float] = None,
        max_dph: Optional[float] = None,
        limit: int = 50,
    ) -> List[VastOffer]:
        """
        Search for available GPU offers.

        Args:
            gpu_name: Filter by GPU name (e.g., "RTX_4090", "A100")
            num_gpus: Minimum number of GPUs
            min_gpu_ram: Minimum GPU RAM in GB
            max_dph: Maximum dollars per hour
            limit: Maximum number of results

        Returns:
            List of VastOffer objects
        """
        query: Dict[str, Any] = {
            "rentable": {"eq": True},
            "rented": {"eq": False},
        }

        if gpu_name:
            query["gpu_name"] = {"eq": gpu_name.upper()}
        if num_gpus and num_gpus > 0:
            query["num_gpus"] = {"gte": num_gpus}
        if min_gpu_ram and min_gpu_ram > 0:
            query["gpu_ram"] = {"gte": min_gpu_ram * 1024}  # Convert GB to MB
        if max_dph and max_dph > 0:
            query["dph_total"] = {"lte": max_dph}

        response = self._request(
            "search/asks",
            method="PUT",
            data={"q": query, "limit": limit},
        )

        offers = response.get("offers", [])
        return [self._parse_offer(o) for o in offers]

    def create_instance(
        self,
        offer_id: int,
        image: str,
        disk: float = 50,
        label: Optional[str] = None,
        onstart: Optional[str] = None,
        direct: bool = False,
    ) -> int:
        """
        Create a new instance from an offer.

        Args:
            offer_id: The offer ID to rent
            image: Docker image to use
            disk: Disk space in GB
            label: Optional label for the instance
            onstart: Optional startup script
            direct: Use direct SSH connection

        Returns:
            The new instance/contract ID
        """
        data = {
            "client_id": "me",
            "image": image,
            "env": {},
            "disk": disk,
            "label": label or "",
            "onstart": onstart or "",
            "runtype": "ssh_direc ssh_proxy" if direct else "ssh_proxy",
            "cancel_unavail": False,
            "force": False,
        }

        response = self._request(f"asks/{offer_id}", method="PUT", data=data)
        new_contract = response.get("new_contract")

        if not new_contract:
            raise VastAPIError(0, "No contract ID returned")

        return new_contract

    # =========================================================================
    # SSH Key Operations
    # =========================================================================

    def list_ssh_keys(self) -> List[Dict[str, Any]]:
        """
        List SSH keys registered with the account.

        Returns:
            List of SSH key objects
        """
        response = self._request("ssh")
        # API may return list directly or dict with ssh_keys
        if isinstance(response, list):
            return response
        return response.get("ssh_keys", [])

    def add_ssh_key(self, public_key: str, label: Optional[str] = None) -> None:
        """
        Add an SSH key to the account.

        Args:
            public_key: The public key content
            label: Optional label for the key
        """
        from datetime import datetime

        key_label = label or f"tmux-trainsh-{datetime.now().timestamp():.0f}"
        self._request(
            "ssh",
            method="POST",
            data={"ssh_key": public_key, "label": key_label},
        )

    def delete_ssh_key(self, key_id: int) -> None:
        """
        Delete an SSH key from the account.

        Args:
            key_id: The SSH key ID
        """
        self._request(f"ssh/{key_id}", method="DELETE")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_ssh_command(self, instance: VastInstance) -> Optional[str]:
        """
        Get SSH command for connecting to an instance.

        Args:
            instance: The VastInstance object

        Returns:
            SSH command string, or None if not available
        """
        if not instance.ssh_host or not instance.ssh_port:
            return None
        return f"ssh -p {instance.ssh_port} root@{instance.ssh_host}"

    def _parse_instance(self, data: Dict[str, Any]) -> VastInstance:
        """Parse API response into VastInstance."""
        return VastInstance(
            id=data.get("id", 0),
            actual_status=data.get("actual_status"),
            cur_state=data.get("cur_state"),
            next_state=data.get("next_state"),
            intended_status=data.get("intended_status"),
            gpu_name=data.get("gpu_name"),
            gpu_arch=data.get("gpu_arch"),
            gpu_totalram=data.get("gpu_totalram"),
            gpu_ram=data.get("gpu_ram"),
            gpu_util=data.get("gpu_util"),
            gpu_temp=data.get("gpu_temp"),
            num_gpus=data.get("num_gpus"),
            dph_total=data.get("dph_total"),
            dph_base=data.get("dph_base"),
            storage_cost=data.get("storage_cost"),
            storage_total_cost=data.get("storage_total_cost"),
            disk_space=data.get("disk_space"),
            disk_usage=data.get("disk_usage"),
            ssh_idx=data.get("ssh_idx"),
            ssh_host=data.get("ssh_host"),
            ssh_port=data.get("ssh_port"),
            public_ipaddr=data.get("public_ipaddr"),
            direct_port_start=data.get("direct_port_start"),
            direct_port_end=data.get("direct_port_end"),
            label=data.get("label"),
            template_name=data.get("template_name"),
            image_uuid=data.get("image_uuid"),
            cpu_name=data.get("cpu_name"),
            cpu_cores=data.get("cpu_cores"),
            cpu_ram=data.get("cpu_ram"),
            machine_id=data.get("machine_id"),
            host_id=data.get("host_id"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            duration=data.get("duration"),
            geolocation=data.get("geolocation"),
            reliability2=data.get("reliability2"),
            country_code=data.get("country_code"),
        )

    def _parse_offer(self, data: Dict[str, Any]) -> VastOffer:
        """Parse API response into VastOffer."""
        return VastOffer(
            id=data.get("id", 0),
            gpu_name=data.get("gpu_name"),
            num_gpus=data.get("num_gpus"),
            gpu_ram=data.get("gpu_ram"),
            dph_total=data.get("dph_total"),
            reliability2=data.get("reliability2"),
            inet_down=data.get("inet_down"),
            inet_up=data.get("inet_up"),
            cpu_cores=data.get("cpu_cores"),
            cpu_ram=data.get("cpu_ram"),
        )


def get_vast_client() -> VastAPIClient:
    """
    Get a Vast.ai API client using stored credentials.

    Returns:
        VastAPIClient instance

    Raises:
        RuntimeError: If API key is not configured
    """
    from ..core.secrets import get_secrets_manager

    secrets = get_secrets_manager()
    api_key = secrets.get_vast_api_key()

    if not api_key:
        raise RuntimeError(
            "Vast.ai API key not configured. "
            "Run: train secrets set VAST_API_KEY"
        )

    return VastAPIClient(api_key)
