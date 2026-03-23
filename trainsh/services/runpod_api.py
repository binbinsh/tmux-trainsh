"""RunPod API clients for Pods and GPU type discovery."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..constants import (
    DEFAULT_RUNPOD_CONTAINER_DISK_GB,
    DEFAULT_RUNPOD_IMAGE,
    DEFAULT_RUNPOD_VOLUME_GB,
    RUNPOD_GRAPHQL_API_BASE,
    RUNPOD_REST_API_BASE,
)
from ..core.models import RunpodGPUType, RunpodPod


class RunpodAPIError(Exception):
    """Exception raised for RunPod API errors."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"RunPod API error ({status_code}): {message}")


@dataclass(frozen=True)
class RunpodPriceRequest:
    """Inputs used to query current GPU type availability and price hints."""

    gpu_count: int = 1
    min_memory_gb: int = 0
    min_vcpu_count: int = 2
    secure_cloud: bool = True


class RunpodAPIClient:
    """RunPod REST + GraphQL client."""

    def __init__(self, api_key: str):
        self.api_key = str(api_key or "").strip()
        self.rest_base_url = RUNPOD_REST_API_BASE
        self.graphql_base_url = RUNPOD_GRAPHQL_API_BASE

    def _rest_request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.rest_base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req) as response:
                payload = response.read().decode("utf-8")
                if not payload:
                    return {}
                return json.loads(payload)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8") if exc.fp else ""
            raise RunpodAPIError(exc.code, error_body)
        except URLError as exc:
            raise RunpodAPIError(0, str(exc.reason))

    def _graphql_request(self, query: str) -> Dict[str, Any]:
        url = f"{self.graphql_base_url}?api_key={quote(self.api_key, safe='')}"
        req = Request(
            url,
            data=json.dumps({"query": query}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8") if exc.fp else ""
            raise RunpodAPIError(exc.code, error_body)
        except URLError as exc:
            raise RunpodAPIError(0, str(exc.reason))

        errors = payload.get("errors") or []
        if errors:
            message = "; ".join(str(item.get("message", item)) for item in errors)
            raise RunpodAPIError(400, message or "GraphQL request failed")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RunpodAPIError(0, "Invalid GraphQL response")
        return data

    def list_pods(self) -> List[RunpodPod]:
        response = self._rest_request("pods")
        raw_pods = response.get("items") if isinstance(response, dict) else None
        if raw_pods is None and isinstance(response, dict):
            raw_pods = response.get("pods")
        if raw_pods is None and isinstance(response, list):
            raw_pods = response
        return [self._parse_pod(item) for item in list(raw_pods or [])]

    def get_pod(self, pod_id: str) -> RunpodPod:
        response = self._rest_request(f"pods/{pod_id}")
        if not response:
            raise RunpodAPIError(404, f"Pod {pod_id} not found.")
        return self._parse_pod(response)

    def create_pod(
        self,
        *,
        name: str,
        gpu_type_id: str,
        gpu_count: int = 1,
        image_name: str = DEFAULT_RUNPOD_IMAGE,
        cloud_type: str = "SECURE",
        container_disk_in_gb: int = DEFAULT_RUNPOD_CONTAINER_DISK_GB,
        volume_in_gb: int = DEFAULT_RUNPOD_VOLUME_GB,
        ports: Optional[List[str]] = None,
        support_public_ip: bool = True,
    ) -> RunpodPod:
        payload = {
            "computeType": "GPU",
            "name": str(name or "").strip() or "tmux-trainsh",
            "imageName": image_name,
            "gpuCount": max(int(gpu_count or 1), 1),
            "gpuTypeIds": [str(gpu_type_id).strip()],
            "cloudType": str(cloud_type or "SECURE").strip().upper(),
            "containerDiskInGb": int(container_disk_in_gb or DEFAULT_RUNPOD_CONTAINER_DISK_GB),
            "volumeInGb": int(volume_in_gb or DEFAULT_RUNPOD_VOLUME_GB),
            "volumeMountPath": "/workspace",
            "ports": list(ports or ["22/tcp"]),
            "supportPublicIp": bool(support_public_ip),
        }
        response = self._rest_request("pods", method="POST", data=payload)
        return self._parse_pod(response)

    def start_pod(self, pod_id: str) -> None:
        self._rest_request(f"pods/{pod_id}/start", method="POST")

    def stop_pod(self, pod_id: str) -> None:
        self._rest_request(f"pods/{pod_id}/stop", method="POST")

    def restart_pod(self, pod_id: str) -> None:
        self._rest_request(f"pods/{pod_id}/restart", method="POST")

    def reset_pod(self, pod_id: str) -> None:
        self._rest_request(f"pods/{pod_id}/reset", method="POST")

    def delete_pod(self, pod_id: str) -> None:
        self._rest_request(f"pods/{pod_id}", method="DELETE")

    def update_pod_name(self, pod_id: str, name: str) -> RunpodPod:
        response = self._rest_request(f"pods/{pod_id}/update", method="POST", data={"name": str(name).strip()})
        return self._parse_pod(response)

    def list_gpu_types(
        self,
        *,
        gpu_name: Optional[str] = None,
        max_dph: Optional[float] = None,
        min_gpu_ram: Optional[float] = None,
        gpu_count: int = 1,
        secure_cloud: bool = True,
    ) -> List[RunpodGPUType]:
        request = RunpodPriceRequest(
            gpu_count=max(int(gpu_count or 1), 1),
            min_memory_gb=max(int(math.ceil(float(min_gpu_ram or 0))), 0),
            secure_cloud=bool(secure_cloud),
        )
        id_filter = f'(input: {{ id: "{self._graphql_escape(gpu_name)}" }})' if gpu_name and not any(ch in gpu_name for ch in "*?") else ""
        query = f"""
        query {{
          gpuTypes{id_filter} {{
            id
            displayName
            memoryInGb
            securePrice
            communityPrice
            secureSpotPrice
            lowestPrice(input: {{
              compliance: null,
              dataCenterId: null,
              globalNetwork: false,
              gpuCount: {request.gpu_count},
              minDisk: 0,
              minMemoryInGb: {request.min_memory_gb},
              minVcpuCount: {request.min_vcpu_count},
              secureCloud: {"true" if request.secure_cloud else "false"}
            }}) {{
              minimumBidPrice
              uninterruptablePrice
              minVcpu
              minMemory
              stockStatus
              availableGpuCounts
            }}
          }}
        }}
        """
        response = self._graphql_request(query)
        gpu_types = [self._parse_gpu_type(item) for item in list(response.get("gpuTypes") or [])]

        if gpu_name:
            needle = gpu_name.strip().lower()
            gpu_types = [
                item
                for item in gpu_types
                if needle in str(item.id or "").lower() or needle in str(item.display_name or "").lower()
            ]
        if min_gpu_ram is not None:
            gpu_types = [
                item
                for item in gpu_types
                if item.memory_gb is None or item.memory_gb >= float(min_gpu_ram)
            ]
        if max_dph is not None:
            gpu_types = [
                item
                for item in gpu_types
                if item.best_hourly_price <= float(max_dph)
            ]
        return gpu_types

    @staticmethod
    def _graphql_escape(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _parse_pod(self, data: Dict[str, Any]) -> RunpodPod:
        gpu = data.get("gpu") if isinstance(data.get("gpu"), dict) else {}
        mappings = data.get("portMappings") if isinstance(data.get("portMappings"), dict) else {}
        normalized_mappings = {
            str(key): int(value)
            for key, value in mappings.items()
            if str(key).strip() and value not in (None, "")
        }
        return RunpodPod(
            id=str(data.get("id", "")).strip(),
            desired_status=data.get("desiredStatus"),
            name=data.get("name"),
            image_name=data.get("imageName") or data.get("image"),
            public_ip=data.get("publicIp"),
            port_mappings=normalized_mappings or None,
            ports=list(data.get("ports") or []),
            gpu_type_id=gpu.get("id") or data.get("gpuTypeId"),
            gpu_display_name=gpu.get("displayName") or data.get("gpuTypeId"),
            gpu_count=gpu.get("count") or data.get("gpuCount"),
            gpu_memory_gb=self._coerce_float(gpu.get("memoryInGb")),
            cost_per_hr=self._coerce_float(data.get("costPerHr")),
            cloud_type=data.get("cloudType"),
            container_disk_in_gb=self._coerce_int(data.get("containerDiskInGb")),
            volume_in_gb=self._coerce_int(data.get("volumeInGb")),
            template_id=data.get("templateId"),
        )

    def _parse_gpu_type(self, data: Dict[str, Any]) -> RunpodGPUType:
        lowest_price = data.get("lowestPrice") if isinstance(data.get("lowestPrice"), dict) else {}
        counts = lowest_price.get("availableGpuCounts")
        if not isinstance(counts, list):
            counts = None
        return RunpodGPUType(
            id=str(data.get("id", "")).strip(),
            display_name=data.get("displayName"),
            memory_gb=self._coerce_float(data.get("memoryInGb")),
            secure_price=self._coerce_float(data.get("securePrice")),
            community_price=self._coerce_float(data.get("communityPrice")),
            secure_spot_price=self._coerce_float(data.get("secureSpotPrice")),
            min_bid_price=self._coerce_float(lowest_price.get("minimumBidPrice")),
            uninterruptable_price=self._coerce_float(lowest_price.get("uninterruptablePrice")),
            min_vcpu=self._coerce_int(lowest_price.get("minVcpu")),
            min_memory_gb=self._coerce_float(lowest_price.get("minMemory")),
            stock_status=lowest_price.get("stockStatus"),
            available_gpu_counts=[int(item) for item in counts] if counts else None,
        )

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def get_runpod_client() -> RunpodAPIClient:
    """Build a RunPod client from configured secrets."""

    from ..core.secrets import get_secrets_manager

    secrets = get_secrets_manager()
    api_key = secrets.get_runpod_api_key()
    if not api_key:
        raise RuntimeError(
            "RunPod API key not configured. "
            "Run: train secrets set RUNPOD_API_KEY"
        )
    return RunpodAPIClient(api_key)
