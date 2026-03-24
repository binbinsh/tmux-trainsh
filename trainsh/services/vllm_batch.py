"""Local batch client helpers for OpenAI-compatible vLLM endpoints."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class BatchRequest:
    """One normalized batch request item."""

    request_id: str
    custom_id: str
    method: str
    url: str
    body: Dict[str, Any]


def parse_endpoint_name(value: str) -> str:
    """Normalize friendly endpoint aliases."""
    normalized = str(value or "chat").strip().lower().replace("_", "-")
    mapping = {
        "chat": "/chat/completions",
        "chat-completions": "/chat/completions",
        "completions": "/completions",
        "embedding": "/embeddings",
        "embeddings": "/embeddings",
    }
    return mapping.get(normalized, value)


def completed_request_ids(output_path: Path) -> set[str]:
    """Read completed request IDs from an existing JSONL output file."""
    completed: set[str] = set()
    if not output_path.exists():
        return completed
    try:
        lines = output_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return completed
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        request_id = str(
            payload.get("request_id")
            or payload.get("custom_id")
            or payload.get("id")
            or ""
        ).strip()
        if request_id:
            completed.add(request_id)
    return completed


def resolve_request_url(base_url: str, path: str) -> str:
    """Join a base URL and request path without duplicating `/v1`."""
    cleaned_base = str(base_url or "").rstrip("/")
    cleaned_path = str(path or "").strip()
    if cleaned_path.startswith("http://") or cleaned_path.startswith("https://"):
        return cleaned_path
    if not cleaned_path.startswith("/"):
        cleaned_path = "/" + cleaned_path
    if cleaned_base.endswith("/v1") and cleaned_path.startswith("/v1/"):
        cleaned_base = cleaned_base[: -len("/v1")]
    return cleaned_base + cleaned_path


def normalize_request_line(payload: Dict[str, Any], *, line_num: int, default_path: str) -> BatchRequest:
    """Convert one input JSON object into a normalized batch request."""
    custom_id = str(payload.get("custom_id") or payload.get("id") or f"line-{line_num}").strip()
    request_id = custom_id or f"line-{line_num}"
    method = str(payload.get("method", "POST")).strip().upper() or "POST"
    if "body" in payload and isinstance(payload.get("body"), dict):
        body = dict(payload.get("body") or {})
        path = str(payload.get("url") or payload.get("path") or default_path).strip() or default_path
    else:
        body = dict(payload)
        for key in ("custom_id", "id", "method", "url", "path"):
            body.pop(key, None)
        path = str(default_path).strip()
    return BatchRequest(
        request_id=request_id,
        custom_id=custom_id,
        method=method,
        url=path,
        body=body,
    )


def load_batch_requests(input_path: Path, *, default_path: str, completed: set[str]) -> list[BatchRequest]:
    """Load pending JSONL requests from disk."""
    pending: list[BatchRequest] = []
    try:
        lines = input_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Failed to read input file: {exc}") from exc
    for line_num, raw_line in enumerate(lines, start=1):
        text = raw_line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"Invalid JSONL line {line_num}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Invalid JSONL line {line_num}: expected object")
        request = normalize_request_line(payload, line_num=line_num, default_path=default_path)
        if request.request_id in completed:
            continue
        pending.append(request)
    return pending


def decode_response_bytes(payload: bytes, *, headers=None) -> str:
    """Decode HTTP response bytes using the announced charset when possible."""
    encoding = "utf-8"
    if headers is not None:
        try:
            parsed = headers.get_content_charset()
            if parsed:
                encoding = parsed
        except Exception:
            pass
    try:
        return payload.decode(encoding, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def request_once(
    *,
    method: str,
    url: str,
    body: Dict[str, Any],
    timeout: int,
    api_key: str = "",
) -> tuple[bool, int | None, Any, str]:
    """Send one OpenAI-compatible HTTP request."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout))) as response:
            payload = response.read()
            text = decode_response_bytes(payload, headers=response.headers)
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = text
            return True, int(getattr(response, "status", 0) or 0), parsed, ""
    except urllib.error.HTTPError as exc:
        payload = exc.read() if hasattr(exc, "read") else b""
        text = decode_response_bytes(payload, headers=getattr(exc, "headers", None))
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = text
        return False, int(exc.code) if exc.code is not None else None, parsed, str(exc)
    except urllib.error.URLError as exc:
        return False, None, None, str(exc)
    except Exception as exc:
        return False, None, None, str(exc)


def run_batch_request(
    request: BatchRequest,
    *,
    base_url: str,
    timeout: int,
    retries: int,
    api_key: str,
) -> Dict[str, Any]:
    """Execute one batch request with retries."""
    request_url = resolve_request_url(base_url, request.url)
    last_error = ""
    last_status: int | None = None
    last_response: Any = None
    attempts = max(1, int(retries) + 1)
    for attempt in range(1, attempts + 1):
        ok, status, response, error = request_once(
            method=request.method,
            url=request_url,
            body=request.body,
            timeout=timeout,
            api_key=api_key,
        )
        if ok:
            return {
                "request_id": request.request_id,
                "custom_id": request.custom_id,
                "ok": True,
                "status_code": status,
                "url": request.url,
                "response": response,
            }
        last_error = error
        last_status = status
        last_response = response
        if attempt < attempts:
            time.sleep(min(5, attempt))
    return {
        "request_id": request.request_id,
        "custom_id": request.custom_id,
        "ok": False,
        "status_code": last_status,
        "url": request.url,
        "error": last_error or "request failed",
        "response": last_response,
    }
